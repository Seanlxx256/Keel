"""Validate retained native PostgreSQL contract evidence; never execute SQL."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from compass.progress import atomic_json
from keel.evaluation_protocol import implementation_hashes, file_hash


MODULES={'tests.test_postgres_store','tests.test_postgres_integration'}
NATIVE_CONTRACTS={
    'tests.test_postgres_integration.PostgresIntegrationTests.'+name for name in (
        'test_concurrent_duplicates_commit_one_business_effect',
        'test_reopen_uses_receipt_without_business_callback',
        'test_callback_failure_rolls_back_effect_and_intent',
        'test_principal_namespaces_are_separate',
        'test_changed_input_cannot_reapply')}


def verify(folder):
    folder=Path(folder);destination=folder/'acceptance.json'
    if destination.exists():raise FileExistsError('Prior acceptance report must be preserved')
    # Exclusive claim preserves a previous adjudication instead of overwriting it.
    (folder/'acceptance-claim').mkdir(exist_ok=False)
    verdict={'status':'checking','scope':'Native PostgreSQL operation contracts only; not full controller migration'}
    atomic_json(destination,verdict)
    try:
        def read(name):return json.loads((folder/name).read_text(encoding='utf-8'))
        preflight=read('preflight/report.json');plan=read('plan.json')
        report=read('results/report.json');watchdog=read('watchdog.json');identity=read('identity.json')
        if (preflight.get('status')!='passed' or preflight.get('check_value')!=1
                or not preflight.get('driver_available') or not preflight.get('dsn_configured')):
            raise ValueError('Native PostgreSQL preflight did not pass')
        if watchdog.get('status')!='passed' or watchdog.get('returncode')!=0:
            raise ValueError('Bounded test execution did not pass')
        if set(plan.get('modules',[]))!=MODULES or report.get('modules')!=plan['modules']:
            raise ValueError('Required database contract modules were not declared and executed')
        if (report.get('status')!='passed'
                or any(not isinstance(report.get(field),list) or report[field] for field in ('failures','errors','skipped'))
                or any(type(report.get(field)) is not int or report[field]!=0 for field in ('expected_failures','unexpected_successes'))):
            raise ValueError('Contract outcome unavailable, skipped or unsuccessful')
        inventory=report.get('test_inventory')
        if (not isinstance(inventory,list) or not inventory or any(not isinstance(name,str) for name in inventory)
                or len(set(inventory))!=len(inventory) or report.get('tests_run')!=len(inventory)
                or report.get('passed')!=len(inventory)):
            raise ValueError('Actual test inventory missing or inconsistent')
        native=[name for name in inventory if name.startswith('tests.test_postgres_integration.')]
        if not NATIVE_CONTRACTS<=set(native) or any(not any(name.startswith(module+'.') for module in MODULES) for name in inventory):
            raise ValueError('Required native PostgreSQL cases missing from executed inventory')
        if (not report.get('declared_inputs_unchanged')
                or implementation_hashes(Path(plan['root']))!=plan['implementation']
                or any(file_hash(Path(name))!=expected for name,expected in plan['input_hashes'].items())):
            raise ValueError('Declared implementation or test inputs changed')
        root=Path(plan['root'])
        for module in MODULES:
            required=root/(module.replace('.','/')+'.py')
            if not any(Path(name).samefile(required) for name in plan['input_hashes']):
                raise ValueError('Required test source hash binding missing')
        if not identity.get('commit') or not identity.get('psycopg_version') or not preflight.get('server_version'):
            raise ValueError('Execution identity metadata unavailable')
        names=['preflight/report.json','plan.json','results/report.json','watchdog.json','identity.json','console.log']
        verdict.update(status='passed',tests_run=len(inventory),native_tests_run=len(native),
            native_test_inventory=native,server_version=preflight.get('server_version'),
            commit=identity['commit'],psycopg_version=identity['psycopg_version'],
            artifacts_sha256={name:file_hash(folder/name) for name in names})
    except (OSError,ValueError,KeyError,TypeError) as error:
        verdict.update(status='incomplete',failure_type=type(error).__name__,
                       failed_condition=str(error) if type(error) is ValueError else 'Evidence unavailable or malformed')
        raise
    finally:atomic_json(destination,verdict)
    return verdict


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    result=verify(parser.parse_args().output)
    print(json.dumps(result),flush=True)
