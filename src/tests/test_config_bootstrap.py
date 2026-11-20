from __future__ import annotations

import ast
import gc
import importlib
import sys
from types import ModuleType

import micropython
import picographics
import pytest

import config_bootstrap
from conftest import PICO_SRC, utc_epoch
from services.time_service import TimeService


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


@pytest.mark.parametrize(
    ("defaults_source", "defaults"),
    [
        ("FOO = 1\nBAR = 'two'\nBAZ = (1, 2, 3)\n", {"FOO": 1, "BAR": "two", "BAZ": (1, 2, 3)}),
        # const() is a MicroPython compile-time hint that returns the bare value at runtime.
        ("from micropython import const\nPORT = const(8080)\n", {"PORT": 8080}),
    ],
    ids=["plain", "const"],
)
def test_empty_user_module_falls_back_to_every_default(workspace, defaults_source: str, defaults: dict) -> None:
    workspace.write_defaults(defaults_source)
    workspace.write_user("")

    merged = config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)

    for name, value in defaults.items():
        assert getattr(merged, name) == value
        assert type(getattr(merged, name)) is type(value)


def test_merge_fills_defaults_into_the_user_module_in_place_keeping_its_overrides(workspace) -> None:
    workspace.write_defaults("FOO = 1\nBAR = 2\n")
    workspace.write_user("FOO = 100\n")
    pre_imported = __import__(_USER_NAME)
    assert not hasattr(pre_imported, "BAR")

    merged = config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)

    assert merged is pre_imported
    assert sys.modules[_USER_NAME] is pre_imported
    assert pre_imported.FOO == 100
    assert pre_imported.BAR == 2


def test_idempotent_apply_returns_same_module_without_rerunning(workspace, capsys) -> None:
    workspace.write_defaults("FOO = 1\n")
    workspace.write_user("UNKNOWN_KEY = 99\nFOO = 100\n")

    first = config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)
    capsys.readouterr()  # drain the first call's warning
    second = config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)

    assert first is second
    # Second call should be a sentinel-guarded no-op: no fresh warning emitted.
    assert "UNKNOWN_KEY" not in capsys.readouterr().out


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


@pytest.mark.parametrize(
    ("name", "is_setting"),
    [
        ("WIFI_SSID", True),
        ("BME690_READ_PERIOD_MS", True),
        ("_SENTINEL", False),
        ("const", False),
        ("Wifi_Ssid", False),
        ("", False),
    ],
)
def test_only_upper_snake_case_names_are_settings(name: str, is_setting: bool) -> None:
    assert config_bootstrap._is_public_setting(name, 1) is is_setting


class _UnindexableStr(str):
    def __getitem__(self, key):
        raise AssertionError("indexed")

    def __iter__(self):
        raise AssertionError("iterated")


def test_setting_name_check_neither_indexes_nor_iterates_the_name() -> None:
    assert config_bootstrap._is_public_setting(_UnindexableStr("WIFI_SSID"), 1) is True


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


@pytest.mark.parametrize(
    ("defaults_source", "user_source", "message_fragments"),
    [
        ("BME690_TEMP_OFFSET = -1.7\n", 'BME690_TEMP_OFFSET = "minus two"\n', ("BME690_TEMP_OFFSET", "float", "str")),
        # A user config still on the old 5-tuple SENSOR_*_BANDS shape.
        (
            "SENSOR_TEMP_BANDS = (18.0, 25.0, 29.0)\n",
            "SENSOR_TEMP_BANDS = (16, 18, 25, 29, 31)\n",
            ("SENSOR_TEMP_BANDS", "length 3", "length 5"),
        ),
    ],
    ids=["scalar-type", "tuple-length"],
)
def test_invalid_override_raises_invalid_config_error_describing_both_values(
    workspace, defaults_source: str, user_source: str, message_fragments: tuple[str, str, str]
) -> None:
    workspace.write_defaults(defaults_source)
    workspace.write_user(user_source)

    with pytest.raises(config_bootstrap.InvalidConfigError) as exc:
        config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)

    msg = str(exc.value)
    for fragment in message_fragments:
        assert fragment in msg


