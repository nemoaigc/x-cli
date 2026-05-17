"""Cookie authentication for x-cli.

Supports:
1. Profile file: ~/.config/x-cli/profiles/<name>.json (legacy ~/.config/x-query/ also read)
2. Environment variables: TWITTER_AUTH_TOKEN + TWITTER_CT0
3. Auto-extract from browser via browser-cookie3
"""

from __future__ import annotations

import glob
import json
import logging
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

from .constants import BEARER_TOKEN, get_user_agent
from .exceptions import AuthenticationError, InvalidInputError

logger = logging.getLogger(__name__)

_TWITTER_DOMAINS = {"x.com", "twitter.com", ".x.com", ".twitter.com"}

_KEYCHAIN_ERROR_KEYWORDS = (
    "key for cookie decryption",
    "safe storage",
    "keychain",
    "secretstorage",
)


def _is_twitter_domain(domain: str) -> bool:
    return domain in _TWITTER_DOMAINS or domain.endswith(".x.com") or domain.endswith(".twitter.com")


def _diagnose_keychain_issues(diagnostics: List[str]) -> Optional[str]:
    lowered = " ".join(diagnostics).lower()
    if not any(kw in lowered for kw in _KEYCHAIN_ERROR_KEYWORDS):
        return None
    is_ssh = bool(os.environ.get("SSH_CLIENT") or os.environ.get("SSH_TTY") or os.environ.get("SSH_CONNECTION"))
    if sys.platform == "darwin":
        if is_ssh:
            return (
                "macOS Keychain is locked (SSH session detected).\n"
                "  Fix: security unlock-keychain ~/Library/Keychains/login.keychain-db\n"
                "  Then retry the command."
            )
        return (
            "macOS Keychain permission denied.\n"
            "  Fix: Open Keychain Access → search for \"<Browser> Safe Storage\" → Access Control → add your Terminal app."
        )
    if sys.platform == "win32":
        return (
            "Windows DPAPI cookie decryption failed.\n"
            "  Workaround: Set TWITTER_AUTH_TOKEN and TWITTER_CT0 environment variables manually."
        )
    return "System keyring access failed — the cookie encryption key could not be retrieved."


def load_from_env() -> Optional[Dict[str, str]]:
    auth_token = os.environ.get("TWITTER_AUTH_TOKEN", "")
    ct0 = os.environ.get("TWITTER_CT0", "")
    if auth_token and ct0:
        return {"auth_token": auth_token, "ct0": ct0}
    return None


def load_from_profile(profile_name: str) -> Optional[Dict[str, str]]:
    """Load cookies from a saved profile file."""
    try:
        from .profiles import load_profile
        return load_profile(profile_name)
    except ValueError as exc:
        raise InvalidInputError(str(exc)) from exc


def load_default_profile() -> Optional[Dict[str, str]]:
    """Load the default profile if one is configured."""
    try:
        from .profiles import get_default_profile
        profile_name = get_default_profile()
        if profile_name:
            return load_from_profile(profile_name)
    except InvalidInputError as exc:
        # Surface misconfigured default-profile name (e.g. path traversal attempt)
        logger.warning("Default profile name is invalid: %s", exc)
    except Exception as exc:
        logger.debug("Failed to read default profile: %s", exc)
    return None


def verify_cookies(auth_token: str, ct0: str, cookie_string: Optional[str] = None) -> Dict[str, Any]:
    from .client import _get_cffi_session
    urls = [
        "https://api.x.com/1.1/account/verify_credentials.json",
        "https://x.com/i/api/1.1/account/settings.json",
    ]
    cookie_header = cookie_string or "auth_token=%s; ct0=%s" % (auth_token, ct0)
    headers = {
        "Authorization": "Bearer %s" % BEARER_TOKEN,
        "Cookie": cookie_header,
        "X-Csrf-Token": ct0,
        "X-Twitter-Active-User": "yes",
        "X-Twitter-Auth-Type": "OAuth2Session",
        "User-Agent": get_user_agent(),
    }
    session = _get_cffi_session()
    attempts = []
    for url in urls:
        endpoint = url.split("/")[-1]
        try:
            resp = session.get(url, headers=headers, timeout=5)
            if resp.status_code in (401, 403):
                raise AuthenticationError(
                    "Cookie expired or invalid (HTTP %d). Please re-login to x.com." % resp.status_code
                )
            if resp.status_code == 200:
                data = resp.json()
                return {"screen_name": data.get("screen_name", "")}
            attempts.append("%s=%d" % (endpoint, resp.status_code))
            continue
        except RuntimeError:
            raise
        except Exception as e:
            attempts.append("%s=%s" % (endpoint, type(e).__name__))
            continue
    logger.info("Cookie verification skipped (attempts: %s)", ", ".join(attempts))
    return {}


