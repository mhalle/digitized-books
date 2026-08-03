#!/bin/sh
#
# Cut a release tag, with the ordering enforced instead of remembered.
#
# The version comes from git tags (hatch-vcs). That is a good single
# source of truth, but only if two things hold at the moment of the
# build: the tree is clean, and HEAD is exactly the tag. Get either
# wrong and you get a plausible-looking version that is not the release
# — `0.1.1.dev0+g24afa015.d20260803` rather than `0.1.0`.
#
# This script refuses rather than producing that.
#
# Usage:
#   sh scripts/release.sh 0.2.0        # check, tag, print next steps
#   sh scripts/release.sh 0.2.0 --push # ...and push commits + tag
#
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VERSION="${1:?usage: sh scripts/release.sh X.Y.Z [--push]}"
PUSH="${2:-}"
TAG="v${VERSION}"

die() { echo "release: $*" >&2; exit 1; }

echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.]+)?$' \
    || die "'$VERSION' is not X.Y.Z (pass it without the leading 'v')"

# 1. Clean tree. A dirty tree makes hatch-vcs stamp a .dYYYYMMDD suffix,
#    so the artifact would not carry the release version.
[ -z "$(git status --porcelain --untracked-files=no)" ] \
    || die "working tree has uncommitted changes. Commit or stash first:
$(git status --short --untracked-files=no | sed 's/^/    /')"

# 2. Tag must not already exist, locally or upstream.
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null \
    && die "$TAG already exists locally. Delete it or pick another version."
if git remote get-url origin >/dev/null 2>&1; then
    git ls-remote --exit-code --tags origin "$TAG" >/dev/null 2>&1 \
        && die "$TAG already exists on origin. Releases are immutable; bump."
fi

# 3. The checks the release must not skip.
echo "running tests"
uv run --quiet pytest -q
echo "linting"
uv run --quiet ruff check src/ tests/
echo "type-checking"
uv run --quiet mypy src/

# 4. CHANGELOG should mention this version — a release with no note is a
#    release nobody can read later.
if [ -f CHANGELOG.md ] && ! grep -q "\[$VERSION\]" CHANGELOG.md; then
    die "CHANGELOG.md has no '[$VERSION]' section. Add one first."
fi

# 5. A stale _version.py in the source tree would be picked up at runtime
#    ahead of anything else. Remove it so nothing reports a version from a
#    tree state that no longer exists.
rm -f src/iiif_utils/_version.py

git tag -a "$TAG" -m "$(basename "$ROOT") $VERSION

See CHANGELOG.md for the notes."
echo "tagged $TAG at $(git rev-parse --short HEAD)"

# 6. Verify the invariant the build depends on: HEAD is exactly the tag.
DESCRIBED="$(git describe --tags --dirty)"
[ "$DESCRIBED" = "$TAG" ] \
    || die "git describe says '$DESCRIBED', expected '$TAG'. Do not build
    from this state — the artifact would carry the wrong version."
echo "verified: git describe = $TAG"

if [ "$PUSH" = "--push" ]; then
    git remote get-url origin >/dev/null 2>&1 \
        || die "no 'origin' remote; add one or push manually."
    git push origin HEAD
    git push origin "$TAG"
    echo "pushed. CI builds the bundle from the tag."
else
    cat <<EOF

Next:
  git push origin HEAD && git push origin $TAG

CI builds the release bundle from a clean checkout at the tag, which is
the only place the version is guaranteed correct. Do not ship a locally
built artifact — local builds are dev builds by design.
EOF
fi
