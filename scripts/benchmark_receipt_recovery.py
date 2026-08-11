"""Compare issue-72 receipt recovery with its pre-optimization implementation."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
import statistics
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import types
from typing import Any
from unittest.mock import Mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tabula_rasa.receipt_recovery import recover_receipts_from_synology
from tests.test_receipt_recovery import (
    _backup_with_receipts,
    _drive_file,
    _reference,
)


BASELINE_REF = "48cf0d3"


def _baseline_recovery(ref: str) -> Callable[..., dict[str, Any]]:
    result = subprocess.run(
        ["git", "show", f"{ref}:tabula_rasa/receipt_recovery.py"],
        check=True,
        capture_output=True,
        text=True,
    )
    module = types.ModuleType("receipt_recovery_baseline")
    exec(
        compile(result.stdout, "receipt_recovery_baseline.py", "exec"),
        module.__dict__,
    )
    return module.recover_receipts_from_synology


def _measure(
    recovery: Callable[..., dict[str, Any]],
    *,
    receipt_count: int,
    latency_seconds: float,
) -> tuple[int, int, float]:
    contents = [
        f"receipt-{index}".encode() for index in range(1, receipt_count + 1)
    ]
    references = [
        _reference(index, content)
        for index, content in enumerate(contents, start=1)
    ]
    backup, storage, _ = _backup_with_receipts(references)
    worksheet = storage._workbook.sheets["Transactions"]
    original_read = worksheet.get_all_values
    original_update = worksheet.update
    read_count = 0
    write_count = 0

    def delayed_read() -> list[list[str]]:
        nonlocal read_count
        read_count += 1
        time.sleep(latency_seconds)
        return original_read()

    def delayed_update(
        values: list[list[str]],
        range_name: str,
        **kwargs: object,
    ) -> None:
        nonlocal write_count
        write_count += 1
        time.sleep(latency_seconds)
        original_update(values, range_name=range_name, **kwargs)

    def delayed_batch_update(
        data: list[dict[str, object]],
        **kwargs: object,
    ) -> None:
        nonlocal write_count
        write_count += 1
        time.sleep(latency_seconds)
        for item in data:
            original_update(
                item["values"],
                range_name=str(item["range"]),
                **kwargs,
            )

    worksheet.get_all_values = Mock(side_effect=delayed_read)
    worksheet.update = Mock(side_effect=delayed_update)
    worksheet.batch_update = Mock(side_effect=delayed_batch_update)
    references_by_name = {
        str(reference["name"]): (index, reference)
        for index, reference in enumerate(references, start=1)
    }

    def restore_receipt(**kwargs: object) -> tuple[dict[str, object], bool]:
        index, reference = references_by_name[str(kwargs["stored_filename"])]
        return _drive_file(
            reference,
            file_id=f"newreceipt{index:03d}",
        ), False

    drive = Mock()
    drive.restore_receipt.side_effect = restore_receipt
    with TemporaryDirectory() as directory:
        root = Path(directory)
        for reference, content in zip(references, contents):
            (root / str(reference["name"])).write_bytes(content)
        started = time.perf_counter()
        report = recovery(
            backup,
            root,
            profile_key="north",
            folder_id="folder123456",
            storage=storage,
            drive=drive,
        )
        elapsed = time.perf_counter() - started
    if report["restored"] != receipt_count or report["errors"]:
        raise RuntimeError(f"Benchmark recovery failed: {report}")
    return read_count, write_count, elapsed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-ref", default=BASELINE_REF)
    parser.add_argument("--receipts", type=int, default=100)
    parser.add_argument("--latency-ms", type=float, default=5.0)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    baseline = _baseline_recovery(args.baseline_ref)
    latency_seconds = args.latency_ms / 1000

    print("implementation,reads,writes,median_seconds")
    for label, recovery in (
        (f"baseline-{args.baseline_ref}", baseline),
        ("optimized", recover_receipts_from_synology),
    ):
        measurements = [
            _measure(
                recovery,
                receipt_count=args.receipts,
                latency_seconds=latency_seconds,
            )
            for _run in range(args.runs)
        ]
        reads = {measurement[0] for measurement in measurements}
        writes = {measurement[1] for measurement in measurements}
        if len(reads) != 1 or len(writes) != 1:
            raise RuntimeError("Benchmark call counts changed between runs")
        print(
            f"{label},{reads.pop()},{writes.pop()},"
            f"{statistics.median(item[2] for item in measurements):.4f}"
        )


if __name__ == "__main__":
    main()