def _extract_cookies_from_jar(jar: Any, source: str = "unknown") -> Optional[Dict[str, str]]:
    result: Dict[str, str] = {}
    all_cookies: Dict[str, str] = {}
    twitter_cookie_count = 0
    for cookie in jar:
        domain = cookie.domain or ""
        if _is_twitter_domain(domain):
            twitter_cookie_count += 1
            if cookie.name == "auth_token":
                result["auth_token"] = cookie.value
            elif cookie.name == "ct0":
                result["ct0"] = cookie.value
            if cookie.name and cookie.value:
                all_cookies[cookie.name] = cookie.value
    if "auth_token" in result and "ct0" in result:
        cookies = {"auth_token": result["auth_token"], "ct0": result["ct0"]}
        if all_cookies:
            cookies["cookie_string"] = "; ".join("%s=%s" % (k, v) for k, v in all_cookies.items())
        return cookies
    return None


_CHROMIUM_BASE_DIRS: Dict[str, str] = {
    "vivaldi": "Vivaldi",
    "chrome": os.path.join("Google", "Chrome"),
    "edge": "Microsoft Edge",
}

# Order matters: first one that returns valid cookies wins.
# Vivaldi is the primary browser; chrome/edge are fallbacks.
_DEFAULT_BROWSER_ORDER = ["vivaldi", "chrome", "edge"]
_SUPPORTED_BROWSERS = {"vivaldi", "chrome", "edge"}


def _get_browser_order() -> List[str]:
    env = os.environ.get("TWITTER_BROWSER", "").strip().lower()
    if not env:
        return _DEFAULT_BROWSER_ORDER
    if env not in _SUPPORTED_BROWSERS:
        logger.warning("TWITTER_BROWSER='%s' is invalid, using default order", env)
        return _DEFAULT_BROWSER_ORDER
    return [env] + [b for b in _DEFAULT_BROWSER_ORDER if b != env]


def _iter_chrome_cookie_files(browser_name: str) -> List[str]:
    base_dir = _CHROMIUM_BASE_DIRS.get(browser_name)
    if base_dir is None:
        return []
    if sys.platform == "darwin":
        root = os.path.join(os.path.expanduser("~"), "Library", "Application Support", base_dir)
    elif sys.platform == "win32":
        if browser_name == "edge":
            root = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "User Data")
        else:
            root = os.path.join(os.environ.get("LOCALAPPDATA", ""), base_dir)
    else:
        if browser_name == "edge":
            root = os.path.join(os.path.expanduser("~"), ".config", "microsoft-edge")
        else:
            root = os.path.join(os.path.expanduser("~"), ".config", base_dir)
    if not os.path.isdir(root):
        return []
    env_profile = os.environ.get("TWITTER_CHROME_PROFILE", "").strip()
    if env_profile:
        cookie_path = os.path.join(root, env_profile, "Cookies")
        if os.path.exists(cookie_path):
            return [cookie_path]
        return []
    paths: List[str] = []
    default_cookies = os.path.join(root, "Default", "Cookies")
    if os.path.exists(default_cookies):
        paths.append(default_cookies)
    for profile_dir in sorted(glob.glob(os.path.join(root, "Profile *"))):
        cookie_file = os.path.join(profile_dir, "Cookies")
        if os.path.exists(cookie_file):
            paths.append(cookie_file)
    return paths


def _extract_in_process() -> Tuple[Optional[Dict[str, str]], List[str]]:
    try:
        import browser_cookie3
    except ImportError:
        return None, ["browser-cookie3 not installed"]

    browser_fns = {
        "vivaldi": browser_cookie3.vivaldi,
        "chrome": browser_cookie3.chrome,
        "edge": browser_cookie3.edge,
    }
    attempts: List[str] = []
    diagnostics: List[str] = []

    for name in _get_browser_order():
        fn = browser_fns[name]
        if name in _CHROMIUM_BASE_DIRS:
            cookie_files = _iter_chrome_cookie_files(name)
            if not cookie_files:
                try:
                    jar = fn()
                except Exception as e:
                    attempts.append("%s=%s" % (name, type(e).__name__))
                    diagnostics.append("%s: %s" % (name, e))
                    continue
                cookies = _extract_cookies_from_jar(jar, source="%s(in-process)" % name)
                if cookies:
                    return cookies, diagnostics
                attempts.append("%s=no-cookies" % name)
                continue
            for cookie_file in cookie_files:
                profile_name = os.path.basename(os.path.dirname(cookie_file))
                try:
                    jar = fn(cookie_file=cookie_file)
                except Exception as e:
                    attempts.append("%s[%s]=%s" % (name, profile_name, type(e).__name__))
                    diagnostics.append("%s[%s]: %s" % (name, profile_name, e))
                    continue
                cookies = _extract_cookies_from_jar(jar, source="%s[%s]" % (name, profile_name))
                if cookies:
                    return cookies, diagnostics
                attempts.append("%s[%s]=no-cookies" % (name, profile_name))
        else:
            try:
                jar = fn()
            except Exception as e:
                attempts.append("%s=%s" % (name, type(e).__name__))
                diagnostics.append("%s: %s" % (name, e))
                continue
            cookies = _extract_cookies_from_jar(jar, source="%s(in-process)" % name)
            if cookies:
                return cookies, diagnostics
            attempts.append("%s=no-cookies" % name)

    if attempts:
        logger.debug("In-process extraction attempts: %s", ", ".join(attempts))
    return None, diagnostics


