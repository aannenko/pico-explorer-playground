from __future__ import annotations

import importlib
import sys

import pytest

import config_bootstrap


# Workspace fixture: writes ad-hoc ``<name>.py`` files into a tmp_path
# entry on ``sys.path`` and clears tracked names from ``sys.modules`` /
# the import cache on teardown so tests don't pollute each other.


_TEST_NAME_PREFIX = "cfg_test_"
_DEFAULTS_NAME = _TEST_NAME_PREFIX + "defaults"
_USER_NAME = _TEST_NAME_PREFIX + "user"


class _Workspace:
    def __init__(self, tmp_path) -> None:
        self.tmp_path = tmp_path
        self._path_str = str(tmp_path)
        sys.path.insert(0, self._path_str)

    def write_defaults(self, source: str, name: str = _DEFAULTS_NAME) -> str:
        (self.tmp_path / (name + ".py")).write_text(source, encoding="utf-8")
        return name

    def write_user(self, source: str, name: str = _USER_NAME) -> str:
        (self.tmp_path / (name + ".py")).write_text(source, encoding="utf-8")
        return name

    def teardown(self) -> None:
        try:
            sys.path.remove(self._path_str)
        except ValueError:
            pass
        for name in [n for n in sys.modules if n.startswith(_TEST_NAME_PREFIX)]:
            del sys.modules[name]
        importlib.invalidate_caches()


@pytest.fixture
def workspace(tmp_path):
    ws = _Workspace(tmp_path)
    try:
        yield ws
    finally:
        ws.teardown()


# ---------------------------------------------------------------------
# apply_overrides — happy paths
# ---------------------------------------------------------------------


def test_empty_user_module_falls_back_to_every_default(workspace) -> None:
    workspace.write_defaults("FOO = 1\nBAR = 'two'\nBAZ = (1, 2, 3)\n")
    workspace.write_user("")

    merged = config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)

    assert merged.FOO == 1
    assert merged.BAR == "two"
    assert merged.BAZ == (1, 2, 3)


def test_user_override_wins_over_default(workspace) -> None:
    workspace.write_defaults("FOO = 1\nBAR = 'sample'\n")
    workspace.write_user("FOO = 100\n")

    merged = config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)

    assert merged.FOO == 100
    assert merged.BAR == "sample"


def test_apply_returns_user_module_object(workspace) -> None:
    workspace.write_defaults("FOO = 1\n")
    workspace.write_user("FOO = 100\n")

    merged = config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)

    # The merged module IS the user module (in-place mutation), not a synthetic copy.
    assert merged is sys.modules[_USER_NAME]


def test_idempotent_apply_returns_same_module_without_rerunning(workspace, capsys) -> None:
    workspace.write_defaults("FOO = 1\n")
    workspace.write_user("UNKNOWN_KEY = 99\nFOO = 100\n")

    first = config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)
    capsys.readouterr()  # drain the first call's warning
    second = config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)

    assert first is second
    # Second call should be a sentinel-guarded no-op: no fresh warning emitted.
    assert "UNKNOWN_KEY" not in capsys.readouterr().out


def test_in_place_mutation_visible_to_prior_references(workspace) -> None:
    """A reference to ``user`` taken *before* the loader runs sees defaults
    materialise on the same module object after the loader runs."""
    workspace.write_defaults("FOO = 1\nBAR = 2\n")
    workspace.write_user("FOO = 100\n")

    pre_imported = __import__(_USER_NAME)
    assert not hasattr(pre_imported, "BAR")

    config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)

    assert pre_imported.BAR == 2
    assert pre_imported.FOO == 100


def test_unknown_user_key_emits_warning(workspace, capsys) -> None:
    workspace.write_defaults("FOO = 1\n")
    workspace.write_user("FOO = 100\nWIFI_SSDI = 'typo'\n")

    config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)

    out = capsys.readouterr().out
    assert "WIFI_SSDI" in out
    assert "ignoring unknown key" in out


def test_uppercase_callable_and_module_aliases_are_not_treated_as_settings(
    workspace, capsys
) -> None:
    workspace.write_defaults("FOO = 1\n")
    workspace.write_user(
        "import os as OS\n"
        "from os import getcwd as GETCWD\n"
        "FOO = 100\n"
    )

    config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)

    out = capsys.readouterr().out
    assert "OS" not in out
    assert "GETCWD" not in out


