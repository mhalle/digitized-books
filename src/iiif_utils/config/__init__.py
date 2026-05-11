"""Config loader.

Precedence (lowest → highest):
  1. Packaged defaults at src/iiif_utils/config/config.toml
  2. Project-local override at ./iiif-utils.toml
  3. Explicit path passed via --config
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef,import-not-found,unused-ignore]

PACKAGED_DEFAULTS = Path(__file__).parent / "config.toml"
PROJECT_LOCAL_NAME = "iiif-utils.toml"


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(explicit: Path | str | None = None) -> dict[str, Any]:
    """Return the merged config as a plain dict."""
    config: dict[str, Any] = tomllib.loads(PACKAGED_DEFAULTS.read_text())
    project_local = Path.cwd() / PROJECT_LOCAL_NAME
    if project_local.exists():
        config = _deep_merge(config, tomllib.loads(project_local.read_text()))
    if explicit is not None:
        config = _deep_merge(config, tomllib.loads(Path(explicit).read_text()))
    return config