def _extract_via_subprocess() -> Tuple[Optional[Dict[str, str]], List[str]]:
    extract_script = '''
import glob, json, os, sys
try:
    import browser_cookie3
except ImportError:
    print(json.dumps({"error": "browser-cookie3 not installed"}))
    sys.exit(1)

CHROMIUM_BASE_DIRS = {
    "vivaldi": "Vivaldi",
    "chrome": os.path.join("Google", "Chrome"),
    "edge": "Microsoft Edge",
}

def iter_cookie_files(browser_name):
    base_dir = CHROMIUM_BASE_DIRS.get(browser_name)
    if base_dir is None:
        return []
    if sys.platform == "darwin":
        root = os.path.join(os.path.expanduser("~"), "Library", "Application Support", base_dir)
    elif sys.platform == "win32":
        if browser_name == "edge":
            root = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "User Data")
        else:
            root = os.path.join(os.environ.get("LOCALAPPDATA", ""), base_dir)
    else:
        if browser_name == "edge":
            root = os.path.join(os.path.expanduser("~"), ".config", "microsoft-edge")
        else:
            root = os.path.join(os.path.expanduser("~"), ".config", base_dir)
    if not os.path.isdir(root):
        return []
    env_profile = os.environ.get("TWITTER_CHROME_PROFILE", "").strip()
    if env_profile:
        p = os.path.join(root, env_profile, "Cookies")
        return [p] if os.path.exists(p) else []
    paths = []
    d = os.path.join(root, "Default", "Cookies")
    if os.path.exists(d):
        paths.append(d)
    for pd in sorted(glob.glob(os.path.join(root, "Profile *"))):
        cf = os.path.join(pd, "Cookies")
        if os.path.exists(cf):
            paths.append(cf)
    return paths

def extract_from_jar(jar, name, profile=""):
    result = {}
    all_cookies = {}
    for cookie in jar:
        domain = cookie.domain or ""
        if domain.endswith(".x.com") or domain.endswith(".twitter.com") or domain in ("x.com", "twitter.com", ".x.com", ".twitter.com"):
            if cookie.name == "auth_token":
                result["auth_token"] = cookie.value
            elif cookie.name == "ct0":
                result["ct0"] = cookie.value
            if cookie.name and cookie.value:
                all_cookies[cookie.name] = cookie.value
    if "auth_token" in result and "ct0" in result:
        result["browser"] = name
        if profile:
            result["profile"] = profile
        result["all_cookies"] = all_cookies
        return result
    return None

DEFAULT_ORDER = ["vivaldi", "chrome", "edge"]
env_browser = os.environ.get("TWITTER_BROWSER", "").strip().lower()
if env_browser in {"vivaldi", "chrome", "edge"}:
    browser_order = [env_browser] + [b for b in DEFAULT_ORDER if b != env_browser]
else:
    browser_order = DEFAULT_ORDER
browser_fns = {
    "vivaldi": browser_cookie3.vivaldi,
    "chrome": browser_cookie3.chrome,
    "edge": browser_cookie3.edge,
}
attempts = []

for name in browser_order:
    fn = browser_fns[name]
    if name in CHROMIUM_BASE_DIRS:
        cookie_files = iter_cookie_files(name)
        if not cookie_files:
            try:
                jar = fn()
            except Exception as exc:
                attempts.append(f"{name}={type(exc).__name__}: {exc}")
                continue
            r = extract_from_jar(jar, name)
            if r:
                print(json.dumps(r))
                sys.exit(0)
            attempts.append(f"{name}=no-cookies")
            continue
        for cf in cookie_files:
            pname = os.path.basename(os.path.dirname(cf))
            try:
                jar = fn(cookie_file=cf)
            except Exception as exc:
                attempts.append(f"{name}[{pname}]={type(exc).__name__}: {exc}")
                continue
            r = extract_from_jar(jar, name, pname)
            if r:
                print(json.dumps(r))
                sys.exit(0)
            attempts.append(f"{name}[{pname}]=no-cookies")
    else:
        try:
            jar = fn()
        except Exception as exc:
            attempts.append(f"{name}={type(exc).__name__}: {exc}")
            continue
        r = extract_from_jar(jar, name)
        if r:
            print(json.dumps(r))
            sys.exit(0)
        attempts.append(f"{name}=no-cookies")

print(json.dumps({
    "error": "No Twitter cookies found in any browser.",
    "attempts": attempts,
}))
sys.exit(1)
'''
    diagnostics: List[str] = []

    def _run(cmd, timeout, label):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None, False
        except FileNotFoundError:
            return None, False
        output = result.stdout.strip()
        if not output:
            return None, True
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            return None, True
        if "error" in data:
            attempts_list = data.get("attempts") or []
            diagnostics.extend(str(item) for item in attempts_list)
            retryable = data.get("error") == "browser-cookie3 not installed"
            return None, retryable
        return data, False

    data, retry_with_uv = _run([sys.executable, "-c", extract_script], 15, "current env")
    if data is None and retry_with_uv:
        data, _ = _run(
            ["uv", "run", "--with", "browser-cookie3", "python", "-c", extract_script],
            30, "uv fallback",
        )
    if data is None:
        return None, diagnostics
    cookies: Dict[str, str] = {"auth_token": data["auth_token"], "ct0": data["ct0"]}
    all_cookies = data.get("all_cookies", {})
    if all_cookies:
        cookies["cookie_string"] = "; ".join("%s=%s" % (k, v) for k, v in all_cookies.items())
    return cookies, diagnostics


