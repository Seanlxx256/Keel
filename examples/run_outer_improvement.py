"""Run bounded, offline prompt proposal and controlled diagnosis selection."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.models import from_config
from keel.outer_improvement import execute, validate_candidates
from examples.evaluate_diagnosis import load_completed, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-seconds', type=int, default=900)
    parser.add_argument('--validate-pilot', type=Path, help='Freeze candidates from a completed pilot; no new proposal')
    parser.add_argument('--feedback-from', type=Path, help='Propose one candidate from verified validation failures; replay three cases')
    parser.add_argument('--reuse-proposal', type=Path, help='Migrate a saved pre-trial proposal without another proposal call')
    parser.add_argument('--recover-guards', action='store_true', help='Host candidate identities and one citation correction within existing limits')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.max_seconds <= 900:
        parser.error('--max-seconds must be 1..900')
    if args.validate_pilot and args.feedback_from:
        parser.error('--validate-pilot and --feedback-from are mutually exclusive')
    if args.feedback_from and args.max_seconds > 300:
        parser.error('Feedback replay requires --max-seconds <=300')
    raw = args.model_config.read_bytes()
    feedback = None
    if args.feedback_from:
        from keel.outer_feedback import collect_feedback
        feedback = collect_feedback(args.feedback_from, hashlib.sha256(raw).hexdigest())
    validation = None
    if args.validate_pilot:
        source = args.validate_pilot
        report = json.loads((source/'report.json').read_text(encoding='utf-8'))
        manifest = json.loads((source/'manifest.json').read_text(encoding='utf-8'))
        candidates = validate_candidates({'candidates': json.loads((source/'candidates.json').read_text(encoding='utf-8'))})
        proposal = json.loads((source/'proposal.json').read_text(encoding='utf-8'))
        receipt = json.loads((source/'proposal-receipt.json').read_text(encoding='utf-8'))
        if (report['status'] != 'completed' or report['manifest_sha256'] != digest(manifest)
                or manifest['config_sha256'] != hashlib.sha256(raw).hexdigest()
                or receipt != {'proposal': digest(proposal), 'candidates': digest(candidates)}):
            raise ValueError('Pilot receipt or model configuration mismatch')
        for row in report['records']:
            record = load_completed(source/(row['case']+'-'+row['arm']))
            if row['passed'] != record['score']['passed']:
                raise ValueError('Pilot score mismatch')
        validation = {'source': {name: hashlib.sha256((source/name).read_bytes()).hexdigest()
                       for name in ('report.json', 'manifest.json', 'candidates.json', 'proposal.json')},
                      'candidates': candidates}
    model = from_config(json.loads(raw))
    model.check_credentials()
    report = execute(model, args.output, config_hash=hashlib.sha256(raw).hexdigest(),
                     max_seconds=args.max_seconds, resume=args.resume, validation=validation, feedback=feedback, reuse_proposal=args.reuse_proposal, recover_guards=args.recover_guards)
    print(json.dumps({'status': report['status'], 'selection': report['selection'],
                      'report': str(args.output/'report.json')}))


if __name__ == '__main__':
    main()
