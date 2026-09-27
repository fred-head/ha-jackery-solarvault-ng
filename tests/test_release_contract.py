"""Regression tests for release metadata and fail-closed release tooling."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

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


def _release_repo(tmp_path: Path, *, origin: str = NG_ORIGIN) -> Path:
    repo = tmp_path / "release-repo"
    (repo / "custom_components" / "jackery").mkdir(parents=True)
    (repo / "tools").mkdir()
    shutil.copy2(ROOT / "release.sh", repo / "release.sh")
    shutil.copy2(ROOT / "hacs.json", repo / "hacs.json")
    shutil.copy2(ROOT / "pyproject.toml", repo / "pyproject.toml")
    manifest = json.loads((ROOT / "custom_components" / "jackery" / "manifest.json").read_text())
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


def _preflight(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "release.sh", f"v{MANIFEST_VERSION}"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def test_static_release_contract_is_coherent() -> None:
    assert contract_errors() == []


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
