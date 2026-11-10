"""Minimal TOML reader.

Supports the subset settings.toml uses: ``[section]`` headers, ``key = value``
pairs, ``#`` comments, and bool / int / float / quoted-string values. Nested
tables, arrays and multi-line strings are not supported and raise.
"""

import re

_SECTION = re.compile(r"^\[([A-Za-z0-9_.\-]+)\]\s*$")
_PAIR = re.compile(r"^([A-Za-z0-9_\-]+)\s*=\s*(.+?)\s*$")


class TomlError(ValueError):
    pass


def _strip_comment(line):
    out = []
    in_str = False
    for ch in line:
        if ch == '"':
            in_str = not in_str
        if ch == "#" and not in_str:
            break
        out.append(ch)
    return "".join(out).strip()


def _coerce(raw, lineno):
    if raw == "true":
        return True
    if raw == "false":
        return False
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        return raw[1:-1]
    if re.fullmatch(r"[+-]?\d+", raw):
        return int(raw)
    if re.fullmatch(r"[+-]?(\d+\.\d*|\d*\.\d+|\d+)([eE][+-]?\d+)?", raw):
        return float(raw)
    raise TomlError("line {}: cannot parse value {!r}".format(lineno, raw))


def loads(text):
    data = {}
    current = None
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw_line)
        if not line:
            continue
        m = _SECTION.match(line)
        if m:
            current = m.group(1)
            data.setdefault(current, {})
            continue
        m = _PAIR.match(line)
        if not m:
            raise TomlError("line {}: unparseable {!r}".format(lineno, raw_line))
        key, value = m.group(1), _coerce(m.group(2), lineno)
        if current is None:
            data.setdefault("", {})[key] = value
        else:
            data[current][key] = value
    return data


def load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return loads(fh.read())
