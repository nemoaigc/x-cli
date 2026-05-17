# TASK — x-cli typer refactor (in progress)

> See SPEC.md for the full command surface that must be preserved. Each
> command is TDD'd: test first, implement, green, next.

## Phase 1 — typer scaffold + commands (this work)

### Setup
- [x] git init + snapshot baseline (commit `d4b9794`)
- [x] SPEC.md — feature matrix locked
- [ ] pyproject: add typer + pytest deps + `[project.scripts]` entry
- [ ] src/x_cli/ skeleton (`__main__.py`, `commands/`, `core/`)
- [ ] move `scripts/_core/` → `src/x_cli/core/` (rename imports)
- [ ] common output helpers (JSON envelope, --json/--yaml/--profile/-v)
- [ ] CliRunner test fixture in `tests/conftest.py`

### Command implementations (TDD: red → green per cmd)
- [ ] `auth status / add / list / remove / use`            (was profile.py)
- [ ] `user HANDLE` (default = profile metadata — NEW)
- [ ] `user HANDLE --tweets / --replies / --media / --likes / --articles / --highlights`
- [ ] `user HANDLE --followers / --following / --recommended`
- [ ] `user --recommended` (general, no handle)
- [ ] `user search QUERY`                                  (was --search-users)
- [ ] `search QUERY [--since --until --lang --from-user --min-likes --min-retweets --product --top]`
- [ ] `tweet ID_OR_URL`                                    (was --tweet)
- [ ] `tweet article ID_OR_URL`                            (was --article)
- [ ] `tweet batch ID [ID...]`                             (was --batch)
- [ ] `feed list`                                          (was --feeds)
- [ ] `feed NAME [--top]`                                  (was --feed)
- [ ] `list LIST_ID [--top]`                               (was --list)
- [ ] `trend scan [--scan-drill-top --top]`                (was digest --scan)
- [ ] `trend drill TREND_ID [--top]`                       (was digest --drill)
- [ ] `me status / health / likes / bookmarks / mentions`  (was me.py reads)
- [ ] `engage like / unlike / retweet / unretweet / bookmark / unbookmark`  (was me.py writes)
- [ ] `post --text [--reply-to --quote --media --long] [--dry-run|--yes]`
- [ ] `post delete / pin / unpin / hide-reply / unhide-reply`
- [ ] `follow HANDLE / follow remove / block / unblock / mute / unmute`
- [ ] `follow queue add / list / tick / clear`            (was follow_queue.py)
- [ ] `x-list create / delete / add / remove`              (was write.py list-*)

### Shared utilities (extract from scripts → core/cli_helpers.py)
- [ ] `--top` rank/filter flags (article + post thresholds, --product, --since/--until/--lang)
- [ ] dry-run / --yes plan→execute pattern (for write/engage/follow/post/x-list)
- [ ] audit log writer (was `_audit` in write.py + follow_queue.py)

### Cleanup
- [ ] DELETE `scripts/` (only after every command above is green)
- [ ] DELETE SKILL.md, references/, schema.json (these move to x-cli-skill repo)
- [ ] Rewrite README.md as pure CLI usage docs (no LLM prompts)
- [ ] Update pyproject metadata (description, keywords — drop "claude-skill")

## Phase 2 — extract Skill (next session)
- [ ] Create `personal/skills/x-cli-skill/` with SKILL.md + references/
- [ ] Update references/*.md to call `x-cli user @h --json` instead of `uv run scripts/user.py`
- [ ] Push to `nemoaigc/x-cli-skill`

## Phase 3 — server integration (later session)
- [ ] git submodule add `nemoaigc/x-cli` → `server/vendor/x-cli`
- [ ] server/Dockerfile: install x-cli
- [ ] `app/services/community/x_bridge.py`: HTTP → subprocess
- [ ] Railway env: `TWITTER_AUTH_TOKEN`, `TWITTER_CT0`
- [ ] Remove `TWITTER_CLI_URL`, `TWITTER_CLI_API_KEY` config + Settings UI fields
- [ ] Search rate-limit (3 layer: in-run dedupe + 8/run cap + 24h cross-task cache)