def test_failed_validation_does_not_mutate_user_module(workspace) -> None:
    workspace.write_defaults("AAA = 1\nBBB = 2\nCCC = 3\n")
    # User overrides AAA correctly but breaks CCC; without two-pass, BBB
    # might get filled in before CCC's mismatch fires.
    workspace.write_user("AAA = 100\nCCC = 'not an int'\n")

    with pytest.raises(config_bootstrap.InvalidConfigError):
        config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)

    user_module = sys.modules[_USER_NAME]
    assert user_module.AAA == 100
    assert not hasattr(user_module, "BBB")
    assert user_module.CCC == "not an int"
    # The merged sentinel would make a retry return the bad module unvalidated.
    assert not hasattr(user_module, "_CONFIG_BOOTSTRAP_MERGED")


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


@pytest.mark.parametrize(
    ("expected", "actual"),
    [
        (1, "a"),
        ("a", 1),
        # bool is a subclass of int, but neither may override the other.
        (True, 1),
        (1, True),
        (1, 1.0),
        pytest.param([1, 2], (1, 2), id="tuple-for-list"),
        pytest.param((1, 2), [1, 2], id="list-for-tuple"),
    ],
)
def test_compat_rejects_an_override_of_another_type(expected, actual) -> None:
    assert config_bootstrap._is_compatible(expected, actual) is False


def test_compat_int_widens_to_float() -> None:
    fn = config_bootstrap._is_compatible
    assert fn(1.0, 5) is True
    assert fn(0.0, 0) is True
    assert fn(-1.7, -2) is True


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


# ---------------------------------------------------------------------
# _is_compatible — variadic ``list`` defaults
# ---------------------------------------------------------------------


def test_compat_list_is_variadic_any_length() -> None:
    fn = config_bootstrap._is_compatible
    assert fn(["U11006Z1"], []) is True                 # empty override accepted
    assert fn(["U11006Z1"], ["a", "b", "c"]) is True    # longer override accepted
    assert fn([1], [1, 2, 3, 4, 5]) is True


def test_compat_list_elements_checked_against_first_default() -> None:
    fn = config_bootstrap._is_compatible
    assert fn([""], ["U11006Z1", "U11006Z2"]) is True
    assert fn([""], ["ok", 42]) is False                # wrong element type
    assert fn([1], [1, "x"]) is False


def test_compat_empty_list_default_accepts_any_list() -> None:
    fn = config_bootstrap._is_compatible
    assert fn([], []) is True
    assert fn([], ["anything", 1, (2, 3)]) is True


def test_compat_list_of_tuples_validates_element_shape() -> None:
    fn = config_bootstrap._is_compatible
    default = [("", (2026, 1, 1), 0, 0, 0, 1)]
    assert fn(default, [("BIO", (2026, 6, 4), 6, 0, 60, 2)]) is True
    assert fn(
        default,
        [("BIO", (2026, 6, 4), 6, 0, 60, 2), ("PLAST", (2026, 6, 5), 6, 0, 60, 2)],
    ) is True
    assert fn(default, [("BIO",)]) is False                              # wrong tuple length
    assert fn(default, [("BIO", (2026, 6, 4), 6, 0, 60, "2")]) is False  # wrong element type


def test_compat_list_element_widens_int_to_float() -> None:
    """The int->float widening propagates into a variadic list's element template."""
    fn = config_bootstrap._is_compatible
    assert fn([1.0], [1, 2, 3]) is True       # ints accepted where template is float
    assert fn([1.0], [1, 2.5, 3]) is True      # floats still fine
    assert fn([1.0], [1, "x"]) is False        # non-numeric element still rejected


def test_compat_list_nested_in_tuple_stays_variadic() -> None:
    """A ``list`` nested inside a fixed-shape ``tuple`` keeps variadic semantics."""
    fn = config_bootstrap._is_compatible
    assert fn((1, [2]), (1, [2, 3, 4])) is True   # inner list may be any length
    assert fn((1, [2]), (1, [])) is True          # inner list may be empty
    assert fn((1, [2]), (1, [2, "x"])) is False   # inner element type mismatch
    assert fn((1, [2]), (1, (2, 3))) is False     # inner tuple override of list default
    assert fn((1, [2]), (1, 2)) is False          # inner non-list override


# ---------------------------------------------------------------------
# apply_overrides — variadic ``list`` keys (end-to-end)
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("default", "override"),
    [
        (["U11006Z1"], ["U11006Z1", "U11006Z2"]),
        (["Zlicin"], []),
        (
            [("", (2026, 1, 1), 0, 0, 0, 1)],
            [("BIO", (2026, 6, 4), 6, 0, 60, 2), ("PLAST", (2026, 6, 5), 6, 0, 60, 2)],
        ),
    ],
    ids=["longer", "empty", "list-of-tuples"],
)
def test_variadic_list_override_replaces_its_default(workspace, default: list, override: list) -> None:
    workspace.write_defaults(f"SETTING = {default!r}\n")
    workspace.write_user(f"SETTING = {override!r}\n")

    cfg = config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)

    assert cfg.SETTING == override


