#!/usr/bin/env bash
# release.sh - tag and cut a GitHub release so HACS can install the integration.
#
# HACS installs by GitHub release/tag; without one it falls back to the commit
# SHA as the "version" and the install fails. This script tags the version in
# manifest.json and publishes a release with auto-generated notes.
#
# Usage:
#   scripts/release.sh           # release the version already in manifest.json
#   scripts/release.sh 0.1.1     # bump manifest.json to 0.1.1, commit, then release
#
# Requires: git, gh (authenticated: gh auth login). Run from anywhere in the repo.
# Note: uses BSD sed in-place syntax (macOS). On Linux change `sed -i ''` to `sed -i`.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"
MANIFEST="custom_components/value_crossing/manifest.json"

die() { echo "error: $*" >&2; exit 1; }
read_version() {
  grep -o '"version"[[:space:]]*:[[:space:]]*"[^"]*"' "$MANIFEST" |
    head -1 | sed -E 's/.*"([^"]*)"$/\1/'
}

command -v gh >/dev/null || die "gh (GitHub CLI) not found"
gh auth status >/dev/null 2>&1 || die "gh not authenticated (run: gh auth login)"
[ -f "$MANIFEST" ] || die "manifest not found at $MANIFEST"

current="$(read_version)"
[ -n "$current" ] || die "could not read version from $MANIFEST"

version="${1:-$current}"
echo "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || die "version '$version' is not semver X.Y.Z"
tag="v$version"

git rev-parse -q --verify "refs/tags/$tag" >/dev/null && die "tag $tag already exists locally"
git ls-remote --exit-code --tags origin "$tag" >/dev/null 2>&1 && die "tag $tag already exists on origin"

branch="$(git rev-parse --abbrev-ref HEAD)"
[ "$branch" = "main" ] || echo "warning: on branch '$branch', not 'main'"

# Bump manifest.json if a new version was requested, and commit it.
if [ "$version" != "$current" ]; then
  git diff --quiet || die "working tree has uncommitted changes; commit or stash first"
  sed -i '' -E "s/(\"version\"[[:space:]]*:[[:space:]]*\")[^\"]*\"/\1$version\"/" "$MANIFEST"
  git add "$MANIFEST"
  git commit -m "chore: release $tag"
  echo "bumped manifest.json $current -> $version"
fi

[ "$(read_version)" = "$version" ] || die "manifest version != $version after bump"

echo "releasing $tag ..."
git push origin "$branch"
git tag "$tag"
git push origin "$tag"
gh release create "$tag" --title "$tag" --generate-notes

url="$(gh release view "$tag" --json url -q .url)"
echo "done: $url"
echo "now in HACS: Value Crossing -> 3-dot menu -> Redownload -> $tag"
