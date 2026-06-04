"""Layered (ASP.NET-style) configuration loader.

``apply_overrides()`` imports ``config_defaults.py`` (committed schema
and defaults) and ``config.py`` (git-ignored, sparse overrides), then
mutates the user module in place: each declared default the user
doesn't override is copied onto ``config``; each user override is
structurally validated against the default's type/shape and rejected
with ``InvalidConfigError`` on mismatch.  No file I/O.

The merge mutates the user module in place rather than synthesising a
new namespace, so pre-existing ``import config`` references see the
merged values and ``sys.modules['config']`` keeps pointing at the same
object.

Validation is *structural* only — same Python type, same tuple length
and per-element types, with a single widening (``int`` accepted where
the default is ``float``).  Semantic invariants (range bounds, monotonic
ordering, uniqueness) live with their consumers.  Placeholder credential
detection is intentionally out of scope: a ``config.py`` that does not
override ``WIFI_SSID`` / ``WIFI_PASSWORD`` boots with the placeholder
defaults and surfaces the problem at WiFi connect time.
"""

import os
import sys


class MissingConfigError(RuntimeError):
    """User ``config.py`` is absent from the import path."""


class InvalidConfigError(RuntimeError):
    """A user override is structurally incompatible with its default."""


_SENTINEL_ATTR = "_CONFIG_BOOTSTRAP_MERGED"

# MicroPython's slim ``types`` module may omit ``ModuleType``; ``type(sys)``
# always yields the module type on both runtimes.
_MODULE_TYPE = type(sys)


def _is_compatible(expected, actual):
    """Return True when ``actual`` matches ``expected``'s type and shape.

    Allows the single widening ``int`` -> ``float``.  Tuples/lists must
    match length and recurse per-element; dicts require every key in
    ``expected`` (extras on ``actual`` are allowed).  ``bool`` and ``int``
    are intentionally not interchangeable: ``type(True) is int`` is False.
    """
    et = type(expected)
    at = type(actual)
    if et is float and at is int:
        return True
    if et is not at:
        return False
    if et is tuple or et is list:
        if len(expected) != len(actual):
            return False
        for e, a in zip(expected, actual):
            if not _is_compatible(e, a):
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
    if name == "tuple" or name == "list":
        return "{} of length {}".format(name, len(value))
    return name


def _collect_settings(module):
    """Return ``{name: value}`` for every public UPPER_SNAKE_CASE attribute."""
    settings = {}
    for name in dir(module):
        if name == _SENTINEL_ATTR:
            continue
        value = getattr(module, name)
        if _is_public_setting(name, value):
            settings[name] = value
    return settings


def _user_module_file_exists(user_name):
    """Return True if ``<user_name>.py``/``.mpy`` exists on ``sys.path``.

    Used in place of ``ImportError.name`` inspection so the
    missing-config-vs-broken-nested-import disambiguation works on
    MicroPython (whose ``ImportError`` does not expose ``.name``).
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
    """Load ``user_name`` on top of ``defaults_name``, in place.

    Returns the merged user module.  Idempotent: a second call returns
    the same module without re-validating or re-mutating.

    Raises:
      * ``MissingConfigError`` — ``<user_name>.py``/``.mpy`` not found on
        ``sys.path``.  Message points the user at ``config_defaults.py``.
      * ``InvalidConfigError`` — at least one override fails structural
        compatibility.  When raised, the user module is guaranteed
        untouched: pass 1 collects every mismatch before pass 2 mutates.
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
        # File exists (per the probe above) so this is a body-import failure.
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

    # Warn about unknown user keys before mutation so the ``dir(user)`` walk
    # only sees keys the user actually wrote, not defaults we'll copy in.
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