@pytest.mark.parametrize(
    ("default", "override"),
    [
        (["U11006Z1"], ["ok", 42]),
        ([("", (2026, 1, 1), 0, 0, 0, 1)], [("BIO",)]),
        (["U11006Z1"], ("U11006Z1",)),
    ],
    ids=["wrong-element-type", "wrong-entry-shape", "tuple-override"],
)
def test_variadic_list_override_of_another_shape_raises_invalid_config_error(
    workspace, default: list, override: list | tuple
) -> None:
    workspace.write_defaults(f"SETTING = {default!r}\n")
    workspace.write_user(f"SETTING = {override!r}\n")

    with pytest.raises(config_bootstrap.InvalidConfigError):
        config_bootstrap.apply_overrides(_DEFAULTS_NAME, _USER_NAME)


@pytest.mark.parametrize(
    "utc", [utc_epoch(2026, 1, 15, 12, 0, 0), utc_epoch(2026, 7, 15, 12, 0, 0)]
)
def test_real_defaults_take_a_fractional_zone_without_dst(workspace, utc) -> None:
    workspace.write_user("TIME_ZONE_OFFSET_HOURS = 5.5\nDST_OFFSET_HOURS = 0\n")
    cfg = config_bootstrap.apply_overrides("config_defaults", _USER_NAME)

    svc = TimeService(
        tz_offset_hours=cfg.TIME_ZONE_OFFSET_HOURS,
        dst_start_rule=cfg.DST_START_RULE,
        dst_end_rule=cfg.DST_END_RULE,
        dst_offset_hours=cfg.DST_OFFSET_HOURS,
        get_time=lambda: utc,
    )
    local = svc.now()
    assert type(local) is int
    assert local == utc + 19_800
    assert svc.to_utc(local) == utc


def test_main_prefix_releases_bootstrap_before_collection_and_framebuffer_on_reentry(tmp_path, monkeypatch) -> None:
    source_path = PICO_SRC / "main.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    framebuffer_index = next(
        index for index, node in enumerate(tree.body)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "PICO_GRAPHICS" for target in node.targets)
    )
    prefix = compile(
        ast.Module(body=tree.body[:framebuffer_index + 1], type_ignores=[]), str(source_path), "exec"
    )
    defaults = ModuleType("config_defaults")
    shared = [(1, 2, 3)]
    defaults.PORT = 8080
    defaults.SHARED = shared
    user = ModuleType("config")
    user.PORT = 100
    monkeypatch.setitem(sys.modules, "config_defaults", defaults)
    monkeypatch.setitem(sys.modules, "config_bootstrap", config_bootstrap)
    monkeypatch.setitem(sys.modules, "config", user)
    (tmp_path / "config.py").write_text("PORT = 100\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    namespace = {"__name__": "__main__"}
    calls = []

    def assert_released() -> None:
        assert "config_defaults" not in sys.modules
        assert "config_bootstrap" not in sys.modules
        assert "config_bootstrap" not in namespace
        assert "config_defaults" not in namespace
        assert "sys" not in namespace
        assert sys.modules["config"] is user
        assert user.PORT == 100
        assert user.SHARED is shared

    def collect() -> None:
        assert_released()
        calls.append("collect")

    def framebuffer(*, display: int, pen_type: int) -> tuple[int, int]:
        assert_released()
        assert calls[-1] == "collect"
        calls.append("framebuffer")
        return display, pen_type

    monkeypatch.setattr(gc, "collect", collect)
    monkeypatch.setattr(micropython, "alloc_emergency_exception_buf", lambda size: None, raising=False)
    monkeypatch.setattr(picographics, "DISPLAY_PICO_EXPLORER", 17, raising=False)
    monkeypatch.setattr(picographics, "PEN_P4", 4, raising=False)
    monkeypatch.setattr(picographics, "PicoGraphics", framebuffer)

    for _ in range(2):
        exec(prefix, namespace)
        assert sys.modules["config"] is user
        assert namespace["PICO_GRAPHICS"] == (17, 4)
        assert user._CONFIG_BOOTSTRAP_MERGED is True
        assert user.SHARED is shared
    assert calls == ["collect", "framebuffer", "collect", "framebuffer"]
    assert shared == [(1, 2, 3)]
