"""Render the three controlled samples without making statistical claims."""
from pathlib import Path
import json
from statistics import median

root = Path('experiments/ci-376/results')
samples = [json.loads((root / f'sample-{number}-summary.json').read_text()) for number in range(1, 4)]
assert len({sample['source_sha'] for sample in samples}) == 1
assert all(sample['overlay_proof'] for sample in samples)
lines = ['# Controlled CI evidence for issue #376', '',
         f"Fixed source: `{samples[0]['source_sha']}`. Three paired hosted attempts; reconstructed baseline and partitioned layout share current source, dependencies and assertions.", '',
         '| Pair | Baseline elapsed s | Partitioned elapsed s | Baseline runner s | Partitioned runner s | Outcome |',
         '| --- | ---: | ---: | ---: | ---: | --- |']
for sample in samples:
    old, new = sample['layouts']['baseline'], sample['layouts']['partitioned']
    lines.append(f"| [{sample['sample']}]({sample['url']}) | {old['elapsed_seconds']:.0f} | {new['elapsed_seconds']:.0f} | {old['runner_seconds']:.0f} | {new['runner_seconds']:.0f} | {sample['conclusion']} |")
lines += ['', 'Occupied runner seconds are unweighted job intervals, not billed usage. Queue/start delays, OS-specific runner seconds, step costs, runtime/cache observations, and individual JUnit report counts are preserved in the adjacent JSON files. Experiment aggregate overhead is excluded from both layouts.', '']
for key, label in [('elapsed_seconds', 'elapsed seconds'), ('runner_seconds', 'occupied runner seconds')]:
    old = [sample['layouts']['baseline'][key] for sample in samples]
    new = [sample['layouts']['partitioned'][key] for sample in samples]
    deltas = [(after / before - 1) * 100 for before, after in zip(old, new)]
    lines.append(f'Median {label}: baseline {median(old):.0f} (range {min(old):.0f}–{max(old):.0f}), partitioned {median(new):.0f} (range {min(new):.0f}–{max(new):.0f}). Paired changes: ' + ', '.join(f'{delta:+.1f}%' for delta in deltas) + '.')
lines += ['', '## Coverage and diagnostic audit', '',
          'Complete this section only after checking every JUnit report, source proof, failure/cancellation, native inventory and runner/cache observation. Do not infer equivalent coverage merely from a green aggregate.', '',
          '## Interpretation and limits', '',
          'The deliberate treatment is execution ownership: five unchanged HTTP/Git contracts execute twenty times in the reconstructed baseline and five times in the partitioned layout; all 140 UI/browser/device cases and the same native inventory remain. Current security, onboarding and NAS recovery coverage is included in both. Baseline reconstruction uses the prior 30-minute combined budget; production bounded partition budgets are unchanged.', '',
          'Three pairs describe observed outcomes, not long-term reliability or causal isolation from runner/cache variability. Keep reported failures, cancellations and reruns. No billed-cost claim, production coverage reduction or broader visual scheduling follows from this experiment.', '']
(root / 'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
print(root / 'REPORT.md')
