#!/usr/bin/env python
"""Unattended: collect (resume-safe) then export/QA/report. Never waits for input."""
from __future__ import annotations

import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
LOG = ROOT / "logs" / "unattended_run.log"
LOG.parent.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> int:
    log("START unattended pipeline")
    try:
        from src.pipeline import CollectionPipeline

        pipe = CollectionPipeline(ROOT)
        log(
            f"run_id={pipe.state['run_id']} jobs={len(pipe.iter_jobs())} "
            f"kw={len(pipe.keywords)} months={len(pipe.months)}"
        )
        pipe.run()
        log("Collection finished")
    except Exception:
        log("Collection ERROR:\n" + traceback.format_exc())
        # still try finalize with whatever was saved
    try:
        from src.report import write_collection_report
        from src.qa import run_qa

        log("Export + collection_report")
        write_collection_report(ROOT)
        log("QA report")
        run_qa(ROOT)
        log("DONE all outputs written")
        return 0
    except Exception:
        log("Finalize ERROR:\n" + traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
