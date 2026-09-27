#!/usr/bin/env python3
"""Validate the static SolarVault NG release and compatibility contract."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "custom_components" / "jackery" / "manifest.json"
NG_REPOSITORY = "https://github.com/fred-head/ha-jackery-solarvault-ng"
MINIMUM_HA = "2025.8.0"


def _load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def contract_errors() -> list[str]:
    """Return all static release-contract violations."""
    errors: list[str] = []
    manifest = _load_json(MANIFEST)
    hacs = _load_json(ROOT / "hacs.json")
    with (ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)

    if manifest.get("documentation") != NG_REPOSITORY:
        errors.append("manifest documentation must point to the NG repository")
    if manifest.get("issue_tracker") != f"{NG_REPOSITORY}/issues":
        errors.append("manifest issue_tracker must point to the NG issue tracker")
    version = manifest.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        errors.append("manifest version must be an unprefixed X.Y.Z release version")
    if hacs.get("homeassistant") != MINIMUM_HA:
        errors.append(f"hacs homeassistant must match the evidenced floor {MINIMUM_HA}")

    project = pyproject.get("project", {})
    if project.get("name") != "ha-jackery-solarvault-ng-tooling":
        errors.append("pyproject name must identify the NG tooling environment")
    if project.get("version") != "0.0.0":
        errors.append("pyproject version must remain the non-release tooling sentinel 0.0.0")
    if project.get("requires-python") != ">=3.13.2,<3.14":
        errors.append("pyproject Python range must match the locked HA 2025.8+ tooling contract")
    if (ROOT / ".python-version").read_text(encoding="utf-8").strip() != "3.13.5":
        errors.append(".python-version must pin the tested tooling interpreter 3.13.5")

    release_script = (ROOT / "release.sh").read_text(encoding="utf-8")
    # Compose forbidden historical targets so repository-wide literal searches
    # flag only an actual executable destination, not this denylist.
    for stale_target in ("csoscd" + "/ha-solarvault", "ht-it-lab" + "/jackery"):
        if stale_target in release_script:
            errors.append(f"release.sh contains stale release target {stale_target}")
    for unsafe_operation in ("git add .", "git tag -d", "git push origin :refs/tags/"):
        if unsafe_operation in release_script:
            errors.append(f"release.sh contains unsafe operation: {unsafe_operation}")
    if "This script intentionally did not create or push anything" not in release_script:
        errors.append("release.sh must remain a preflight-only tool")
    if "uv sync --frozen --all-groups" not in release_script:
        errors.append("release.sh must install the complete frozen quality-gate environment")
    if (ROOT / "prepare_release.sh").exists():
        errors.append("legacy prepare_release.sh must not coexist with the release preflight")

    workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text(encoding="utf-8")
    if workflow.count('python-version: "3.13.5"') != 2:
        errors.append("test and lint jobs must pin Python 3.13.5")
    if workflow.count("uv sync --frozen") != 2:
        errors.append("test and lint jobs must install from the frozen lock")
    return errors


def main() -> int:
    """Print a concise result and return a shell-friendly exit status."""
    errors = contract_errors()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Release and compatibility contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
