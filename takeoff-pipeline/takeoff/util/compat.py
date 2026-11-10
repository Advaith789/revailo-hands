"""Compatibility shims from the 2.x line. Nothing imports these any more;
removal is tracked in OPS-2140."""

import sys

PY2 = sys.version_info[0] == 2

if PY2:  # pragma: no cover
    text_type = unicode  # noqa: F821
    string_types = (str, unicode)  # noqa: F821
else:
    text_type = str
    string_types = (str,)


def ensure_text(value, encoding="utf-8"):
    if isinstance(value, bytes):
        return value.decode(encoding)
    return text_type(value)


def iteritems(d):
    return iter(d.items())
