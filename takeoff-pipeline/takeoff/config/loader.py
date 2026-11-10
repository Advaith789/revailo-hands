"""Settings loader.

Precedence, lowest to highest:

1. ``defaults.DEFAULTS``
2. ``settings.toml`` at the repository root (or the file named by
   ``TAKEOFF_SETTINGS``)
3. environment variables of the form ``TAKEOFF_<SECTION>__<KEY>``

The merged result is exposed as the module-level ``settings`` object and is
read once at import time, which mirrors how the Lambda runtime caches SSM
parameters for the life of the container.
"""

import copy
import os
from pathlib import Path

from . import toml_lite
from .defaults import DEFAULTS

ENV_PREFIX = "TAKEOFF_"
ENV_FILE_VAR = "TAKEOFF_SETTINGS"


class Section(object):
    """Read-only view of one settings section with attribute access."""

    def __init__(self, name, values):
        self._name = name
        self._values = dict(values)

    def get(self, key, default=None):
        return self._values.get(key, default)

    def __getattr__(self, key):
        if key.startswith("_"):
            raise AttributeError(key)
        try:
            return self._values[key]
        except KeyError:
            raise AttributeError("settings.{}.{} is not set".format(self._name, key))

    def __contains__(self, key):
        return key in self._values

    def as_dict(self):
        return dict(self._values)

    def __repr__(self):
        return "Section({!r}, {!r})".format(self._name, self._values)


class Settings(object):
    def __init__(self, data, source):
        self._data = data
        self.source = source

    def section(self, name):
        return Section(name, self._data.get(name, {}))

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self.section(name)

    def as_dict(self):
        return copy.deepcopy(self._data)


def _deep_merge(base, overlay):
    out = copy.deepcopy(base)
    for section, values in overlay.items():
        if not isinstance(values, dict):
            continue
        out.setdefault(section, {}).update(values)
    return out


def _coerce_env(raw):
    low = raw.strip().lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def _env_overrides(environ):
    out = {}
    for key, value in environ.items():
        if not key.startswith(ENV_PREFIX) or key == ENV_FILE_VAR:
            continue
        rest = key[len(ENV_PREFIX):]
        if "__" not in rest:
            continue
        section, name = rest.split("__", 1)
        out.setdefault(section.lower(), {})[name.lower()] = _coerce_env(value)
    return out


def default_settings_path():
    return Path(__file__).resolve().parents[2] / "settings.toml"


def load(path=None, environ=None):
    environ = os.environ if environ is None else environ
    if path is None:
        path = environ.get(ENV_FILE_VAR) or default_settings_path()
    path = Path(path)
    data = copy.deepcopy(DEFAULTS)
    source = "defaults"
    if path.exists():
        data = _deep_merge(data, toml_lite.load(path))
        source = str(path)
    data = _deep_merge(data, _env_overrides(environ))
    return Settings(data, source)


settings = load()
