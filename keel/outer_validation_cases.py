"""New synthetic selection families, authored after pilot prompts were frozen."""
from examples.evaluate_diagnosis import FAMILIES

FAMILIES_V2 = {
    'routing': {
        'symptom': 'send("primary") returns "backup"; expected "main".',
        'hypotheses': {
            'A': 'Name resolution maps primary to backup; transport preserves the resolved destination.',
            'B': 'Name resolution maps primary to main; transport always redirects to backup.'},
        'sources': {
            'A': 'def resolve(name):\n    return "backup"\ndef transport(target):\n    return target\ndef send(name):\n    return transport(resolve(name))\n',
            'B': 'def resolve(name):\n    return "main"\ndef transport(target):\n    return "backup"\ndef send(name):\n    return transport(resolve(name))\n'},
        'probes': {'resolve_primary': 'resolve("primary") == "main"',
                   'transport_main': 'transport("main") == "main"',
                   'original_failure': 'send("primary") == "main"'}},
    'snapshot': {
        'symptom': 'After saving [1] and appending 2 to the original, restore() returns [1, 2]; expected [1].',
        'hypotheses': {
            'A': 'save retains an alias to the original list; restore returns the stored list unchanged.',
            'B': 'save copies the input; restore itself appends 2 to a copy of the saved list.'},
        'sources': {
            'A': 'stored = []\ndef save(xs):\n    global stored\n    stored = xs\ndef peek():\n    return stored[:]\ndef restore():\n    return stored[:]\nxs = [1]\nsave(xs)\nxs.append(2)\n',
            'B': 'stored = []\ndef save(xs):\n    global stored\n    stored = xs[:]\ndef peek():\n    return stored[:]\ndef restore():\n    return stored[:] + [2]\nxs = [1]\nsave(xs)\nxs.append(2)\n'},
        'probes': {'stored_copy': 'peek() == [1]', 'original_failure': 'restore() == [1]',
                   'input_control': 'xs == [1, 2]'}}}
FAMILIES_V2['counter_control'] = FAMILIES['counter']
CASES_V2 = [('routing-A', 'routing', 'A'), ('snapshot-B', 'snapshot', 'B'),
            ('routing-B', 'routing', 'B'), ('snapshot-A', 'snapshot', 'A'),
            ('counter-control-B', 'counter_control', 'B')]
EVIDENCE_PROTOCOL = ('Evidence IDs refer only to observations returned by the executor. '
                     'Before the first probe, evidence_ids MUST be []. '
                     'Probe names and the initial symptom are NOT observation IDs. '
                     'After execution cite the exact returned observation-N ID. '
                     'Predictions refer to the truth of the displayed boolean expression, not to the hypothesis itself.')
