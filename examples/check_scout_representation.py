"""Run under an external enforced deadline, e.g. observed_stage."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keel.scout_representation_smoke import run

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('dataset','tokenizer-run','weights','output'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--input-mode',choices=('numbered','without_ids'),required=True)
    p.add_argument('--readout-mode',choices=('candidate_end','after_catalog'),required=True)
    a=p.parse_args()
    print(json.dumps(run(a.dataset,a.tokenizer_run,a.weights,a.output,input_mode=a.input_mode,readout_mode=a.readout_mode)))
