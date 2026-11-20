#!/usr/bin/env python
"""Run full Naver blog collection from config (resume-safe)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.pipeline import CollectionPipeline


def main() -> int:
    pipe = CollectionPipeline(ROOT)
    pipe.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
