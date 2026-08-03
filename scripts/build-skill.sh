#!/bin/sh
#
# Build the installable .skill bundles.
#
# The bundle is assembled from an EXPLICIT LIST of what belongs in it,
# never by copying the repo and excluding what doesn't. That inversion
# is the point. Every packaging bug this project has had came from the
# subtractive approach — a stale git worktree and a local settings file
# rode along in the first bundle, and a second SKILL.md from skills/
# made the next one refuse to install. With a denylist, anything new in
# the repo ships by default and you find out downstream. With an
# allowlist, a file has to be named here to escape.
#
# It also means the skill is self-contained rather than a copy of the
# development tree: the wheel IS the code, so src/, tests/, uv.lock and
# docs/ have no reason to be there. That is ~400K down to ~140K, and
# removes the question of whether the source or the wheel is the one
# actually running.
#
# Used by both the release workflow and local builds, so the artifact a
# user installs is the one you can test here.
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

BUNDLE="$STAGE/$SKILL_NAME"
mkdir -p "$BUNDLE/scripts" "$BUNDLE/wheels" "$OUT_DIR"

# --- everything that ships, and nothing else ---------------------------
#
#   SKILL.md            the skill itself
#   LICENSE             Apache-2.0 §4(a) requires it accompany the work
#   CHANGELOG.md        what is in this version, for a reader
#   scripts/iiif-utils  the launcher; the only executable a user runs
#   wheels/*.whl        the code (built below)
#
echo "staging $SKILL_NAME"
cp "$ROOT/SKILL.md" "$ROOT/LICENSE" "$ROOT/CHANGELOG.md" "$BUNDLE/"
cp "$ROOT/scripts/iiif-utils" "$BUNDLE/scripts/"
chmod +x "$BUNDLE/scripts/iiif-utils"

# The wheel carries the version hatch-vcs resolved from git, so it is
# self-describing with no git and no build backend. Build it from the
# pristine repo — never from the staged copy — so nothing here can
# dirty the tree and change the version.
echo "building wheel"
uv build --wheel --project "$ROOT" -o "$BUNDLE/wheels" >/dev/null
# uv drops a .gitignore into any -o directory; it is not on the list above.
rm -f "$BUNDLE/wheels/.gitignore"

# hatch-vcs writes _version.py into the SOURCE tree as a side-effect.
# It is gitignored, so it survives, and runtime prefers it — a stale one
# reports a version true for a tree state that no longer exists. The
# wheel has its own copy; delete the repo's.
rm -f "$ROOT/src/iiif_utils/_version.py"

VERSION="$(basename "$BUNDLE"/wheels/iiif_utils-*.whl \
    | sed -E 's/^iiif_utils-(.+)-py3-none-any\.whl$/\1/')"
[ -n "$VERSION" ] || { echo "could not read version from wheel" >&2; exit 1; }
echo "bundling version $VERSION"

# --- guards: backstops, not the mechanism ------------------------------
# The allowlist above is what makes these unreachable in practice. They
# stay because both failures are silent and outbound.
[ ! -e "$BUNDLE/.claude" ] || { echo "error: .claude in bundle" >&2; exit 1; }

N="$(find "$BUNDLE" -name SKILL.md | wc -l | tr -d ' ')"
if [ "$N" != "1" ]; then
    echo "error: bundle has $N SKILL.md files, expected exactly 1" >&2
    find "$BUNDLE" -name SKILL.md | sed "s|$STAGE/|  |" >&2
    exit 1
fi

echo "validating"
uvx --from skills-ref agentskills validate "$BUNDLE"

# Exercise it the way a user will: read-only, no git, no checkout, and
# no source tree to fall back on.
echo "smoke-testing read-only"
chmod -R a-w "$BUNDLE"
"$BUNDLE/scripts/iiif-utils" --version
chmod -R u+w "$BUNDLE"

OUT="$OUT_DIR/$SKILL_NAME.skill"
rm -f "$OUT"
( cd "$STAGE" && zip -qr "$OUT" "$SKILL_NAME" )
echo "built $OUT ($(du -h "$OUT" | cut -f1))"

# --- sibling skills ----------------------------------------------------
# A .skill archive holds exactly one skill, so anything under skills/
# ships as its own archive. These are instruction-only — no package, no
# wheel — so the whole directory is the skill.
for skill_dir in "$ROOT"/skills/*/; do
    [ -f "${skill_dir}SKILL.md" ] || continue
    name="$(basename "$skill_dir")"
    rm -rf "${STAGE:?}/sib"
    mkdir -p "$STAGE/sib/$name"
    rsync -a --exclude='__pycache__' --exclude='*.pyc' \
             --exclude='.DS_Store' "$skill_dir" "$STAGE/sib/$name/"
    uvx --from skills-ref agentskills validate "$STAGE/sib/$name" >/dev/null
    rm -f "$OUT_DIR/$name.skill"
    ( cd "$STAGE/sib" && zip -qr "$OUT_DIR/$name.skill" "$name" )
    echo "built $OUT_DIR/$name.skill ($(du -h "$OUT_DIR/$name.skill" | cut -f1))"
done
