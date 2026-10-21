"""Bounded failure-first feedback; full reports remain authoritative artifacts."""
import re
import hashlib
import json


def bounded_failure_locations(rows):
    """Normalize navigation evidence; log paths never grant read/write rights."""
    result = []
    for row in rows[:4] if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        entry = {key: str(row.get(key) or '')[:limit] for key, limit in (
            ('section', 300), ('source_path', 300), ('statement', 300), ('context', 800))}
        line = row.get('line')
        entry['line'] = line if type(line) is int and line > 0 else None
        entry['status'] = ('observed' if row.get('status') == 'observed' and
                           entry['source_path'] and entry['line'] and entry['statement'] else 'not_established')
        omitted = row.get('omitted_context_characters', 0)
        entry['omitted_context_characters'] = (omitted if type(omitted) is int and omitted >= 0 else 0)
        entry['omitted_context_characters'] += max(0, len(str(row.get('context') or ''))-800)
        entry['scope'] = 'Observed pytest call marker/frame only; test phase and causality require interpretation.'
        result.append(entry)
    return result


def pytest_call_location(section, title):
    lines = section.splitlines()
    marker = next((i for i, text in enumerate(lines) if re.match(r'^>\s+\S', text)), None)
    row = {'section': title, 'status': 'not_established'}
    if marker is None:
        return row
    row['statement'] = lines[marker][1:].strip()
    # The first marked statement in the failure block is the outer call;
    # later markers may belong to internal raising frames.
    for text in lines[marker+1:marker+21]:
        if re.match(r'^>\s+\S', text):
            break
        match = re.match(r'^(.+\.py):(\d+):(?:\s|$)', text)
        if match:
            row.update(source_path=match[1], line=int(match[2]), status='observed')
            break
    context = '\n'.join(lines[max(0, marker-4):marker+4])
    row.update(context=context[:800], omitted_context_characters=max(0, len(context)-800))
    return row


def failure_feedback(status, observed):
    observed = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', observed)
    counts, failed = {}, []
    for group, values in (status or {}).items():
        counts[group] = {key: len(ids) for key, ids in values.items()}
        failed.extend({'group': group, 'test': str(test)[:300]} for test in values.get('failure', []))
    # Pytest prints failure blocks before potentially thousands of passing IDs.
    parts = re.split(r'(?m)^((?:_{3,}[^\n]*_{3,}|={3,}[^\n]*={3,}))[ \t\r]*$', observed)
    excerpts, locations = [], []
    for index in range(0, len(parts), 2):
        section = parts[index]
        title = parts[index-1].strip('_= \t\r') if index else ''
        if re.search(r'(?m)^PASSED ', section) and not re.search(r'(?m)^E\s|^Traceback', section):
            continue
        if re.search(r'(?m)^E\s|Traceback|(?:Error|Exception):', section):
            locations.append(pytest_call_location(section, title))
            # Keep assertion/exception lines even when a block contains a long source listing.
            lines = section.splitlines()
            errors = [i for i, line in enumerate(lines) if re.match(r'^E\s', line)]
            excerpt = '\n'.join(lines[max(0, errors[0]-5):errors[-1]+2]) if errors else section
            excerpts.append(excerpt[-1000:])
    universe = {group: sorted(set(str(test) for ids in values.values() for test in ids))
                for group, values in (status or {}).items()}
    return {'test_universe_sha256': hashlib.sha256(json.dumps(universe, sort_keys=True).encode()).hexdigest(),
            'test_counts': counts, 'failed_tests': failed[:10],
            'omitted_failed_tests': max(0, len(failed)-10),
            'failure_excerpts': excerpts[:4], 'omitted_failure_excerpts': max(0, len(excerpts)-4),
            'failure_locations': bounded_failure_locations(locations),
            'omitted_failure_locations': max(0, len(locations)-4),
            'observed_test_output_tail': observed[-1000:]}
