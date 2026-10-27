"""Archive only approved checkpoint groups; verify before removing originals."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keel.checkpoint_archive import archive_checkpoints,restore_checkpoint

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument('--proposal',type=Path)
    p.add_argument('--archive',type=Path)
    p.add_argument('--record',type=Path,required=True)
    p.add_argument('--seconds',type=float,default=900)
    p.add_argument('--restore-directory')
    a=p.parse_args()
    if a.restore_directory:
        print(json.dumps({'restored':restore_checkpoint(a.record,a.restore_directory,seconds=a.seconds)}))
    else:
        if not a.proposal or not a.archive:p.error('--proposal and --archive are required for archival')
        print(json.dumps(archive_checkpoints(a.workspace,a.proposal,a.archive,a.record,seconds=a.seconds)))
