"""Shared concise decision questions, not hidden reasoning or completion proof."""

DECISION_QUESTIONS = {
    'facts': 'What do current raw observations establish, and what remains unknown? Cite evidence; plans are not observations.',
    'alternatives': 'Compare plausible competing explanations, including a workflow/tool-state fault when relevant. Do not invent an alternative just to fill a quota.',
    'choice': 'Which permitted action best distinguishes the remaining explanations, and why choose it over the alternative? Name tool/input when available.',
    'success': 'What observable result would support or refute the hypothesis, and how would it change the next action? Repair success still requires independent acceptance.',
    'switch': 'What result, repetition or concrete obstacle means switch approach or report unresolved? Missing evidence calls for collection, not an unsupported blocker.',
}

SUMMARY_GUIDANCE = (
    'Give a concise decision brief, not private chain-of-thought: FACTS (cited observations/unknowns), '
    'ALTERNATIVES (plausible explanations), CHOICE (action and why), SUCCESS (observable prediction), '
    'SWITCH (when to change course). Reuse established facts; do not re-narrate history. '
    'A comment or equivalent rewrite is not a repair: name the expected behavioral difference. '
    'Instructions to investigate belong in a check/handoff, not a source comment. '
    'State capability limits honestly; do not claim an unavailable tool executed.'
)
