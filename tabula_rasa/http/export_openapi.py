"""Deterministic schema-only export; no settings, database or network."""

import argparse
import json
from pathlib import Path

from .app import create_app


def export_schema(output: Path):
    schema = create_app(schema_only=True).openapi()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    export_schema(parser.parse_args().output)


if __name__ == "__main__":
    main()