def extract_from_browser() -> Tuple[Optional[Dict[str, str]], List[str]]:
    all_diagnostics: List[str] = []
    cookies, diag = _extract_in_process()
    all_diagnostics.extend(diag)
    if cookies:
        return cookies, all_diagnostics
    logger.debug("In-process extraction failed, trying subprocess fallback")
    cookies, diag = _extract_via_subprocess()
    all_diagnostics.extend(diag)
    return cookies, all_diagnostics


def get_cookies(profile: Optional[str] = None) -> Dict[str, str]:
    """Get cookies. Priority: profile file → env vars → browser extraction.

    Args:
        profile: Named profile from ~/.config/x-cli/profiles/<name>.json.
                 If None, checks XCLI_PROFILE / XQ_PROFILE env vars, then
                 default-profile file, then falls through to env vars and
                 browser extraction.
    """
    cookies: Optional[Dict[str, str]] = None
    diagnostics: List[str] = []

    # 1. Named profile (XCLI_PROFILE preferred; XQ_PROFILE kept for back-compat)
    effective_profile = (
        profile
        or os.environ.get("XCLI_PROFILE", "").strip()
        or os.environ.get("XQ_PROFILE", "").strip()
    )
    if effective_profile:
        cookies = load_from_profile(effective_profile)
        if cookies:
            logger.info("Loaded cookies from profile: %s", effective_profile)
            return cookies

    # 2. Default profile
    if not effective_profile:
        cookies = load_default_profile()
        if cookies:
            logger.info("Loaded cookies from default profile")
            return cookies

    # 3. Environment variables
    cookies = load_from_env()
    if cookies:
        logger.info("Loaded cookies from environment variables")
        return cookies

    # 4. Browser extraction
    logger.debug("Attempting browser cookie extraction")
    cookies, diagnostics = extract_from_browser()

    if not cookies:
        lines = ["No Twitter/X cookies found."]
        hint = _diagnose_keychain_issues(diagnostics)
        if hint:
            lines.append("")
            lines.append("Likely cause:")
            lines.extend("  " + line for line in hint.splitlines())
            lines.append("")
        lines.append("Option 1: Set TWITTER_AUTH_TOKEN and TWITTER_CT0 environment variables")
        lines.append("Option 2: Make sure you are logged into x.com in your browser")
        lines.append("Option 3: Run 'uv run scripts/profile.py add <name>' to save a profile")
        raise AuthenticationError("\n".join(lines))

    try:
        verify_cookies(cookies["auth_token"], cookies["ct0"], cookies.get("cookie_string"))
    except AuthenticationError as exc:
        logger.info("Cookie verification failed, re-extracting from browser")
        fresh_cookies, _ = extract_from_browser()
        if not fresh_cookies:
            raise AuthenticationError(
                f"Browser cookies failed verification ({exc}) and re-extraction returned nothing."
                " Re-login to x.com or run 'profile.py add <name>'."
            ) from exc
        try:
            verify_cookies(
                fresh_cookies["auth_token"],
                fresh_cookies["ct0"],
                fresh_cookies.get("cookie_string"),
            )
        except AuthenticationError as refresh_exc:
            raise AuthenticationError(
                f"Freshly extracted browser cookies also failed ({refresh_exc}). "
                f"Original error: {exc}. Re-login to x.com and retry."
            ) from refresh_exc
        return fresh_cookies
    return cookies
