"""Real subprocess regressions; outer worker deadline prevents a pipe-cleanup hang."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


class HarnessProcessCleanupTests(unittest.TestCase):
    def exercise(self,root,parent_exits,implementation_root=None):
        leaf=root/'leaf.py';parent=root/'parent.py';worker=root/'worker.py'
        leaf.write_text("import os,time\nfrom pathlib import Path\np=Path("+repr(str(root))+')\n'+
            "(p/'leaf.pid').write_text(str(os.getpid()))\nfor i in range(600):\n    if (p/'stop').exists():break\n    (p/'heartbeat').write_text(str(i))\n    time.sleep(.05)\n",encoding='utf-8')
        parent.write_text("import os,subprocess,sys,time\nfrom pathlib import Path\np=Path("+repr(str(root))+')\n'+
            "(p/'parent.pid').write_text(str(os.getpid()))\nsubprocess.Popen([sys.executable,str(p/'leaf.py')],stdout=sys.stdout,stderr=sys.stderr)\n"+
            "for i in range(100):\n    if (p/'leaf.pid').exists():break\n    time.sleep(.01)\nprint('descendant inherited output',flush=True)\n"+
            ('' if parent_exits else "for i in range(600):\n    if (p/'stop').exists():break\n    time.sleep(.05)\n"),encoding='utf-8')
        repo=Path(implementation_root) if implementation_root else Path(__file__).resolve().parents[1]
        worker.write_text("import sys,json,subprocess\nfrom pathlib import Path\nsys.path.insert(0,"+repr(str(repo))+')\n'+
            "from examples.swebench_bridge import run_harness\np=Path("+repr(str(root))+')\n'+
            "try:\n    value=run_harness([sys.executable,'-u',str(p/'parent.py')],cwd=p,log_path=p/'harness.log',timeout=2,heartbeat=.1)\n    result={'timeout':False,'returncode':value.returncode}\nexcept subprocess.TimeoutExpired:\n    result={'timeout':True}\n(p/'observed.json').write_text(json.dumps(result))\n",encoding='utf-8')
        started=time.monotonic()
        try:
            done=subprocess.run([sys.executable,str(worker)],capture_output=True,timeout=12)
            self.assertEqual(done.returncode,0,done.stderr.decode(errors='replace'))
            self.assertLess(time.monotonic()-started,10)
            self.assertIn('descendant inherited output',(root/'harness.log').read_text(encoding='utf-8'))
            observed=json.loads((root/'observed.json').read_text())
            receipt=json.loads((root/'harness-process.json').read_text())
            if parent_exits:
                self.assertEqual(observed,{'timeout':False,'returncode':0})
                self.assertEqual(receipt['status'],'exited')
            else:
                self.assertTrue(observed['timeout'])
                self.assertEqual(receipt['status'],'timed_out')
                self.assertTrue(receipt['cleanup']['root_exited'])
            self.assertTrue((root/'leaf.pid').exists())
            before=(root/'heartbeat').read_bytes();time.sleep(.3)
            self.assertEqual((root/'heartbeat').read_bytes(),before,'Descendant continued executing after runner cleanup')
        finally:
            (root/'stop').write_text('stop')
            time.sleep(.2)
            # Fixture-owned PIDs only; also clean up when the old buggy runner hits outer timeout.
            for name in ('parent.pid','leaf.pid'):
                file=root/name
                if not file.exists():continue
                pid=int(file.read_text())
                if os.name=='nt':
                    subprocess.run(['taskkill','/PID',str(pid),'/T','/F'],stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3,
                        creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    try:os.kill(pid,signal.SIGKILL)
                    except ProcessLookupError:pass

    def test_timeout_stops_descendant_holding_inherited_output_and_returns(self):
        with tempfile.TemporaryDirectory() as temp:self.exercise(Path(temp),False)

    def outer_watchdog_fixture(self,nested=False):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);repo=Path(__file__).resolve().parents[1]
            child=root/'parent.py';leaf=root/'leaf.py';worker=root/'worker.py'
            leaf.write_text("import os,time\nfrom pathlib import Path\np=Path("+repr(temp)+")\n(p/'leaf.pid').write_text(str(os.getpid()))\nfor i in range(600):\n    if (p/'stop').exists():break\n    (p/'heartbeat').write_text(str(i))\n    time.sleep(.05)\n")
            if nested:
                child.write_text("import sys\nfrom pathlib import Path\nsys.path.insert(0,"+repr(str(repo))+")\nfrom examples.swebench_bridge import run_harness\np=Path("+repr(temp)+")\nrun_harness([sys.executable,"+repr(str(leaf))+"],cwd=p,log_path=p/'inner.log',timeout=30,heartbeat=.1)\n")
            else:
                child.write_text("import subprocess,sys,time\nsubprocess.Popen([sys.executable,"+repr(str(leaf))+"])\ntime.sleep(30)\n")
            plan={'root':str(root),'implementation':{},'output':str(root/'trial'),'python':sys.executable,'arguments':[str(child)],'max_seconds':2}
            (root/'plan.json').write_text(json.dumps(plan))
            worker.write_text("import sys\nfrom pathlib import Path\nsys.path.insert(0,"+repr(str(repo))+")\nfrom examples.run_bounded_exploration import execute\nexecute(Path("+repr(str(root/'plan.json'))+"))\n")
            try:
                done=subprocess.run([sys.executable,str(worker)],capture_output=True,timeout=12)
                self.assertEqual(done.returncode,0,done.stderr.decode(errors='replace'))
                result=json.loads((root/'watchdog.json').read_text())
                self.assertEqual(result['status'],'deadline_exceeded')
                self.assertLess(result['seconds'],10)
                self.assertTrue((root/'leaf.pid').exists())
                before=(root/'heartbeat').read_bytes();time.sleep(.3)
                self.assertEqual((root/'heartbeat').read_bytes(),before)
            finally:
                (root/'stop').write_text('stop')
                time.sleep(.2)

    def test_outer_watchdog_also_terminates_real_descendants(self):
        self.outer_watchdog_fixture()

    @unittest.skipUnless(os.name=='nt','Windows nested Job Object containment')
    def test_windows_outer_watchdog_terminates_nested_harness_job(self):
        self.outer_watchdog_fixture(nested=True)

    def test_parent_exit_does_not_wait_for_descendant_output_eof(self):
        with tempfile.TemporaryDirectory() as temp:self.exercise(Path(temp),True)