def test_const_values_round_trip_as_plain_ints(workspace) -> None:
    """``const()`` is a MicroPython compile-time hint that returns the bare
    value at runtime — the loader should treat ``const(8080)`` as ``int``."""
    workspace.write_defaults(
        "from micropython import const\n"
        "PORT = const(8080)\n"
    )
    workspace.write_user("")

    merged = config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)

    assert merged.PORT == 8080
    assert type(merged.PORT) is int


# ---------------------------------------------------------------------
# apply_overrides — error paths
# ---------------------------------------------------------------------


def test_missing_user_raises_missing_config_error(workspace) -> None:
    workspace.write_defaults("FOO = 1\n")

    with pytest.raises(config_bootstrap.MissingConfigError) as exc:
        config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)

    msg = str(exc.value)
    assert "config.py" in msg
    assert "WIFI_SSID" in msg


def test_nested_import_failure_is_not_missing_config_error(workspace) -> None:
    """Detection uses the file-existence probe rather than ``ImportError.name``
    so this works identically on CPython and MicroPython."""
    workspace.write_defaults("FOO = 1\n")
    workspace.write_user(
        "import this_module_does_not_exist_xyz\n"
        "FOO = 100\n"
    )

    with pytest.raises(RuntimeError) as exc:
        config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)

    assert not isinstance(exc.value, config_bootstrap.MissingConfigError)
    msg = str(exc.value)
    assert "this_module_does_not_exist_xyz" in msg
    assert "config.py" in msg


def test_user_syntax_error_raises_runtime_error(workspace) -> None:
    workspace.write_defaults("FOO = 1\n")
    workspace.write_user('WIFI_SSID = "unterminated\n')

    with pytest.raises(RuntimeError) as exc:
        config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)

    assert "invalid syntax" in str(exc.value)


def test_missing_defaults_module_raises_runtime_error(workspace) -> None:
    workspace.write_user("FOO = 100\n")

    with pytest.raises(RuntimeError) as exc:
        config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)

    assert not isinstance(exc.value, config_bootstrap.MissingConfigError)
    assert _DEFAULTS_NAME in str(exc.value)


def test_invalid_override_raises_invalid_config_error(workspace) -> None:
    workspace.write_defaults("BME690_TEMP_OFFSET = -1.7\n")
    workspace.write_user('BME690_TEMP_OFFSET = "minus two"\n')

    with pytest.raises(config_bootstrap.InvalidConfigError) as exc:
        config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)

    msg = str(exc.value)
    assert "BME690_TEMP_OFFSET" in msg
    assert "float" in msg
    assert "str" in msg


def test_invalid_tuple_shape_message_mentions_both_lengths(workspace) -> None:
    """Realistic regression: user kept the old 3-tuple SENSOR_*_BANDS shape."""
    workspace.write_defaults("SENSOR_TEMP_BANDS = (16, 18, 25, 29, 31)\n")
    workspace.write_user("SENSOR_TEMP_BANDS = (10, 20, 30)\n")

    with pytest.raises(config_bootstrap.InvalidConfigError) as exc:
        config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)

    msg = str(exc.value)
    assert "SENSOR_TEMP_BANDS" in msg
    assert "length 5" in msg
    assert "length 3" in msg


def test_failed_validation_does_not_set_sentinel(workspace) -> None:
    """Otherwise a subsequent retry would early-return on a bad module."""
    workspace.write_defaults("PORT = 8080\n")
    workspace.write_user('PORT = "eighty-eighty"\n')

    with pytest.raises(config_bootstrap.InvalidConfigError):
        config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)

    user_module = sys.modules[_USER_NAME]
    assert not getattr(user_module, "_CONFIG_BOOTSTRAP_MERGED", False)


def test_failed_validation_does_not_mutate_user_module(workspace) -> None:
    """Pass 1 must validate every key before pass 2 starts mutating, so a
    later mismatch can't leave the user module half-merged."""
    workspace.write_defaults("AAA = 1\nBBB = 2\nCCC = 3\n")
    # User overrides AAA correctly but breaks CCC; without two-pass, BBB
    # might get filled in before CCC's mismatch fires.
    workspace.write_user("AAA = 100\nCCC = 'not an int'\n")

    with pytest.raises(config_bootstrap.InvalidConfigError):
        config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)

    user_module = sys.modules[_USER_NAME]
    assert user_module.AAA == 100
    assert not hasattr(user_module, "BBB")  # default NOT copied in
    assert user_module.CCC == "not an int"


