"""Bundled agent skill installer tests."""
from __future__ import annotations

import json
from pathlib import Path


def test_skill_path_points_to_bundled_x_research(cli):
    result = cli(["skill", "path"])

    assert result.exit_code == 0, result.stderr
    body = result.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["name"] == "x-research"
    skill_path = Path(data["path"])
    assert (skill_path / "SKILL.md").exists()
    assert (skill_path / "commands" / "x.md").exists()


def test_skill_install_links_claude_and_codex(tmp_path, cli):
    result = cli(["skill", "install", "--home", str(tmp_path)])

    assert result.exit_code == 0, result.stderr
    body = result.json()
    installs = body["data"]["installs"]
    statuses = {item["status"] for item in installs}
    assert statuses == {"linked"}

    assert (tmp_path / ".claude" / "skills" / "x-research").is_symlink()
    assert (tmp_path / ".claude" / "commands" / "x.md").is_symlink()
    assert (tmp_path / ".claude" / "commands" / "x-research.md").is_symlink()
    assert (tmp_path / ".claude" / "commands" / "x-cli.md").is_symlink()
    assert (tmp_path / ".codex" / "skills" / "x-research").is_symlink()


def test_skill_install_is_idempotent_for_existing_links(tmp_path, cli):
    first = cli(["skill", "install", "--home", str(tmp_path)])
    assert first.exit_code == 0, first.stderr

    second = cli(["skill", "install", "--home", str(tmp_path)])
    assert second.exit_code == 0, second.stderr
    statuses = {item["status"] for item in second.json()["data"]["installs"]}
    assert statuses == {"already_installed"}


def test_skill_install_refuses_existing_real_directory(tmp_path, cli):
    existing = tmp_path / ".claude" / "skills" / "x-research"
    existing.mkdir(parents=True)

    result = cli(["skill", "install", "--home", str(tmp_path), "--force"])

    assert result.exit_code == 0, result.stderr
    body = json.loads(result.stdout)
    claude_skill = next(
        item for item in body["data"]["installs"]
        if item["kind"] == "claude_skill"
    )
    assert claude_skill["status"] == "refused_directory"
    assert existing.is_dir()
    assert not existing.is_symlink()


def test_skill_install_can_copy_instead_of_linking(tmp_path, cli):
    result = cli([
        "skill", "install",
        "--home", str(tmp_path),
        "--copy",
        "--no-codex",
    ])

    assert result.exit_code == 0, result.stderr
    skill_dir = tmp_path / ".claude" / "skills" / "x-research"
    command = tmp_path / ".claude" / "commands" / "x.md"
    assert skill_dir.is_dir()
    assert not skill_dir.is_symlink()
    assert command.is_file()
    assert not command.is_symlink()
