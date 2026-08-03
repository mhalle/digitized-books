# wheels/

Holds the built `iiif_utils-*.whl` that `SKILL.md` runs. Wheels are
**not** committed: the version string embeds a git hash and build date
(`0.0.1.dev40+g58290f489.d20260803`), so every rebuild would churn git
history with a new 116K binary.

Populate it before packaging or first use:

```sh
sh ../scripts/build-wheel.sh /path/to/iiif
```

If this directory is empty, the skill's documented command has nothing
to install. Either build the wheel, or — in a writable checkout — use
the source form instead:

```sh
uv run --project /path/to/iiif iiif-utils <command>
```

The launcher (`../scripts/iiif-utils`) picks the newest wheel here, so a
stale build left behind never shadows a fresh one.
