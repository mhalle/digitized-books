#!/bin/sh
# Rebuild the wheel this skill ships.
#
# The skill runs iiif-utils from a prebuilt wheel rather than from
# source, because an editable/project install needs a WRITABLE source
# tree: uv puts `.venv` there, and hatch-vcs's build hook writes
# `_version.py` back into it. Skill directories are often mounted
# read-only, so a wheel — which needs no build backend and no git — is
# the only form that works everywhere.
#
# Run from a git checkout (hatch-vcs derives the version from git tags).
set -e
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_DIR="${1:-$(cd "$SKILL_DIR/../.." && pwd)}"

if [ ! -f "$REPO_DIR/pyproject.toml" ]; then
    echo "error: no pyproject.toml in $REPO_DIR" >&2
    echo "usage: sh $0 [path-to-iiif-repo]" >&2
    exit 1
fi

echo "building wheel from $REPO_DIR"
rm -f "$SKILL_DIR"/wheels/iiif_utils-*.whl
uv build --wheel --project "$REPO_DIR" -o "$SKILL_DIR/wheels"
ls -1 "$SKILL_DIR"/wheels/*.whl
