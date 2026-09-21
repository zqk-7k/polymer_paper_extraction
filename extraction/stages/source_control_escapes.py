"""Compare alternate escaped spellings of OCR control artifacts, not glyphs."""
import re

_TOKEN = re.compile(r'\\u00([0-9a-fA-F]{2})|\\x([0-9a-fA-F]{2})|([\x00-\x08\x0b\x0c\x0e-\x1f\x7f])')


def _code(match):
    return ord(match[3]) if match[3] else int(match[1] or match[2], 16)


def decode_control_escapes(text: str) -> str:
    def replace(match):
        code = _code(match)
        return chr(code) if code < 32 or code == 127 else match[0]
    return _TOKEN.sub(replace, text)


def restore_source_control_spellings(text: str, source: str) -> str:
    """Retain the source's escaped notation in the published quote/unit."""
    spellings = {}
    for match in _TOKEN.finditer(source):
        code = _code(match)
        if code < 32 or code == 127:
            spellings.setdefault(code, match[0])
    return _TOKEN.sub(lambda m: spellings.get(_code(m), m[0]), text)
