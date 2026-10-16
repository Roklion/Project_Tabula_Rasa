"""Summarize GET /actions/runs/{id}/jobs and optional JUnit without test output.

Input must describe one workflow attempt. Do not combine attempts or cancelled
superseded runs and call the result a speed comparison.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from statistics import median
import xml.etree.ElementTree as ET


def seconds(start: str, end: str) -> float:
    return (datetime.fromisoformat(end.replace("Z", "+00:00")) -
            datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds()


def summarize(jobs: list[dict]) -> dict:
    if not jobs or any(not job.get("completed_at") for job in jobs):
        raise ValueError("Use one completed workflow attempt, including unsuccessful jobs.")
    if len({job["head_sha"] for job in jobs}) != 1 or len({job.get("run_attempt", 1) for job in jobs}) != 1:
        raise ValueError("Do not combine revisions or workflow attempts.")
    if len({job.get("run_id") for job in jobs}) != 1:
        raise ValueError("Do not combine workflow runs.")
    return {
        "head_sha": jobs[0]["head_sha"],
        "attempt": jobs[0].get("run_attempt", 1),
        "elapsed_seconds": seconds(min(job["started_at"] for job in jobs),
                                   max(job["completed_at"] for job in jobs)),
        # Unweighted occupied time, not billing (Windows, rounding and plans differ).
        "runner_seconds": sum(seconds(job["started_at"], job["completed_at"]) for job in jobs),
        "jobs": [{
            "name": job["name"], "conclusion": job["conclusion"],
            "seconds": seconds(job["started_at"], job["completed_at"]),
            "steps": [{"name": step["name"], "conclusion": step["conclusion"],
                       "seconds": seconds(step["started_at"], step["completed_at"])}
                      for step in job["steps"] if step.get("started_at") and step.get("completed_at")],
        } for job in jobs],
    }


def junit_summary(path: Path) -> dict:
    cases = list(ET.parse(path).getroot().iter("testcase"))
    durations = sorted(float(case.get("time", "0")) for case in cases)
    return {"cases": len(cases),
            "failures": sum(case.find("failure") is not None or case.find("error") is not None for case in cases),
            "skipped": sum(case.find("skipped") is not None for case in cases),
            "case_seconds": sum(durations),
            "max_case_seconds": max(durations, default=0),
            "median_case_seconds": median(durations) if durations else 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", required=True, type=Path)
    parser.add_argument("--junit", type=Path, nargs="*", default=[])
    args = parser.parse_args()
    report = summarize(json.loads(args.jobs.read_text(encoding="utf-8-sig"))["jobs"])
    # Only aggregate timing/counts: never copy testcase names, properties,
    # stdout, stderr, failure messages or local paths into retained evidence.
    report["junit"] = [junit_summary(path) for path in args.junit]
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
