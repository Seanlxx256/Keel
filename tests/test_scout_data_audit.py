import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keel.scout_data_audit import audit,_inspect


def events(target=None):
    return [{'event':'request','args':[[{'role':'user','content':'PRIVATE_SOURCE_TEXT'}]],
        'kwargs':{'schema':{'type':'object','properties':{'files':{'type':'array','minItems':1,
            'maxItems':2,'items':{'type':'string','enum':['module.py','other.py']}}},
            'required':['files'],'additionalProperties':False}}},
        {'event':'response','content':json.dumps({'files':target if target is not None else ['module.py']})}]


def write(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')


class ScoutDataAuditTests(unittest.TestCase):
    def test_source_change_after_inspection_invalidates_completed_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'input';path=source/'model-transcript.jsonl';write(path,events())
            def inspect(*args):
                result=_inspect(*args)
                with path.open('a') as stream:stream.write('{}\n')
                return result
            with patch('keel.scout_data_audit._inspect',side_effect=inspect):
                result=audit([source],root/'out')
            self.assertEqual(result['status'],'incomplete')
            self.assertEqual(result['error_type'],'ValueError')
            self.assertEqual(result['training_approved'],0)

    def test_progress_failure_does_not_mask_required_result(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'input';write(source/'model-transcript.jsonl',events())
            with patch('keel.scout_data_audit.ProgressLog.emit',side_effect=PermissionError):
                result=audit([source],root/'out')
            self.assertEqual(result['status'],'completed')
            self.assertTrue(result['telemetry_error'])
            self.assertEqual(result['counts']['unique_review_candidates'],1)

    def test_actual_pair_metadata_hashes_no_raw_text_and_no_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'input';path=source/'model-transcript.jsonl'
            write(path,events())
            (source/'trial.json').write_text(json.dumps({'instance_id':'org__lib-1','runtime_status':'passed',
                'official_resolved':True,'api_key':'DO_NOT_EXPORT'}))
            report=audit([source],root/'out')
            self.assertEqual(report['status'],'completed')
            self.assertEqual(report['counts']['unique_review_candidates'],1)
            self.assertEqual(report['unique_candidates_by_task'],{'org__lib-1':1})
            self.assertEqual(report['training_approved'],0)
            row=json.loads((root/'out/candidates.jsonl').read_text())
            self.assertEqual(row['transcript_sha256'],hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertFalse(row['training_approved'])
            self.assertEqual(row['context']['manual_assistance'],'unknown')
            text=''.join(p.read_text(encoding='utf-8') for p in (root/'out').iterdir())
            self.assertNotIn('PRIVATE_SOURCE_TEXT',text);self.assertNotIn('DO_NOT_EXPORT',text)

    def test_duplicate_examples_and_conflicting_targets_are_counted(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'input'
            write(source/'a/model-transcript.jsonl',events())
            write(source/'b/model-transcript.jsonl',events())
            write(source/'c/model-transcript.jsonl',events(['other.py']))
            report=audit([source,source/'a'],root/'out')
            self.assertEqual(report['discovered_transcripts'],3)
            self.assertEqual(report['counts']['exact_duplicates'],1)
            self.assertEqual(report['counts']['unique_review_candidates'],2)
            self.assertEqual(report['states_with_different_targets'],1)

    def test_unknown_enum_selection_rejected_and_no_success_inference(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'input'
            write(source/'model-transcript.jsonl',events(['unseen.py']))
            report=audit([source],root/'out')
            self.assertEqual(report['counts']['structurally_rejected'],1)
            self.assertNotIn('unique_review_candidates',report['counts'])
            row=json.loads((root/'out/candidates.jsonl').read_text())
            self.assertIn('selection_outside_schema_enum',row['issues'])

    def test_lost_event_or_unfinished_call_excludes_entire_file(self):
        for kind in ('missing_response','missing_request','bad_json','overlapping_requests'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);source=root/'input';path=source/'model-transcript.jsonl'
                rows=events()
                if kind=='missing_response':rows=rows[:1]
                if kind=='missing_request':rows=rows[1:]
                if kind=='overlapping_requests':rows=[rows[0],*rows]
                write(path,rows)
                if kind=='bad_json':
                    with path.open('a') as stream:stream.write('{broken\n')
                report=audit([source],root/'out')
                self.assertEqual(report['excluded_transcripts'],1)
                self.assertEqual((root/'out/candidates.jsonl').read_text(),'')

    def test_failed_provider_call_is_not_a_training_example(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'input';rows=events()
            rows[1]={'event':'error','error_type':'ModelCompletionError'}
            write(source/'model-transcript.jsonl',rows)
            report=audit([source],root/'out')
            self.assertEqual(report['counts'],{})
            self.assertEqual(report['files'][0]['events']['error'],1)

    def test_resource_exclusions_are_explicit_not_silent_truncation(self):
        for limits in ({'max_file_bytes':10},{'max_line_bytes':10}):
            with self.subTest(limits=limits),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);source=root/'input';write(source/'model-transcript.jsonl',events())
                report=audit([source],root/'out',**limits)
                self.assertEqual(report['excluded_transcripts'],1)
                self.assertIn('resource_envelope',report['files'][0]['issues'][0])
                self.assertEqual((root/'out/candidates.jsonl').read_text(),'')

    def test_snapshot_repos_and_duplicate_roots_do_not_inflate_inventory(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'input'
            for folder in ('snapshot','repo','real'):write(source/folder/'model-transcript.jsonl',events())
            report=audit([source,source],root/'out')
            self.assertEqual(report['discovered_transcripts'],1)

    def test_deadline_produces_incomplete_receipt_not_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'input';source.mkdir()
            with patch('keel.scout_data_audit.time.monotonic',side_effect=[0]+[5]*30):
                report=audit([source],root/'out',timeout=1)
            self.assertEqual(report['status'],'incomplete')
            self.assertEqual(report['error_type'],'TimeoutError')
            self.assertTrue((root/'out/report.json').is_file())

    def test_output_preserved_and_required_receipt_failure_is_not_telemetry(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'input';source.mkdir()
            audit([source],root/'out')
            with self.assertRaises(FileExistsError):audit([source],root/'out')
            with patch('keel.scout_data_audit.atomic_json',side_effect=PermissionError):
                with self.assertRaises(PermissionError):audit([source],root/'failed')

    def test_unknown_messages_or_schema_never_become_sft_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'input';rows=events()
            rows[0]['args']=[None]
            write(source/'model-transcript.jsonl',rows)
            report=audit([source],root/'out')
            self.assertEqual(report['counts']['structurally_rejected'],1)
            self.assertEqual(report['training_approved'],0)


if __name__=='__main__':unittest.main()
