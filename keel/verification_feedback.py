"""Bounded failure-first feedback; full reports remain authoritative artifacts."""
import re


def failure_feedback(status, observed):
    observed = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', observed)
    counts, failed = {}, []
    for group, values in (status or {}).items():
        counts[group] = {key: len(ids) for key, ids in values.items()}
        failed.extend({'group': group, 'test': str(test)[:300]} for test in values.get('failure', []))
    # Pytest prints failure blocks before potentially thousands of passing IDs.
    sections = re.split(r'(?m)^(?:_{3,}[^\n]*_{3,}|={3,}[^\n]*={3,})[ \t]*$', observed)
    excerpts = []
    for section in sections:
        if re.search(r'(?m)^PASSED ', section) and not re.search(r'(?m)^E\s|^Traceback', section):
            continue
        if re.search(r'(?m)^E\s|Traceback|(?:Error|Exception):', section):
            # Keep assertion/exception lines even when a block contains a long source listing.
            lines = section.splitlines()
            errors = [i for i, line in enumerate(lines) if re.match(r'^E\s', line)]
            excerpt = '\n'.join(lines[max(0, errors[0]-5):errors[-1]+2]) if errors else section
            excerpts.append(excerpt[-1000:])
    return {'test_counts': counts, 'failed_tests': failed[:10],
            'omitted_failed_tests': max(0, len(failed)-10),
            'failure_excerpts': excerpts[:4], 'omitted_failure_excerpts': max(0, len(excerpts)-4),
            'observed_test_output_tail': observed[-1000:]}
