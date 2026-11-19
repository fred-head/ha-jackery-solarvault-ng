"""Regression tests for release metadata and fail-closed release tooling."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from tools import check_release_contract
from tools.check_release_contract import contract_errors

ROOT = Path(__file__).resolve().parents[1]
NG_ORIGIN = "https://github.com/fred-head/ha-jackery-solarvault-ng.git"
MANIFEST_VERSION = json.loads(
    (ROOT / "custom_components" / "jackery" / "manifest.json").read_text(encoding="utf-8")
)["version"]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _release_repo(
    tmp_path: Path, *, origin: str = NG_ORIGIN, version: str = MANIFEST_VERSION
) -> Path:
    repo = tmp_path / "release-repo"
    (repo / "custom_components" / "jackery").mkdir(parents=True)
    (repo / "tools").mkdir()
    shutil.copy2(ROOT / "release.sh", repo / "release.sh")
    shutil.copy2(ROOT / "hacs.json", repo / "hacs.json")
    shutil.copy2(ROOT / "pyproject.toml", repo / "pyproject.toml")
    manifest = json.loads((ROOT / "custom_components" / "jackery" / "manifest.json").read_text())
    manifest["version"] = version
    (repo / "custom_components" / "jackery" / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "release-contract@example.invalid")
    _git(repo, "config", "user.name", "Release Contract Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "release contract fixture")
    _git(repo, "remote", "add", "origin", origin)
    return repo


def _preflight(
    repo: Path, version_tag: str | None = None, *, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "release.sh", version_tag if version_tag is not None else f"v{MANIFEST_VERSION}"],
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_static_release_contract_is_coherent() -> None:
    assert contract_errors() == []


@pytest.mark.parametrize("version", ["2.4.0", "3.0.0-rc.1", "3.0.0-rc.12"])
def test_manifest_accepts_stable_and_release_candidate_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str
) -> None:
    manifest = json.loads(check_release_contract.MANIFEST.read_text())
    manifest["version"] = version
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(check_release_contract, "MANIFEST", manifest_path)

    assert contract_errors() == []


@pytest.mark.parametrize(
    "version", [None, "v3.0.0", "3.0.0-rc", "3.0.0rc1", "3.0.0-rc.0", "3.0.0-rc.01", "3.0.0-rc.1\n"]
)
def test_manifest_refuses_invalid_release_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str | None
) -> None:
    manifest = json.loads(check_release_contract.MANIFEST.read_text())
    manifest["version"] = version
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(check_release_contract, "MANIFEST", manifest_path)

    assert contract_errors() == ["manifest version must be unprefixed X.Y.Z or X.Y.Z-rc.N (N >= 1)"]


@pytest.mark.parametrize(
    "tag", ["", "3.0.0", "v3.0", "v3.0.0-rc", "v3.0.0rc1", "v3.0.0-rc.0", "v3.0.0-rc.01", "v3.0.0-rc.1\n"]
)
def test_release_preflight_refuses_invalid_tags(tmp_path: Path, tag: str) -> None:
    repo = _release_repo(tmp_path)

    result = _preflight(repo, tag)

    assert result.returncode != 0
    assert "pass an exact version tag" in result.stderr


@pytest.mark.parametrize("version", ["2.4.0", "3.0.0-rc.1", "3.0.0-rc.12"])
def test_release_preflight_prints_manual_publication_without_creating_release_objects(
    tmp_path: Path, version: str
) -> None:
    repo = _release_repo(tmp_path, version=version)
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    git_path = shutil.which("git")
    assert git_path is not None
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Exercise the real preflight and Git guards without network or quality-gate
    # subprocesses. A write attempt through gh fails rather than publishing.
    scripts = {
        "git": (
            'if [[ "${1-}" == fetch ]]; then\n'
            '    printf "git %s\\n" "$*" >> "$JACKERY_PREFLIGHT_TEST_LOG"\n'
            "    exit 0\n"
            "fi\n"
            f'exec {shlex.quote(git_path)} "$@"\n'
        ),
        "uv": 'printf "uv %s\\n" "$*" >> "$JACKERY_PREFLIGHT_TEST_LOG"\n',
        "gh": (
            'printf "gh %s\\n" "$*" >> "$JACKERY_PREFLIGHT_TEST_LOG"\n'
            '[[ "${1-}" == run && "${2-}" == list ]] || exit 97\n'
            'printf "%s\\n" "$JACKERY_PREFLIGHT_TEST_HEAD"\n'
        ),
    }
    for name, script in scripts.items():
        executable = bin_dir / name
        executable.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + script, encoding="utf-8")
        executable.chmod(0o755)
    command_log = tmp_path / "preflight-commands.log"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "JACKERY_PREFLIGHT_TEST_LOG": str(command_log),
        "JACKERY_PREFLIGHT_TEST_HEAD": head,
    }

    result = _preflight(repo, f"v{version}", env=env)

    assert result.returncode == 0, result.stderr
    assert f"Release preflight passed for v{version} at {head}" in result.stdout
    command = next(line.strip() for line in result.stdout.splitlines() if line.strip().startswith("gh release create "))
    arguments = shlex.split(command)
    assert arguments[:4] == ["gh", "release", "create", f"v{version}"]
    assert ("--prerelease" in arguments) is ("-rc." in version)
    assert ("--latest=false" in arguments) is ("-rc." in version)
    assert _git(repo, "tag", "--list").stdout == ""
    assert _git(repo, "status", "--porcelain").stdout == ""
    commands = command_log.read_text().splitlines()
    github_commands = [shlex.split(line) for line in commands if line.startswith("gh ")]
    assert len(github_commands) == 1
    assert github_commands[0][:3] == ["gh", "run", "list"]


def test_release_preflight_refuses_wrong_repository(tmp_path: Path) -> None:
    repo = _release_repo(tmp_path, origin="https://github.com/example/wrong.git")

    result = _preflight(repo)

    assert result.returncode != 0
    assert "origin points to" in result.stderr


def test_release_preflight_refuses_non_main_branch(tmp_path: Path) -> None:
    repo = _release_repo(tmp_path)
    _git(repo, "switch", "-c", "release-candidate")

    result = _preflight(repo)

    assert result.returncode != 0
    assert "release source must be 'main'" in result.stderr


def test_release_preflight_refuses_dirty_tree(tmp_path: Path) -> None:
    repo = _release_repo(tmp_path)
    (repo / "uncommitted.txt").write_text("not part of a release\n", encoding="utf-8")

    result = _preflight(repo)

    assert result.returncode != 0
    assert "working tree is not clean" in result.stderr


def test_release_preflight_refuses_manifest_version_mismatch(tmp_path: Path) -> None:
    repo = _release_repo(tmp_path)

    result = subprocess.run(
        ["bash", "release.sh", "v999.999.999"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert f"does not match manifest version '{MANIFEST_VERSION}'" in result.stderr


def test_release_preflight_refuses_existing_tag(tmp_path: Path) -> None:
    repo = _release_repo(tmp_path)
    _git(repo, "tag", f"v{MANIFEST_VERSION}")

    result = _preflight(repo)

    assert result.returncode != 0
    assert f"tag 'v{MANIFEST_VERSION}' already exists locally" in result.stderr
