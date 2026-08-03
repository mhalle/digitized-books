# Releasing, and why the version drifts

The version comes from git tags via `hatch-vcs`. That is a good single
source of truth, and it desyncs in practice for a reason worth stating
plainly, because the failure is silent.

## Nothing reads git at runtime

Computing a version means running `git describe`. Doing that on every
import would be slow, and would fail wherever there is no git — which
is exactly where installed copies live. So the version is **resolved at
build or install time and cached**. There are two caches, and both can
outlive the state they described:

| Cache | Written when | Why it goes stale |
|---|---|---|
| `src/iiif_utils/_version.py` | every build (hatch-vcs hook) | gitignored, so it survives forever; runtime prefers it |
| installed package metadata | `uv sync` / `pip install` | snapshotted at install; editable installs do not refresh on commit |

Observed here: `git describe` said `v0.1.0-2-g4e12ca1` while
`_version.py` claimed `0.1.1.dev0+g24afa015.d20260803`, written during
an earlier **dirty** build. Deleting it fell through to installed
metadata, which claimed `0.0.1.dev45+gafae3efbc` — stale in a different
way. Only `uv sync --reinstall-package iiif-utils` produced
`0.1.1.dev2+g4e12ca12`, matching git.

**A checkout's version is therefore "as of the last build or sync",
not "as of HEAD".** That is inherent, not a bug to fix.

## The rule that actually matters

Don't chase exact versions in a working tree. Guarantee them where they
are consumed:

> **Release artifacts are built only by CI, from a clean checkout, with
> HEAD exactly at the tag. Never ship a locally built artifact.**

Under that rule `git describe` returns the bare tag, so hatch-vcs emits
`0.1.0` — no `.devN`, no `+g<hash>`, no `.dYYYYMMDD` — and bakes it into
the wheel. The wheel is then self-describing forever, with no git and no
network. That is why the bundle ships a wheel: not a workaround for
read-only directories, but the mechanism that makes the version
trustworthy.

## Cutting a release

```bash
sh scripts/release.sh 0.2.0          # check + tag
sh scripts/release.sh 0.2.0 --push   # ...and push
```

The script refuses rather than producing a wrong version. It checks, in
order: the version string is `X.Y.Z`; the tree has no uncommitted
tracked changes (a dirty tree stamps `.dYYYYMMDD`); the tag does not
already exist locally or on origin (releases are immutable); tests, lint
and types pass; `CHANGELOG.md` has a section for the version; and, after
tagging, that `git describe` equals the tag exactly. It also deletes a
stale `src/iiif_utils/_version.py`.

CI re-checks the last of those independently — if HEAD does not describe
as the pushed tag, the release fails rather than publishing a
mislabelled bundle.

## If a checkout reports a surprising version

It is cosmetic, and it means a cache is behind:

```bash
rm -f src/iiif_utils/_version.py
uv sync --extra dev --reinstall-package iiif-utils
```

Keep `--extra dev`: without it the sync drops pytest/ruff/mypy from the
environment, and the next `uv run pytest` fails with a confusing
"Failed to spawn".

## What is deliberately not solved

- **Checkout versions are approximate.** Making them exact means either
  a git call per import or a hook on every commit. Both cost more than
  the problem.
- **`.dYYYYMMDD` on a dirty tree is correct information**, not noise: the
  build genuinely does not correspond to any commit.
- **The workflow also writes `_version.py` and patches
  `fallback-version`** from the tag. That is redundant for the wheel,
  which carries its own, and exists only for someone running
  `uv run --project` against an unpacked bundle, where there is no git
  for hatch-vcs to read.
