from pathlib import Path
import copy
import yaml

SOURCE = '84f427e1ec0f9bb38baf63b7b4c6a6b0bb98f6db'
SAMPLE = 3
root = Path.cwd()
original = yaml.safe_load((root / '.github/workflows/ci.yml').read_text(encoding='utf-8'))
base = original['jobs']
workflow = {
    'name': 'Controlled CI evidence 376',
    'on': {'push': {'branches': ['codex/issue-376-ci-evidence']}},
    'permissions': {'contents': 'read'},
    'concurrency': {'group': 'ci-evidence-376-${{ github.ref }}', 'cancel-in-progress': False},
    'env': {'EVIDENCE_SOURCE_SHA': SOURCE, 'EVIDENCE_SAMPLE': str(SAMPLE)},
    'jobs': {},
}
provenance = {
    'name': 'Verify fixed source and record runtime',
    'shell': 'bash',
    'run': '''test "$(git rev-parse HEAD)" = "$EVIDENCE_SOURCE_SHA"
python --version 2>/dev/null || true
node --version 2>/dev/null || true
printf 'source=%s sample=%s workflow=%s run=%s attempt=%s\n' "$EVIDENCE_SOURCE_SHA" "$EVIDENCE_SAMPLE" "$GITHUB_SHA" "$GITHUB_RUN_ID" "$GITHUB_RUN_ATTEMPT"
''',
}

def prepare(job, layout):
    job = copy.deepcopy(job)
    job['name'] = layout + ' | ' + job['name']
    steps = []
    for step in job['steps']:
        if step.get('uses', '').startswith('actions/checkout@'):
            step['with'] = {'ref': SOURCE}
            steps.extend([step, copy.deepcopy(provenance)])
            continue
        if step.get('uses', '').startswith('actions/upload-artifact@'):
            step['with']['name'] = layout.lower() + '-' + step['with']['name']
        if 'run' in step:
            step['run'] = step['run'].replace('$GITHUB_SHA', '$EVIDENCE_SOURCE_SHA')
        steps.append(step)
    job['steps'] = steps
    return job

for key in ['python-suite', 'windows-tooling', 'frontend-contract', 'browser', 'native-browser']:
    workflow['jobs']['partitioned-' + key] = prepare(base[key], 'Partitioned')
for key in ['python-suite', 'windows-tooling']:
    workflow['jobs']['baseline-' + key] = prepare(base[key], 'Baseline')

# Reconstruct the old combined ownership while keeping current source, assertions,
# native inventory and NAS coverage identical. Only HTTP/Git repetition changes.
combined = prepare(base['frontend-contract'], 'Baseline')
combined['name'] = 'Baseline | Combined frontend, UI and native browser'
combined['timeout-minutes'] = 30
combined['services'] = copy.deepcopy(base['native-browser']['services'])
combined['env'] = copy.deepcopy(base['native-browser']['env'])
steps = combined['steps']
contract_index = next(i for i, s in enumerate(steps) if s.get('run') == 'npm --prefix web run test:contracts')
steps.pop(contract_index)
image_index = next(i for i, s in enumerate(steps) if s.get('name', '').startswith('Build and inspect'))
overlay = r'''python - <<'PY'
from pathlib import Path
import hashlib, json, re
contracts = Path('web/contracts/visual-review.spec.ts').read_text()
ui_path = Path('web/e2e/visual-review.spec.ts')
ui = ui_path.read_text()
marker = "test('"
header, contract_body = contracts.split(marker, 1)
contract_body = marker + contract_body
ui_body = marker + ui.split(marker, 1)[1]
assert len(re.findall(r"^test\('", contract_body, re.M)) == 5
assert len(re.findall(r"^test\('", ui_body, re.M)) == 2
composed = header.replace('../e2e/', './') + contract_body + '\n' + ui_body
assert contract_body in composed and ui_body in composed
ui_path.write_text(composed)
proof = {'source_sha': '84f427e1ec0f9bb38baf63b7b4c6a6b0bb98f6db',
         'contract_body_sha256': hashlib.sha256(contract_body.encode()).hexdigest(),
         'ui_body_sha256': hashlib.sha256(ui_body.encode()).hexdigest(),
         'contract_tests': 5, 'page_tests': 2,
         'treatment': 'unchanged five contract bodies restored to four UI projects'}
Path('baseline-overlay-proof.json').write_text(json.dumps(proof, indent=2))
print(json.dumps(proof))
PY
'''
steps[image_index:image_index] = [
    {'name': 'Restore pre-partition execution ownership', 'shell': 'bash', 'run': overlay},
    {'name': 'Install Node browser engines', 'run': 'npm --prefix web exec -- playwright install --with-deps chromium firefox webkit'},
    {'name': 'Run unsharded UI and repeated contracts', 'run': 'npm --prefix web run test:browser'},
]
# Drop the unused run-once contract upload; collect combined reports below.
combined['steps'] = [s for s in steps if not s.get('uses', '').startswith('actions/upload-artifact@')]
for step in base['native-browser']['steps']:
    if step.get('run', '').startswith('python -m playwright install') or step.get('name') == 'Run native browser concurrency and core workflow tests':
        combined['steps'].append(copy.deepcopy(step))
combined['steps'].append({'name': 'Upload combined reports and overlay proof', 'if': '${{ always() }}',
    'uses': 'actions/upload-artifact@v4', 'with': {'name': 'baseline-combined-results',
    'path': 'native-browser-results.xml\nweb/test-results/\nbaseline-overlay-proof.json', 'if-no-files-found': 'ignore'}})
workflow['jobs']['baseline-combined'] = combined
needs = list(workflow['jobs'])
workflow['jobs']['evidence-status'] = {'name': 'Evidence pair status', 'if': '${{ always() }}',
    'needs': needs, 'runs-on': 'ubuntu-latest', 'timeout-minutes': 5,
    'steps': [{'name': 'Require all evidence components', 'env': {'RESULTS': '${{ toJSON(needs) }}'},
        'run': '''python - <<'PY'
import json, os
results = json.loads(os.environ['RESULTS'])
print(json.dumps(results, indent=2))
assert all(job['result'] == 'success' for job in results.values())
PY
'''}]}
output = root / '.github/workflows/ci-evidence.yml'
output.write_text(yaml.safe_dump(workflow, sort_keys=False, width=1000), encoding='utf-8')
assert len(needs) == 8  # UI matrix expands to two runners, giving nine components.
assert all(s.get('with', {}).get('ref') == SOURCE for j in workflow['jobs'].values() for s in j['steps'] if s.get('uses', '').startswith('actions/checkout@'))
print(f'Generated {output} for sample {SAMPLE}, fixed source {SOURCE}')
