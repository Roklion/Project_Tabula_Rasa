"""Preview exact-target resource retirement using a sanitized offline inventory."""

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tabula_rasa.deployment.resource_retirement import preview, read_inventory


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--target', action='append', required=True)
    args = parser.parse_args(argv)
    try:
        result = preview(read_inventory(args.inventory), args.target)
    except Exception:
        # Do not disclose input, paths, credentials or raw filesystem errors.
        print(json.dumps({'status': 'blocked', 'code': 'invalid_inventory', 'applied': False}))
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 1 if result['status'] == 'blocked' else 0


if __name__ == '__main__':
    raise SystemExit(main())
