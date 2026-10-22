"""Source display equivalence, without changing source bytes or quote contents."""

POLICY = 'source-crlf-equivalence-v1'


def display_text(text):
    return text.replace('\r\n', '\n')


def matching_mode(quote, source):
    if not isinstance(quote, str) or not quote.strip() or not isinstance(source, str):
        return None
    if quote in source:
        return 'exact'
    if display_text(quote) in display_text(source):
        return 'line_endings_only'
    return None
