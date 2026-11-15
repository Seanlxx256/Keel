import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keel.docker_isolation import (PLANNED,PROBE_CHECKS,canonical_mount,execute,
                                  inspect_checks,source_identity,validate_probe)
from keel.isolation_probe import peer_not_addressable


class DockerIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def inspection(self):
        return {'User':'65534:65534','State':{'Running':True},
            'HostConfig':{'NetworkMode':'none','ReadonlyRootfs':True,'Privileged':False,
                'PidMode':'','CapDrop':['ALL'],'SecurityOpt':['no-new-privileges'],
                'Memory':256*1024*1024,'MemorySwap':256*1024*1024,'PidsLimit':64,
                'NanoCpus':1000000000,'Tmpfs':{'/tmp':'rw,noexec,nosuid,size=64m'}},
            'Mounts':[{'Type':'bind','Destination':'/workspace','Source':str(self.root/'repo'),'RW':False},
                      {'Type':'bind','Destination':'/keel-reports','Source':str(self.root/'reports'),'RW':True},
                      {'Type':'tmpfs','Destination':'/tmp','RW':True}]}

    def test_actual_inspection_contract_accepts_only_declared_isolation(self):
        checks=inspect_checks(self.inspection(),self.root/'repo',self.root/'reports')
        self.assertTrue(all(checks.values()),checks)

    def test_network_pid_and_privilege_regressions_are_not_accepted(self):
        for field,value,key in [('NetworkMode','host','network_none'),('PidMode','host','private_pid_mode'),
                                ('Privileged',True,'not_privileged'),('ReadonlyRootfs',False,'root_readonly')]:
            inspection=self.inspection();inspection['HostConfig'][field]=value
            self.assertFalse(inspect_checks(inspection,self.root/'repo',self.root/'reports')[key])

    def test_extra_database_mount_or_writable_source_is_rejected(self):
        inspection=self.inspection()
        inspection['Mounts'].append({'Type':'bind','Source':str(self.root/'control.sqlite'),'Destination':'/control','RW':False})
        self.assertFalse(inspect_checks(inspection,self.root/'repo',self.root/'reports')['exact_bind_mounts'])
        inspection=self.inspection();inspection['Mounts'][0]['RW']=True
        self.assertFalse(inspect_checks(inspection,self.root/'repo',self.root/'reports')['exact_bind_mounts'])

    def test_missing_resource_limits_are_rejected(self):
        inspection=self.inspection();inspection['HostConfig']['Memory']=0
        inspection['HostConfig']['PidsLimit']=0;inspection['HostConfig']['NanoCpus']=0
        result=inspect_checks(inspection,self.root/'repo',self.root/'reports')
        self.assertFalse(result['bounded_memory']);self.assertFalse(result['bounded_processes']);self.assertFalse(result['bounded_cpu'])

    def test_added_capabilities_are_rejected_even_with_cap_drop(self):
        inspection=self.inspection();inspection['HostConfig']['CapAdd']=['NET_ADMIN']
        self.assertFalse(inspect_checks(inspection,self.root/'repo',self.root/'reports')['no_added_capabilities'])

    def test_numeric_pid_collision_is_not_access_to_another_namespace(self):
        with patch('keel.isolation_probe.os.kill'),patch('keel.isolation_probe.os.readlink',return_value='pid:[111]'):
            self.assertTrue(peer_not_addressable(5,'pid:[222]'))
            self.assertFalse(peer_not_addressable(5,'pid:[111]'))
        with patch('keel.isolation_probe.os.kill'),patch('keel.isolation_probe.os.readlink',side_effect=PermissionError):
            self.assertFalse(peer_not_addressable(5,'pid:[222]'))

    def test_mount_alias_is_normalized_without_loosening_target_set(self):
        if os.name=='nt':
            self.assertEqual(canonical_mount('/run/desktop/mnt/host/d/Keel/repo'),canonical_mount('D:\\Keel\\repo'))
        self.assertNotEqual(canonical_mount('/repo-one'),canonical_mount('/repo-two'))

    def probe(self,role):
        return {'role':role,'pid':5,'pid_namespace':'pid:[1234]','net_namespace':'net:[5678]',
                'checks':{key:True for key in PROBE_CHECKS|({'peer_process_not_addressable'} if role=='a' else set())}}

    def test_probe_must_report_all_checks_no_empty_all_pass(self):
        validate_probe(self.probe('a'),'a')
        for change in [{}, {'non_root':True}, {key:'true' for key in PROBE_CHECKS}]:
            value=self.probe('b');value['checks']=change
            with self.assertRaises(ValueError):validate_probe(value,'b')

    def test_negative_check_is_preserved_not_coerced_or_dropped(self):
        value=self.probe('a');value['checks']['peer_process_not_addressable']=False
        result=validate_probe(value,'a')
        self.assertFalse(all(result['checks'].values()))

    def test_missing_namespace_or_wrong_role_cannot_be_pass(self):
        for key,value in [('role','a'),('pid_namespace','unknown'),('pid',0)]:
            probe=self.probe('b');probe[key]=value
            with self.assertRaises(ValueError):validate_probe(probe,'b')

    def test_unavailable_docker_records_no_executed_checks_and_no_local_fallback(self):
        output=self.root/'unavailable'
        with patch('keel.docker_isolation.docker_health',return_value={'ready':False,'diagnostic':'permission denied'}),\
             patch('keel.docker_isolation.CommandRunner.run',side_effect=AssertionError('must not execute')):
            report=execute(output)
        self.assertEqual(report['status'],'unavailable')
        self.assertEqual(report['checks'],{})
        self.assertEqual(report['model_calls'],0)
        self.assertIn('permission denied',report['error'])
        latest=json.loads((output/'latest.json').read_text())
        self.assertEqual(json.loads(Path(latest['report']).read_text())['status'],'unavailable')

    def test_resume_preserves_failed_attempt_and_rejects_implementation_drift(self):
        output=self.root/'resume'
        with patch('keel.docker_isolation.docker_health',return_value={'ready':False,'diagnostic':'not ready'}):
            first=execute(output)
            second=execute(output,resume=True)
        self.assertNotEqual(first['attempt'],second['attempt'])
        self.assertTrue((Path(first['attempt'])/'report.json').is_file())
        manifest=json.loads((output/'manifest.json').read_text());manifest['implementation']['keel/execution.py']='wrong'
        (output/'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):execute(output,resume=True)

    def test_completed_reuse_verifies_evidence_and_does_not_call_docker(self):
        output=self.root/'reuse';output.mkdir()
        manifest={'requested_image':None,'requested_python':None,'max_seconds':240,'implementation':source_identity()}
        (output/'manifest.json').write_text(json.dumps(manifest))
        evidence=output/'evidence.json';evidence.write_text('{"fixture": true}')
        report={'status':'passed','checks':{name:{'passed':True} for name in PLANNED},'model_calls':0,
                'artifact_hashes':{'evidence.json':hashlib.sha256(evidence.read_bytes()).hexdigest()}}
        saved=output/'completed.json';saved.write_text(json.dumps(report))
        (output/'latest.json').write_text(json.dumps({'report':str(saved),'report_sha256':hashlib.sha256(saved.read_bytes()).hexdigest()}))
        with patch('keel.docker_isolation.docker_health',side_effect=AssertionError('must not redispatch')):
            reused=execute(output,resume=True)
        self.assertEqual(reused['status'],'reused');self.assertFalse(reused['fresh_execution'])
        evidence.write_text('changed')
        with self.assertRaises(ValueError):execute(output,resume=True)

    def test_existing_output_or_invalid_budget_is_rejected_before_dispatch(self):
        with self.assertRaises(ValueError):execute(self.root)
        with self.assertRaises(ValueError):execute(self.root/'bad',max_seconds=float('inf'))

    @unittest.skipUnless(os.environ.get('KEEL_TEST_DOCKER_ISOLATION_IMAGE'),'Real Docker image not explicitly configured')
    def test_real_docker_fixture_suite(self):
        result=execute(self.root/'real',image=os.environ['KEEL_TEST_DOCKER_ISOLATION_IMAGE'],
                       python=os.environ.get('KEEL_TEST_DOCKER_ISOLATION_PYTHON'),max_seconds=240)
        self.assertEqual(result['status'],'passed',result)


if __name__=='__main__':unittest.main()
