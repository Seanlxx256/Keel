"""Encode approved development symbol selections as catalog candidate IDs."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.scout_id_training import export_ids

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = export_ids(args.source, args.output)
    print(json.dumps({'status': report['status'], 'sample_count': report['sample_count'],
                      'transformed_samples': report['transformed_samples'], 'model_calls': 0}))
