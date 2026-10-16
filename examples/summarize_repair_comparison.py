"""Export a read-only summary without modifying the source trial."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.evaluation_protocol import file_hash
from keel.repair_reporting import summarize, markdown


def export(source, output):
    raw = source.read_bytes()
    summary = summarize(json.loads(raw))
    summary['source_sha256'] = file_hash(source)
    output.mkdir(parents=True, exist_ok=False)
    (output/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    (output/'summary.md').write_text(markdown(summary), encoding='utf-8')
    if source.read_bytes() != raw:
        raise ValueError('Source changed while exporting')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(export(args.source, args.output), indent=2))
