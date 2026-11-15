"""Run a declared local suite inside the shared bounded-exploration watchdog."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from compass.progress import atomic_json
from keel.evaluation_protocol import implementation_hashes


def test_inventory(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):yield from test_inventory(item)
        else:yield item.id()


def execute(plan_path):
    plan=json.loads(Path(plan_path).read_text(encoding='utf-8'))
    root=Path(plan['root']);output=Path(plan['output'])
    def identity():
        return (implementation_hashes(root)==plan['implementation'] and
            all(hashlib.sha256(Path(name).read_bytes()).hexdigest()==value
                for name,value in plan['input_hashes'].items()))
    if not identity():raise ValueError('Declared implementation or test inputs changed')
    output.mkdir(parents=True,exist_ok=False)
    report={'status':'running','python':sys.executable,'modules':plan['modules'],
            'scope':'Declared local regressions; no full CI or deployment certification'}
    # Required sink is established before importing/running any test.
    atomic_json(output/'report.json',report)
    started=time.monotonic()
    try:
        suite=unittest.defaultTestLoader.loadTestsFromNames(plan['modules'])
        report['test_inventory']=list(test_inventory(suite))
        atomic_json(output/'report.json',report)
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        unchanged=identity()
        report.update(status='passed' if result.wasSuccessful() and unchanged else 'unresolved',
            tests_run=result.testsRun,
            passed=result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped)
                -len(result.expectedFailures)-len(result.unexpectedSuccesses),
            failures=[{'test':str(test),'traceback':detail} for test,detail in result.failures],
            errors=[{'test':str(test),'traceback':detail} for test,detail in result.errors],
            skipped=[{'test':str(test),'reason':reason} for test,reason in result.skipped],
            expected_failures=len(result.expectedFailures),unexpected_successes=len(result.unexpectedSuccesses),
            declared_inputs_unchanged=unchanged)
    except BaseException as error:
        report.update(status='interrupted',error_type=type(error).__name__)
        raise
    finally:
        report['seconds']=time.monotonic()-started
        atomic_json(output/'report.json',report)
    print(json.dumps({key:value for key,value in report.items() if key not in {'modules','errors','failures','skipped','test_inventory'}}),flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    args=parser.parse_args()
    sys.exit(0 if execute(args.plan)['status']=='passed' else 1)
