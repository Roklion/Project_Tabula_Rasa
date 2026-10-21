"""The standalone benchmark must use the supported synthetic recovery fixtures."""

from tempfile import TemporaryDirectory

from scripts import benchmark_receipt_recovery as benchmark


def test_current_recovery_benchmark_runs_with_synthetic_receipts(tmp_path, monkeypatch):
    monkeypatch.setattr(
        benchmark, 'TemporaryDirectory', lambda: TemporaryDirectory(dir=tmp_path),
    )
    reads, writes, elapsed = benchmark._measure(
        benchmark.recover_receipts_from_synology,
        receipt_count=2,
        latency_seconds=0,
    )
    assert reads > 0
    assert writes > 0
    assert elapsed >= 0
