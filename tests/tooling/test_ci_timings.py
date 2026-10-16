"""Timing evidence separates wall time, occupied runner time and test time."""
from pathlib import Path

import pytest

from scripts.summarize_ci_timings import junit_summary, summarize


def job(name="suite", **overrides):
    return {"name": name, "head_sha": "a" * 40, "run_attempt": 1,
            "started_at": "2026-10-16T03:00:00Z", "completed_at": "2026-10-16T03:02:00Z",
            "conclusion": "success", "steps": [{"name": "Install", "conclusion": "success",
            "started_at": "2026-10-16T03:00:00Z", "completed_at": "2026-10-16T03:00:10Z"}],
            **overrides}


def test_parallel_jobs_do_not_sum_to_wall_time_or_hide_failure():
    report = summarize([job(), job("cancelled suite", conclusion="cancelled")])
    assert report["elapsed_seconds"] == 120
    assert report["runner_seconds"] == 240
    assert report["jobs"][1]["conclusion"] == "cancelled"
    assert report["jobs"][0]["steps"][0]["seconds"] == 10


@pytest.mark.parametrize("jobs", [[], [job(completed_at=None)],
                                  [job(), job(head_sha="b" * 40)],
                                  [job(), job(run_attempt=2)],
                                  [job(run_id=1), job(run_id=2)]])
def test_incomplete_or_incomparable_evidence_is_rejected(jobs):
    with pytest.raises(ValueError):
        summarize(jobs)


def test_junit_aggregates_do_not_copy_private_diagnostics(tmp_path: Path):
    path = tmp_path / "results.xml"
    path.write_text('<testsuites><testsuite><testcase name="private" time="2"><failure>secret</failure></testcase>'
                    '<testcase time="0"><skipped/></testcase><testcase time="4"><system-out>secret</system-out>'
                    '</testcase></testsuite></testsuites>')
    report = junit_summary(path)
    assert report == {"cases": 3, "failures": 1, "skipped": 1, "case_seconds": 6,
                      "max_case_seconds": 4, "median_case_seconds": 2}
    assert "secret" not in str(report) and "private" not in str(report)


def test_junit_median_averages_the_middle_pair(tmp_path: Path):
    path = tmp_path / "results.xml"
    path.write_text('<testsuite><testcase time="2"/><testcase time="4"/></testsuite>')
    assert junit_summary(path)["median_case_seconds"] == 3
