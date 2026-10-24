import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from keel.stage_progress import AptProgressBudget
from examples.swebench_bridge import run_harness


class StageProgressTests(unittest.TestCase):
    def test_recent_new_package_renews_but_repetition_does_not(self):
        budget=AptProgressBudget(1000)
        budget.observe('#8 597.3 Unpacking humanity-icon-theme (0.6.16) ...\n',597.3)
        self.assertEqual(budget.remaining(600),120)
        budget.observe('#8 710.0 Unpacking humanity-icon-theme (0.6.16) ...\n',710)
        self.assertEqual(budget.remaining(720),0)
        self.assertEqual(budget.reason,'no_fresh_distinct_progress')

    def test_stale_output_and_arbitrary_heartbeats_do_not_renew(self):
        budget=AptProgressBudget(1000)
        budget.observe('Get:1 http://example/package [10 kB]\n',100)
        budget.observe('process alive\n#8 599.0 waiting ...\n',599)
        self.assertEqual(budget.remaining(600),0)

    def test_total_stage_cap_cannot_be_extended(self):
        budget=AptProgressBudget(650)
        budget.observe('Unpacking first (1.0) ...\n',599)
        self.assertEqual(budget.remaining(600),50)
        budget.observe('Setting up second (1.0) ...\n',649)
        self.assertEqual(budget.remaining(650),0)
        self.assertEqual(budget.reason,'hard_stage_deadline')

    def test_split_lines_are_parsed_without_duplicate_progress(self):
        budget=AptProgressBudget(1000)
        budget.observe('#8 590.0 Unpack',590)
        budget.observe('ing abc (1) ...\n',591)
        self.assertEqual(len(budget.seen),1)
        self.assertEqual(budget.last_progress,591)

    def test_changed_download_counter_or_speed_is_not_new_progress(self):
        budget=AptProgressBudget(1000)
        budget.observe('Get:1 http://example/abc [10 kB]\nFetched 10 kB in 1s (10 kB/s)\n',590)
        budget.observe('Get:9 http://example/abc [10 kB]\nFetched 10 kB in 2s (5 kB/s)\n',599)
        self.assertEqual(len(budget.seen),2)
        self.assertEqual(budget.last_progress,590)

    def test_export_then_unpack_get_bounded_quiet_grace(self):
        budget=AptProgressBudget(1079)
        budget.observe('Setting up abc (1) ...\n',830)
        budget.observe('#9 exporting to image\n#9 exporting layers\n',834)
        budget.observe('#9 exporting layers 63.4s done\n#9 exporting manifest sha256:abc 0.1s done\n'
                       '#9 unpacking to docker.io/library/fixture:unique\n',900)
        self.assertEqual(budget.phase,'unpack')
        self.assertEqual(budget.remaining(960),119)
        self.assertEqual(budget.remaining(1079),0)
        self.assertEqual(budget.reason,'hard_stage_deadline')
        self.assertEqual(len(budget.phase_transitions),2)

    def test_repeated_terminal_phase_does_not_restart_quiet_grace(self):
        budget=AptProgressBudget(2000)
        budget.observe('#9 exporting to image\n#9 exporting layers\n',500)
        budget.observe('#9 exporting layers 20.0s\n',550)
        budget.observe('#9 exporting layers 100.0s\n',700)
        self.assertEqual(budget.last_progress,500)
        self.assertEqual(budget.limit,740)
        self.assertEqual(budget.remaining(740),0)
        self.assertEqual(len(budget.phase_transitions),1)

    def test_unrelated_unpack_text_does_not_claim_export_phase(self):
        budget=AptProgressBudget(1000)
        budget.observe('unpacking to random\n#7 unpacking to unrelated\n',599)
        self.assertEqual(budget.phase,'packages')
        self.assertEqual(budget.remaining(600),0)

    def test_real_process_quiet_export_can_finish_without_claiming_success_early(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            budget=AptProgressBudget(5,soft_seconds=.7,phase_grace_seconds=2)
            script="import time; print('#9 exporting to image',flush=True); print('#9 exporting layers',flush=True); time.sleep(1.2)"
            result=run_harness([sys.executable,'-u','-c',script],cwd=root,log_path=root/'run.log',
                               timeout=5,echo_output=False,progress_budget=budget)
            self.assertEqual(result.returncode,0)
            self.assertEqual(budget.phase,'export')
            self.assertEqual(len(budget.phase_transitions),1)

    def test_real_process_continues_past_soft_deadline_without_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            budget=AptProgressBudget(5,soft_seconds=1,extension_seconds=1,freshness_seconds=2)
            script="import time; print('Unpacking first (1) ...',flush=True); time.sleep(.6); print('Setting up first (1) ...',flush=True); time.sleep(.8)"
            result=run_harness([sys.executable,'-u','-c',script],cwd=root,log_path=root/'run.log',
                               timeout=5,echo_output=False,progress_budget=budget)
            self.assertEqual(result.returncode,0)
            self.assertTrue(budget.events)
            receipt=json.loads((root/'harness-process.json').read_text())
            self.assertEqual(receipt['status'],'exited')
            self.assertTrue(receipt['progress_budget']['extensions'])

    def test_real_process_without_milestones_stops_at_soft_deadline(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            budget=AptProgressBudget(5,soft_seconds=.5)
            with self.assertRaises(subprocess.TimeoutExpired):
                run_harness([sys.executable,'-c','import time; time.sleep(10)'],cwd=root,
                            log_path=root/'run.log',timeout=5,echo_output=False,progress_budget=budget)
            receipt=json.loads((root/'harness-process.json').read_text())
            self.assertEqual(receipt['status'],'timed_out')
            self.assertEqual(receipt['progress_budget']['stop_reason'],'no_fresh_distinct_progress')

    def test_workload_persists_budget_stop_without_claiming_download_error(self):
        from examples.check_repository_network import apt_workload
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            script=root/'setup.sh'
            script.write_text('apt-get -y update && apt-get -y upgrade && apt-get install -y unzip\n')
            output=root/'out';output.mkdir()
            def run(command,**kwargs):
                budget=kwargs['progress_budget']
                budget.observe('Unpacking abc (1) ...\n',599)
                budget.remaining(600)
                budget.remaining(720)
                raise subprocess.TimeoutExpired(command,720)
            inspected=subprocess.CompletedProcess([],0,stdout='sha256:'+'a'*64,stderr='')
            with patch('examples.check_repository_network.subprocess.run',return_value=inspected), \
                    patch('examples.check_repository_network.run_harness',side_effect=run):
                result=apt_workload(script,'fixture:latest',output,1000,progress_budget={'soft_seconds':600})
            self.assertEqual(result['status'],'stage_budget_exhausted')
            self.assertEqual(result['stop_reason'],'no_fresh_distinct_progress')
            self.assertEqual(len(result['progress_budget']['extensions']),1)
            self.assertEqual(json.loads((output/'diagnosis.json').read_text())['status'],'stage_budget_exhausted')