def test_invalid_config_message_lists_extra_mismatch_count(workspace) -> None:
    workspace.write_defaults("AAA = 1\nBBB = 2\nCCC = 3\n")
    workspace.write_user("AAA = 'x'\nBBB = 'y'\nCCC = 'z'\n")

    with pytest.raises(config_bootstrap.InvalidConfigError) as exc:
        config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)

    msg = str(exc.value)
    assert "and 2 more" in msg


def test_same_name_for_both_layers_raises_value_error(workspace) -> None:
    """Pointing both layers at the same module would collapse the merge —
    guard so a future caller can't shoot themselves in the foot silently."""
    workspace.write_defaults("FOO = 1\n")

    with pytest.raises(ValueError) as exc:
        config_bootstrap.apply_overrides(_DEFAULTS_NAME, _DEFAULTS_NAME)

    assert "must differ" in str(exc.value)


def test_user_module_file_exists_probe(workspace) -> None:
    """MP-compat probe: must succeed without relying on ``ImportError.name``."""
    probe = config_bootstrap._user_module_file_exists
    name = "cfg_test_probe_check"

    assert probe(name) is False

    workspace.write_user("", name=name)

    assert probe(name) is True


# ---------------------------------------------------------------------
# _is_compatible — structural type/shape rules
# ---------------------------------------------------------------------


def test_compat_same_scalar_types_match() -> None:
    fn = config_bootstrap._is_compatible
    assert fn(1, 2) is True
    assert fn("a", "b") is True
    assert fn(1.5, 2.5) is True
    assert fn(True, False) is True
    assert fn((1, 2), (3, 4)) is True
    assert fn([1, 2], [3, 4]) is True


def test_compat_mismatched_scalar_types_reject() -> None:
    fn = config_bootstrap._is_compatible
    assert fn(1, "a") is False
    assert fn("a", 1) is False
    assert fn((1, 2), [3, 4]) is False
    assert fn([1, 2], (3, 4)) is False


def test_compat_bool_int_strictly_rejected() -> None:
    """``bool`` is a subclass of ``int`` in Python, but ``type(True) is int``
    is False — config compatibility should also reject the swap."""
    fn = config_bootstrap._is_compatible
    assert fn(True, 1) is False
    assert fn(1, True) is False


def test_compat_int_widens_to_float() -> None:
    fn = config_bootstrap._is_compatible
    assert fn(1.0, 5) is True
    assert fn(0.0, 0) is True
    assert fn(-1.7, -2) is True


def test_compat_float_does_not_narrow_to_int() -> None:
    fn = config_bootstrap._is_compatible
    assert fn(1, 1.0) is False


def test_compat_tuple_length_mismatch_rejects() -> None:
    fn = config_bootstrap._is_compatible
    assert fn((1, 2, 3), (1, 2)) is False
    assert fn((1, 2), (1, 2, 3)) is False


def test_compat_tuple_element_type_mismatch_rejects() -> None:
    fn = config_bootstrap._is_compatible
    assert fn((1, 2, 3), (1, "two", 3)) is False


def test_compat_nested_tuple_structural_match() -> None:
    fn = config_bootstrap._is_compatible
    assert fn(((1, 2), (3, 4)), ((10, 20), (30, 40))) is True
    assert fn(((1, 2), (3, 4)), ((10, 20), (30,))) is False        # inner length mismatch
    assert fn(((1, 2), (3, 4)), ((10, 20), (30, "x"))) is False    # inner element type mismatch


def test_compat_dict_requires_every_expected_key() -> None:
    fn = config_bootstrap._is_compatible
    assert fn({"a": 1, "b": 2}, {"a": 10, "b": 20}) is True
    assert fn({"a": 1}, {"a": 10, "extra": "x"}) is True    # extras on actual allowed
    assert fn({"a": 1, "b": 2}, {"a": 10}) is False         # expected key missing
    assert fn({"a": 1}, {"a": "x"}) is False                # value type mismatch
