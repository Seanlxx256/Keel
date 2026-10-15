"""Conservative metadata evidence extraction, not proof of a dependency failure."""
import re


def extract(title, body, dependency):
    if not isinstance(dependency, str) or not re.fullmatch('[a-z][a-z0-9_-]{0,49}', dependency):
        raise ValueError('Explicit dependency package name required')
    # Require a version near the named dependency on the same metadata line.
    pattern = re.compile(r'\b'+re.escape(dependency)+r'\b(?:\[[a-z0-9_, -]+\])?[`*\s]*'
        r'(?:(?:version|to)\s+)?[<>=!~^]*\s*v?(\d+\.\d+(?:\.\d+)?)\b', re.I)
    for field, text in (('title', title), ('body', body or '')):
        if not isinstance(text, str):
            continue
        for line in text.splitlines():
            match = pattern.search(line)
            if match:
                start = max(0, match.start()-40)
                return {'dependency': dependency, 'mentioned_version': match.group(1), 'field': field,
                    'excerpt': line[start:min(len(line), start+240)], 'method': 'dependency-near-version-v1',
                    'verified_transition': False}
    return None
