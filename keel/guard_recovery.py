"""Typed guard incidents and lossless metadata recovery; no permission/budget grants."""
from dataclasses import asdict, dataclass
import hashlib


@dataclass(frozen=True)
class GuardIncident:
    code: str
    category: str
    protected_purpose: str
    allowed_actions: tuple
    details: dict

    def record(self):
        return asdict(self)


class GuardViolation(ValueError):
    def __init__(self, incident):
        self.incident = incident
        super().__init__(incident.code)


def reject(code, category, purpose, **details):
    raise GuardViolation(GuardIncident(code, category, purpose, (), details))


def canonicalize_candidate_names(value):
    """Names remain metadata. Only host-generated identifiers may form output paths."""
    if not isinstance(value, dict) or set(value) != {'candidates'}:
        reject('candidate_structure', 'protocol_structure', 'guidance_only_candidates')
    candidates = value['candidates']
    if not isinstance(candidates, list) or len(candidates) > 3:
        reject('candidate_count', 'resource_policy', 'bounded_comparison_work')
    normalized = []; mappings = []; seen = set()
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict) or set(candidate) != {'id', 'guidance'}:
            reject('candidate_fields', 'protected_scope', 'no_candidate_configuration_or_tool_changes')
        name, guidance = candidate['id'], candidate['guidance']
        if not isinstance(name, str) or not name or not isinstance(guidance, str) or not 1 <= len(guidance) <= 2000:
            reject('candidate_field_type_or_size', 'protocol_structure', 'valid_guidance_and_display_metadata')
        if len(name.encode('utf-8')) > 16384:
            reject('metadata_resource_capacity', 'resource_policy', 'bounded_metadata_memory')
        if name in seen:
            reject('duplicate_candidate_name', 'ambiguous_reference', 'unambiguous_candidate_identity')
        seen.add(name)
        host_id = f'candidate_{index+1}_{hashlib.sha256(name.encode()).hexdigest()[:10]}'
        normalized.append({'id': host_id, 'guidance': guidance})
        mappings.append({'id': host_id, 'display_name': name})
    incident = GuardIncident('host_candidate_identity', 'metadata_representation',
                            'safe_paths_without_rewriting_guidance', ('continue',),
                            {'mapping': mappings}).record()
    return normalized, incident


def citation_incident(value, known_ids):
    """Never guess which observation a fabricated ID was intended to reference."""
    if not isinstance(value, dict):
        return None
    ids = value.get('evidence_ids')
    if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids):
        return None
    unknown = [x for x in ids if x not in known_ids]
    if not unknown:
        return None
    return GuardIncident('unknown_observation_reference', 'evidence_integrity',
                         'only_observed_evidence_can_support_claims',
                         ('revise_citation', 'withdraw_claim', 'choose_valid_probe'),
                         {'unknown_ids': unknown, 'available_observation_ids': sorted(known_ids),
                          'instruction': 'The previous action was rejected and not executed. '
                                         'Return a new action using this schema. Do not invent an ID. '
                                         'Before any observation exists use evidence_ids=[].'})
