"""Layered (ASP.NET-style) configuration loader."""

import os
import sys


class MissingConfigError(RuntimeError):
    pass


class InvalidConfigError(RuntimeError):
    pass


_SENTINEL_ATTR = "_CONFIG_BOOTSTRAP_MERGED"

# MicroPython has no built-in ``types`` module.
_MODULE_TYPE = type(sys)


def _is_compatible(expected, actual):
    """Return True when ``actual`` matches ``expected``'s type and shape."""
    et = type(expected)
    at = type(actual)
    if et is float and at is int:
        return True
    if et is not at:
        return False
    if et is tuple:
        if len(expected) != len(actual):
            return False
        for e, a in zip(expected, actual):
            if not _is_compatible(e, a):
                return False
        return True
    if et is list:
        if not expected:
            return True
        template = expected[0]
        for a in actual:
            if not _is_compatible(template, a):
                return False
        return True
    if et is dict:
        for k, v in expected.items():
            if k not in actual or not _is_compatible(v, actual[k]):
                return False
        return True
    return True


def _is_public_setting(name, value):
    """Return True when ``(name, value)`` looks like a top-level config key:
    non-empty UPPER_SNAKE_CASE name, not callable, not a module.
    """
    if not name or name[0] == "_":
        return False
    for ch in name:
        if not (ch == "_" or ("A" <= ch <= "Z") or ("0" <= ch <= "9")):
            return False
    if callable(value) or type(value) is _MODULE_TYPE:
        return False
    return True


def _describe(value):
    name = type(value).__name__
    if name == "tuple":
        return "tuple of length {}".format(len(value))
    if name == "list":
        # List length isn't validated, so reporting one would imply it must match.
        return "list"
    return name


def _collect_settings(module):
    settings = {}
    for name in dir(module):
        if name == _SENTINEL_ATTR:
            continue
        value = getattr(module, name)
        if _is_public_setting(name, value):
            settings[name] = value
    return settings


def _user_module_file_exists(user_name):
    """Probe files because MicroPython's ``ImportError`` has no ``.name`` to
    tell a missing config from a broken import inside it.
    """
    candidates = (user_name + ".py", user_name + ".mpy")
    for entry in sys.path:
        prefix = entry if entry else "."
        for fname in candidates:
            try:
                os.stat(prefix + "/" + fname)
                return True
            except OSError:
                pass
    return False


def apply_overrides(defaults_name="config_defaults", user_name="config"):
    """Load ``user_name`` on top of ``defaults_name``, in place; the two must differ.

    Merging in place, not into a new namespace, keeps pre-existing
    ``import config`` references and ``sys.modules['config']`` on the merged
    module.

    Validation is structural only: an override must have its default's
    type, except that an ``int`` may override a ``float``; a ``bool`` is not
    an ``int`` here.  A ``tuple`` must also match its default's length and
    per-element types; a ``list`` may have any length, each element matching
    the default's first element if it has one; a ``dict`` must have every
    default key, with a compatible value, and may add keys.  Semantic
    invariants (range bounds, monotonic ordering, uniqueness) and placeholder
    credentials are not checked; an unknown public key only prints a warning.

    Returns the merged user module.  Idempotent: a second call returns
    the same module without re-validating or re-mutating.

    Raises:
      * ``MissingConfigError`` — no ``<user_name>.py`` or ``.mpy`` on ``sys.path``.
      * ``InvalidConfigError`` — an override fails validation; the user module
        is then untouched: pass 1 collects every mismatch before pass 2 mutates.
      * ``RuntimeError`` — defaults module missing, user-module syntax
        error, or a broken ``import`` inside the user file.

    Atomicity is best-effort beyond validation: a failure during pass 2
    (e.g. ``MemoryError``) leaves a partially-merged unsentinelled module
    that the next call re-completes idempotently.
    """
    if defaults_name == user_name:
        raise ValueError(
            "defaults_name and user_name must differ ({!r} given for both) "
            "— layering collapses if both layers point at the same module.".format(
                defaults_name
            )
        )

    existing = sys.modules.get(user_name)
    if existing is not None and getattr(existing, _SENTINEL_ATTR, False):
        return existing

    try:
        defaults = __import__(defaults_name)
    except ImportError as exc:
        raise RuntimeError(
            "{}.py is missing — code distribution is incomplete: {}".format(
                defaults_name, exc
            )
        )

    if not _user_module_file_exists(user_name):
        raise MissingConfigError(
            "config.py is missing.  Copy config_defaults.py to "
            "config.py and edit WIFI_SSID / WIFI_PASSWORD before "
            "rebooting."
        )

    try:
        user = __import__(user_name)
    except ImportError as exc:
        raise RuntimeError(
            "config.py exists but failed to import: {}".format(exc)
        )
    except SyntaxError as exc:
        raise RuntimeError("config.py has invalid syntax: {}".format(exc))

    defaults_settings = _collect_settings(defaults)

    mismatches = []
    for key, default_val in defaults_settings.items():
        if hasattr(user, key):
            user_val = getattr(user, key)
            if not _is_compatible(default_val, user_val):
                mismatches.append((key, default_val, user_val))

    if mismatches:
        key, default_val, user_val = mismatches[0]
        suffix = ""
        if len(mismatches) > 1:
            suffix = " (and {} more)".format(len(mismatches) - 1)
        raise InvalidConfigError(
            "config.{}: expected {} ({!r}), got {} ({!r}){}".format(
                key,
                _describe(default_val), default_val,
                _describe(user_val), user_val,
                suffix,
            )
        )

    for name in dir(user):
        if name == _SENTINEL_ATTR or name in defaults_settings:
            continue
        value = getattr(user, name)
        if _is_public_setting(name, value):
            print("config: ignoring unknown key {!r}".format(name))

    for key, default_val in defaults_settings.items():
        if not hasattr(user, key):
            setattr(user, key, default_val)

    setattr(user, _SENTINEL_ATTR, True)
    return user
