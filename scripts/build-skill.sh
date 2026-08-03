#!/bin/sh
#
# Build the installable .skill bundle.
#
# Used by BOTH the release workflow and local builds, so the artifact a
# user installs is identical to the one you can test here. Keeping one
# exclusion list is the point: a second, hand-maintained copy is how a
# bundle ends up shipping a stale worktree and a local settings file.
#
# Usage:
#   sh scripts/build-skill.sh [output-dir]     # default: dist/
#
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILL_NAME="$(sed -n 's/^name:[[:space:]]*//p' "$ROOT/SKILL.md" | head -1)"
OUT_DIR="${1:-$ROOT/dist}"
STAGE="$(mktemp -d)"
trap 'chmod -R u+w "$STAGE" 2>/dev/null || true; rm -rf "$STAGE"' EXIT

[ -n "$SKILL_NAME" ] || { echo "no name: in SKILL.md" >&2; exit 1; }

echo "staging $SKILL_NAME"
mkdir -p "$STAGE/$SKILL_NAME" "$OUT_DIR"

# What must NOT ship:
#   .claude       local agent settings + worktrees (absolute paths, and
#                 a worktree is a whole second copy of the repo)
#   .git/.github  version control and CI plumbing
#   .venv, *cache build/inspection state, regenerable
#   *.sqlite      indexes; these are the user's data, sometimes large
#   .iiif-cache   HTTP cache, hundreds of MB
#   dist          previously built bundles
rsync -a \
    --exclude='.claude' \
    --exclude='.git' \
    --exclude='.github' \
    --exclude='.venv' \
    --exclude='.pytest_cache' \
    --exclude='.mypy_cache' \
    --exclude='.ruff_cache' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.DS_Store' \
    --exclude='*.sqlite' \
    --exclude='.iiif-cache' \
    --exclude='dist' \
    "$ROOT/" "$STAGE/$SKILL_NAME/"

# The wheel is what lets the bundle run read-only, with no git and no
# build backend. Build a fresh one; never carry a stale one across.
echo "building wheel"
rm -f "$STAGE/$SKILL_NAME"/wheels/*.whl
uv build --wheel --project "$ROOT" -o "$STAGE/$SKILL_NAME/wheels" >/dev/null

# hatch-vcs writes _version.py into the SOURCE tree as a build
# side-effect. It is gitignored, so it survives — and because runtime
# prefers it, a stale copy reports a version that was true for a tree
# state that no longer exists. The wheel already carries its own, so
# delete the source-tree one rather than leaving a liar behind.
rm -f "$ROOT/src/iiif_utils/_version.py" \
      "$STAGE/$SKILL_NAME/src/iiif_utils/_version.py"

# Validate under the real bundle directory name — the Agent Skills spec
# requires it to equal SKILL.md's `name`, and that can only be checked
# once the directory is named correctly.
echo "validating"
uvx --from skills-ref agentskills validate "$STAGE/$SKILL_NAME"

# Exercise it the way a user will: read-only, no git, no checkout.
echo "smoke-testing read-only"
chmod -R a-w "$STAGE/$SKILL_NAME"
"$STAGE/$SKILL_NAME/scripts/iiif-utils" --version
chmod -R u+w "$STAGE/$SKILL_NAME"

# Refuse to ship a bundle carrying local agent state.
if [ -e "$STAGE/$SKILL_NAME/.claude" ]; then
    echo "error: .claude leaked into the bundle" >&2
    exit 1
fi

BUNDLE="$OUT_DIR/$SKILL_NAME.skill"
rm -f "$BUNDLE"
( cd "$STAGE" && zip -qr "$BUNDLE" "$SKILL_NAME" )
echo "built $BUNDLE ($(du -h "$BUNDLE" | cut -f1))"
