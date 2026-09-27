#!/usr/bin/env bash
# Fail-closed release preflight. This script never creates tags or releases.
set -euo pipefail

readonly EXPECTED_REPOSITORY="fred-head/ha-jackery-solarvault-ng"
readonly EXPECTED_BRANCH="main"
readonly MANIFEST="custom_components/jackery/manifest.json"

fail() {
    printf 'Release preflight failed: %s\n' "$*" >&2
    exit 1
}

version_tag=${1:-}
[[ "$version_tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || \
    fail "pass an exact semantic version tag (vX.Y.Z)"

[[ -f "$MANIFEST" && -f "hacs.json" && -f "pyproject.toml" ]] || \
    fail "run this script from the repository root"

origin_url=$(git remote get-url origin 2>/dev/null) || fail "origin is not configured"
case "$origin_url" in
    "https://github.com/${EXPECTED_REPOSITORY}"|\
    "https://github.com/${EXPECTED_REPOSITORY}.git"|\
    "git@github.com:${EXPECTED_REPOSITORY}"|\
    "git@github.com:${EXPECTED_REPOSITORY}.git"|\
    "ssh://git@github.com/${EXPECTED_REPOSITORY}"|\
    "ssh://git@github.com/${EXPECTED_REPOSITORY}.git") ;;
    *) fail "origin points to '$origin_url', expected GitHub repository '$EXPECTED_REPOSITORY'" ;;
esac

branch=$(git branch --show-current)
[[ "$branch" == "$EXPECTED_BRANCH" ]] || \
    fail "release source must be '$EXPECTED_BRANCH' (current: '${branch:-detached HEAD}')"

[[ -z "$(git status --porcelain --untracked-files=all)" ]] || \
    fail "working tree is not clean"

manifest_version=$(python3 -c \
    'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["version"])' \
    "$MANIFEST")
[[ "$version_tag" == "v$manifest_version" ]] || \
    fail "tag '$version_tag' does not match manifest version '$manifest_version'"

if git show-ref --verify --quiet "refs/tags/$version_tag"; then
    fail "tag '$version_tag' already exists locally"
fi

printf '%s\n' "Fetching the release branch and tags from origin..."
git fetch --quiet origin "$EXPECTED_BRANCH" --tags

local_head=$(git rev-parse HEAD)
remote_head=$(git rev-parse "origin/$EXPECTED_BRANCH")
[[ "$local_head" == "$remote_head" ]] || \
    fail "local HEAD ($local_head) differs from origin/$EXPECTED_BRANCH ($remote_head)"

if git show-ref --verify --quiet "refs/tags/$version_tag"; then
    fail "tag '$version_tag' already exists on origin"
fi

command -v uv >/dev/null || fail "uv is required"
command -v gh >/dev/null || fail "GitHub CLI (gh) is required"

printf '%s\n' "Checking locked dependencies and release metadata..."
uv lock --check
uv sync --frozen --all-groups
uv run python tools/check_release_contract.py

printf '%s\n' "Running release quality gates..."
uv run ruff check custom_components/jackery tests tools
uv run mypy custom_components/jackery
uv run python tools/check_translations.py
uv run pytest tests/ -q --tb=short
uv run python -m compileall -q custom_components/jackery
bash -n release.sh

printf '%s\n' "Checking the Validate workflow for $local_head..."
successful_run=$(gh run list \
    --repo "$EXPECTED_REPOSITORY" \
    --branch "$EXPECTED_BRANCH" \
    --commit "$local_head" \
    --workflow validate.yml \
    --limit 20 \
    --json conclusion,headSha,status \
    --jq ".[] | select(.headSha == \"$local_head\" and .status == \"completed\" and .conclusion == \"success\") | .headSha" \
    | head -n 1)
[[ "$successful_run" == "$local_head" ]] || \
    fail "no successful Validate workflow run exists for HEAD $local_head"

cat <<EOF
Release preflight passed for $version_tag at $local_head.

This script intentionally did not create or push anything. After final review,
the maintainer may create the immutable release objects manually:

  git tag -a $version_tag -m "Release $version_tag"
  git push origin $version_tag
  gh release create $version_tag --repo $EXPECTED_REPOSITORY --title $version_tag --generate-notes
EOF
