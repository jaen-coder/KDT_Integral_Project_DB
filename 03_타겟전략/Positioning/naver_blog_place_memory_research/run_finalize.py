#!/usr/bin/env python
"""Export tables and write QA + collection reports after collection."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.qa import run_qa
from src.report import write_collection_report


def main() -> int:
    print("Exporting + writing collection_report.md ...")
    write_collection_report(ROOT)
    print("Running QA checks -> qa_report.md ...")
    run_qa(ROOT)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
