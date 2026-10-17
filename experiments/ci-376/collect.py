"""Collect sanitized attempt-specific metadata and aggregate JUnit for #376."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile

REPO = 'Roklion/Project_Tabula_Rasa'
SOURCE = '84f427e1ec0f9bb38baf63b7b4c6a6b0bb98f6db'


def gh(*args: str) -> str:
    return subprocess.check_output(['gh', *args], text=True, encoding='utf-8')


def api(path: str) -> dict:
    return json.loads(gh('api', f'repos/{REPO}/{path}'))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_id', type=int)
    parser.add_argument('--sample', type=int, required=True)
    args = parser.parse_args()
    run = api(f'actions/runs/{args.run_id}')
    assert run['status'] == 'completed', 'Collect only completed attempts'
    assert run['head_branch'] == 'codex/issue-376-ci-evidence'
    assert run['event'] == 'push'
    attempt = run['run_attempt']
    jobs = []
    page = 1
    while True:
        payload = api(f'actions/runs/{args.run_id}/attempts/{attempt}/jobs?per_page=100&page={page}')
        jobs.extend(payload['jobs'])
        if len(jobs) >= payload['total_count']:
            break
        page += 1
    assert len(jobs) == 10, 'Expected nine components and experiment aggregate'
    assert all(j['head_sha'] == run['head_sha'] for j in jobs)
    spec = importlib.util.spec_from_file_location('timings', 'scripts/summarize_ci_timings.py')
    timings = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(timings)
    safe_keys = ['id', 'run_id', 'run_attempt', 'head_sha', 'name', 'status', 'conclusion',
                 'started_at', 'completed_at', 'labels', 'html_url']
    safe_steps = ['number', 'name', 'status', 'conclusion', 'started_at', 'completed_at']
    safe_jobs = [{**{k: j[k] for k in safe_keys if k in j},
                  'steps': [{k: s[k] for k in safe_steps if k in s} for s in j['steps']]} for j in jobs]
    report = {'sample': args.sample, 'source_sha': SOURCE, 'workflow_head_sha': run['head_sha'],
              'run_id': args.run_id, 'attempt': attempt, 'event': run['event'],
              'url': run['html_url'], 'created_at': run['created_at'], 'conclusion': run['conclusion'],
              'layouts': {}, 'runtime_observations': [], 'junit': [], 'overlay_proof': None}
    for layout, count in [('Baseline', 3), ('Partitioned', 6)]:
        selected = [j for j in jobs if j['name'].startswith(layout + ' | ')]
        assert len(selected) == count
        summary = timings.summarize(selected)
        summary['runner_seconds_by_os'] = {}
        for job in selected:
            os_name = next(label for label in job['labels'] if label.endswith('-latest'))
            duration = timings.seconds(job['started_at'], job['completed_at'])
            summary['runner_seconds_by_os'][os_name] = summary['runner_seconds_by_os'].get(os_name, 0) + duration
        summary['start_delay_seconds'] = {
            job['name']: timings.seconds(run['created_at'], job['started_at']) for job in selected}
        report['layouts'][layout.lower()] = summary
    for job in jobs:
        if ' | ' not in job['name']:
            continue
        log = gh('run', 'view', str(args.run_id), '--repo', REPO, '--job', str(job['id']), '--log')
        verified = f'source={SOURCE} sample={args.sample} workflow={run["head_sha"]}' in log
        # A failed checkout can legitimately prevent provenance; preserve that fact.
        assert verified or job['conclusion'] != 'success', 'Successful component lacks fixed-source proof'
        observations = {'job': job['name'], 'fixed_source_verified': verified,
                        'cache_hit_lines': [], 'runtime_lines': [], 'configured_runtime_lines': [],
                        'pytest_duration_seconds': {}}
        phase_seconds: dict[str, float] = {}
        for line in log.splitlines():
            # Strip CLI job/step prefix and log timestamp; keep only known public metadata.
            content = re.sub(r'^\d{4}-\d{2}-\d{2}T[0-9:.]+Z\s+', '', line.split('\t')[-1]).strip()
            if re.fullmatch(r'(Python 3\.\d+\.\d+|v24\.\d+\.\d+)', content):
                observations['runtime_lines'].append(content)
            if re.fullmatch(r'(Successfully set up CPython \(3\.12\.\d+\)|node: v24\.\d+\.\d+|npm: [0-9.]+)', content):
                observations['configured_runtime_lines'].append(content)
            if re.fullmatch(r'(Image: [\w. -]+|Version: [\w. -]+)', content):
                observations['runtime_lines'].append(content)
            if re.fullmatch(r'(Cache restored successfully|Cache hit for: [A-Za-z0-9_. -]+|Cache not found for input keys: [A-Za-z0-9_., -]+)', content):
                observations['cache_hit_lines'].append(content)
            match = re.search(r'\b(\d+\.\d+)s (setup|call|teardown)\s', content)
            if match:
                phase_seconds[match[2]] = phase_seconds.get(match[2], 0) + float(match[1])
        observations['pytest_duration_seconds'] = phase_seconds
        observations['pytest_duration_note'] = 'Top-20 duration entries only; not total fixture time'
        report['runtime_observations'].append(observations)
    with tempfile.TemporaryDirectory(prefix='ci-376-artifacts-') as directory:
        gh('run', 'download', str(args.run_id), '--repo', REPO, '--dir', directory)
        root = Path(directory)
        for xml in sorted(root.rglob('*.xml')):
            role = xml.relative_to(root).as_posix()
            report['junit'].append({'artifact_report': role, **timings.junit_summary(xml)})
        proofs = list(root.rglob('baseline-overlay-proof.json'))
        if proofs:
            assert len(proofs) == 1
            proof = json.loads(proofs[0].read_text())
            assert proof['source_sha'] == SOURCE
            for key, path in [('contract_body_sha256', 'web/contracts/visual-review.spec.ts'),
                              ('ui_body_sha256', 'web/e2e/visual-review.spec.ts')]:
                source_text = subprocess.check_output(['git', 'show', f'{SOURCE}:{path}']).decode('utf-8')
                body = "test('" + source_text.split("test('", 1)[1]
                assert proof[key] == hashlib.sha256(body.encode('utf-8')).hexdigest()
            report['overlay_proof'] = proof
    output = Path('experiments/ci-376/results')
    output.mkdir(exist_ok=True)
    (output / f'sample-{args.sample}-jobs.json').write_text(json.dumps({'jobs': safe_jobs}, indent=2) + '\n', encoding='utf-8')
    (output / f'sample-{args.sample}-summary.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'sample': args.sample, 'conclusion': report['conclusion'],
                      'layouts': {name: {key: value[key] for key in ['elapsed_seconds', 'runner_seconds']}
                                  for name, value in report['layouts'].items()}, 'junit_reports': len(report['junit'])}, indent=2))


if __name__ == '__main__':
    main()
