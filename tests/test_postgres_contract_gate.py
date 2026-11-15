"""Synthetic evidence validators only; no server or driver calls in this module."""
import json
from pathlib import Path
import tempfile
import unittest

from examples.verify_postgres_contracts import NATIVE_CONTRACTS, verify
from keel.evaluation_protocol import implementation_hashes, file_hash


class PostgresContractGateTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.base=Path(temp.name);self.root=self.base/'source';self.folder=self.base/'evidence'
        (self.root/'keel').mkdir(parents=True)
        (self.root/'keel'/'postgres_store.py').write_text('fixture = 1\n')
        (self.root/'tests').mkdir()
        sources=[self.root/'tests'/name for name in ('test_postgres_store.py','test_postgres_integration.py')]
        for path in sources:path.write_text('fixture = 1\n')
        self.modules=['tests.test_postgres_store','tests.test_postgres_integration']
        self.plan={'root':str(self.root),'modules':self.modules,'implementation':implementation_hashes(self.root),
                   'input_hashes':{str(path):file_hash(path) for path in sources}}
        inventory=['tests.test_postgres_store.Fixture.test_unit',*sorted(NATIVE_CONTRACTS)]
        self.report={'status':'passed','modules':self.modules,'tests_run':len(inventory),'passed':len(inventory),
            'test_inventory':inventory,'failures':[],'errors':[],'skipped':[],
            'expected_failures':0,'unexpected_successes':0,'declared_inputs_unchanged':True}
        self.write('preflight/report.json',{'status':'passed','check_value':1,'driver_available':True,
            'dsn_configured':True,'server_version':'synthetic-fixture'})
        self.write('plan.json',self.plan);self.write('results/report.json',self.report)
        self.write('watchdog.json',{'status':'passed','returncode':0})
        self.write('identity.json',{'commit':'synthetic-fixture','psycopg_version':'synthetic-fixture'})
        (self.folder/'console.log').write_text('synthetic validator fixture, not a database run\n')

    def write(self,name,value):
        path=self.folder/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value),encoding='utf-8')

    def rejected(self):
        with self.assertRaises(ValueError):verify(self.folder)
        self.assertEqual(json.loads((self.folder/'acceptance.json').read_text())['status'],'incomplete')

    def test_valid_synthetic_structure_produces_hash_bound_verdict(self):
        verdict=verify(self.folder)
        self.assertEqual(verdict['native_tests_run'],len(NATIVE_CONTRACTS))
        self.assertEqual(verdict['artifacts_sha256']['results/report.json'],file_hash(self.folder/'results/report.json'))

    def test_skipped_native_cases_rejected(self):
        self.report['skipped']=[{'test':'native','reason':'unavailable'}]
        self.write('results/report.json',self.report);self.rejected()

    def test_missing_inventory_rejected(self):
        self.report.pop('test_inventory');self.write('results/report.json',self.report);self.rejected()

    def test_units_only_inventory_cannot_claim_native_validation(self):
        self.report.update(test_inventory=['tests.test_postgres_store.Fixture.test_unit'],tests_run=1,passed=1)
        self.write('results/report.json',self.report);self.rejected()

    def test_one_missing_required_native_case_rejected(self):
        self.report['test_inventory'].pop();self.report['tests_run']-=1;self.report['passed']-=1
        self.write('results/report.json',self.report);self.rejected()

    def test_unavailable_preflight_rejected(self):
        self.write('preflight/report.json',{'status':'unavailable'});self.rejected()

    def test_changed_source_rejected(self):
        (self.root/'keel'/'postgres_store.py').write_text('fixture = 2\n');self.rejected()

    def test_missing_test_hash_binding_rejected(self):
        self.plan['input_hashes']={};self.write('plan.json',self.plan);self.rejected()

    def test_unsuccessful_watchdog_rejected(self):
        self.write('watchdog.json',{'status':'unresolved','returncode':1});self.rejected()

    def test_expected_failure_is_not_native_success(self):
        self.report['expected_failures']=1;self.write('results/report.json',self.report);self.rejected()

    def test_prior_verdict_is_preserved(self):
        expected=verify(self.folder)
        with self.assertRaises(FileExistsError):verify(self.folder)
        self.assertEqual(json.loads((self.folder/'acceptance.json').read_text()),expected)
