"""Execute the unchanged official harness with Linux artifact transport on Windows."""
import os
from pathlib import Path
import runpy
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.swebench_transport import linux_artifact_writes


if __name__ == '__main__':
    if os.name == 'nt':
        with linux_artifact_writes():
            runpy.run_module('swebench.harness.run_evaluation', run_name='__main__', alter_sys=True)
    else:
        runpy.run_module('swebench.harness.run_evaluation', run_name='__main__', alter_sys=True)
