"""Tiny progress logger. Honors --verbose."""
from __future__ import annotations

import sys


class Logger:
    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose

    def info(self, msg: str) -> None:
        if self.verbose:
            print(msg, file=sys.stderr, flush=True)

    def warn(self, msg: str) -> None:
        print(f"WARN: {msg}", file=sys.stderr, flush=True)

    def error(self, msg: str) -> None:
        print(f"ERROR: {msg}", file=sys.stderr, flush=True)
