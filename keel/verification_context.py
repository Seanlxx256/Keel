"""Bounded, provenance-labelled test excerpts from actual pytest output."""
import hashlib
import re


def executed_test_patch_context(raw, test_id, *, max_bytes=16384):
    """Read, never execute, the test patch embedded in an archived harness script."""
    path, symbol = test_id.split('::', 1)
    symbol = symbol.split('::')[-1].split('[', 1)[0]
    if not path.endswith('.py') or not symbol.isidentifier():
        raise ValueError('Python test node id required')
    text = raw.decode('utf-8')
    found = []
    for match in re.finditer(r"^git apply[^\n]*<<'([^']+)'\r?$", text, re.M):
        end = re.search(r'^' + re.escape(match[1]) + r'\r?$', text[match.end():], re.M)
        if not end:
            continue
        patch = text[match.end():match.end()+end.start()]
        for section in re.split(r'(?=^diff --git )', patch, flags=re.M):
            if ('+++ b/'+path) not in section.splitlines():
                continue
            if not re.search(r'^[+ ](?:\s*)(?:async )?def '+re.escape(symbol)+r'\(', section, re.M):
                continue
            found.append(section.strip())
    if len(found) != 1 or len(found[0].encode()) > max_bytes:
        raise ValueError('Expected one bounded executed test patch section')
    return {'test_id':test_id, 'path':path, 'text':found[0],
            'raw_eval_sha256':hashlib.sha256(raw).hexdigest(), 'complete_test_body':False,
            'scope':'Archived harness test-patch section, not a complete module or reference solution. '
                    'Read-only diagnostic contract; no shell execution or source modification.'}


def failure_test_context(raw, test_id, *, max_bytes=16384):
    if not isinstance(raw, bytes) or '::' not in test_id:
        raise ValueError('Raw test output and node id required')
    path, symbol = test_id.split('::', 1)
    symbol = symbol.split('::')[-1].split('[', 1)[0]
    if not path.endswith('.py') or not symbol.isidentifier():
        raise ValueError('Python test node id required')
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', raw.decode('utf-8', errors='replace'))
    lines = text.splitlines()
    definition = re.compile(r'^\s+(?:async )?def ' + re.escape(symbol) + r'\(')
    location = re.compile(r'^' + re.escape(path) + r':(\d+):')
    for start, line in enumerate(lines):
        if not definition.search(line):
            continue
        for end in range(start+1, min(len(lines), start+160)):
            match = location.search(lines[end])
            if match:
                excerpt = '\n'.join(lines[start:end]).rstrip()
                if len(excerpt.encode()) > max_bytes:
                    raise ValueError('Failed test excerpt exceeds context limit')
                return {'test_id':test_id, 'path':path, 'failure_line':int(match[1]),
                        'raw_output_sha256':hashlib.sha256(raw).hexdigest(),
                        'text':excerpt, 'complete_test_body':False,
                        'scope':'Observed pytest failure excerpt only; may stop at first failing assertion. '
                                'Not a complete test source file, executable fixture, or writable repair target.'}
    raise ValueError('Matching failed test excerpt not present in actual output')
