from __future__ import annotations

import config_bootstrap


def _read(path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_creates_target_when_missing(tmp_path) -> None:
    sample = tmp_path / "config.sample.py"
    _write(sample, "FOO = 1\nBAR = 2\n")
    target = tmp_path / "config.py"

    state = config_bootstrap.ensure_config(str(sample), str(target))

    assert state == config_bootstrap.CONFIG_CREATED
    assert target.exists()
    # Fresh-copy is byte-for-byte identical to the sample.
    assert _read(target) == "FOO = 1\nBAR = 2\n"


def test_no_op_when_target_has_every_key(tmp_path) -> None:
    sample = tmp_path / "config.sample.py"
    _write(sample, "FOO = 1\nBAR = 2\n")
    target = tmp_path / "config.py"
    original = "BAR = 100\nFOO = 200\n"  # user values, order shuffled
    _write(target, original)

    state = config_bootstrap.ensure_config(str(sample), str(target))

    assert state == config_bootstrap.CONFIG_OK
    # Target is untouched, even byte-for-byte (no banner / no rewrites).
    assert _read(target) == original


def test_appends_missing_keys_with_preceding_comments(tmp_path) -> None:
    sample = tmp_path / "config.sample.py"
    _write(
        sample,
        (
            "FOO = 1\n"
            "\n"
            "# Bar is essential — set to 42 for the universe.\n"
            "BAR = 2\n"
            "\n"
            "# Group of related keys spanning\n"
            "# two comment lines to explain them.\n"
            "BAZ = 3\n"
            "QUX = 4\n"
        ),
    )
    target = tmp_path / "config.py"
    _write(target, "FOO = 100\nBAR = 200\n")

    state = config_bootstrap.ensure_config(str(sample), str(target))

    assert state == config_bootstrap.CONFIG_PATCHED
    text = _read(target)
    # Existing user values preserved verbatim.
    assert text.startswith("FOO = 100\nBAR = 200\n")
    # Banner separates user content from the bootstrapped block.
    assert "Added by config_bootstrap" in text
    # Both missing keys are present after the banner.
    banner_idx = text.index("Added by config_bootstrap")
    assert "BAZ = 3" in text[banner_idx:]
    assert "QUX = 4" in text[banner_idx:]
    # Preceding-comment block followed BAZ (the first key after the comments)
    # so the explanation travels with the value.
    baz_idx = text.index("BAZ = 3")
    assert "# Group of related keys spanning" in text[:baz_idx]
    assert "# two comment lines to explain them." in text[:baz_idx]


def test_preserves_user_values_for_existing_keys(tmp_path) -> None:
    """Bootstrap only appends; it must never rewrite existing keys."""
    sample = tmp_path / "config.sample.py"
    _write(
        sample,
        'WIFI_SSID = "SampleSSID"\n'
        'WIFI_PASSWORD = "SamplePassword"\n'
        'TIMEOUT = 30\n',
    )
    target = tmp_path / "config.py"
    _write(
        target,
        'WIFI_SSID = "MyHomeNetwork"\n'
        'WIFI_PASSWORD = "supersecret"\n',
    )

    state = config_bootstrap.ensure_config(str(sample), str(target))

    assert state == config_bootstrap.CONFIG_PATCHED
    text = _read(target)
    assert 'WIFI_SSID = "MyHomeNetwork"' in text
    assert 'WIFI_PASSWORD = "supersecret"' in text
    assert "TIMEOUT = 30" in text
    # And the sample's default for WIFI_SSID is NOT present.
    assert 'WIFI_SSID = "SampleSSID"' not in text


def test_ignores_indented_assignments_and_equality_checks(tmp_path) -> None:
    """The parser only treats top-level UPPER_SNAKE_CASE = … as a key."""
    sample = tmp_path / "config.sample.py"
    _write(
        sample,
        (
            "FOO = 1\n"
            "if FOO == 1:\n"  # equality, not assignment
            "    BAR = 2\n"  # indented — not top-level
            "BAZ = 3\n"
        ),
    )
    target = tmp_path / "config.py"
    # Non-empty target with a real key so the empty-target shortcut doesn't
    # fire — this test is about parser behavior, not the missing-file path.
    _write(target, "FOO = 100\n")

    state = config_bootstrap.ensure_config(str(sample), str(target))

    assert state == config_bootstrap.CONFIG_PATCHED
    text = _read(target)
    assert "FOO = 100" in text  # user value preserved
    assert "BAZ = 3" in text
    # BAR is indented in the sample → parser treats it as not an assignment,
    # so it is NOT considered "missing" and never gets copied.
    assert "BAR = 2" not in text


def test_const_and_tuple_values_round_trip(tmp_path) -> None:
    """Right-hand sides are copied verbatim — const(...) and tuples work."""
    sample = tmp_path / "config.sample.py"
    _write(
        sample,
        (
            "from micropython import const\n"
            "\n"
            "TIME_ZONE_OFFSET = const(1)\n"
            "DST_START = (3, -1, 6, 2)\n"
            'FONT = "bitmap8"\n'
        ),
    )
    target = tmp_path / "config.py"
    _write(target, "DST_START = (4, -1, 6, 2)\n")  # user customized DST

    state = config_bootstrap.ensure_config(str(sample), str(target))

    assert state == config_bootstrap.CONFIG_PATCHED
    text = _read(target)
    assert "TIME_ZONE_OFFSET = const(1)" in text
    assert 'FONT = "bitmap8"' in text
    # User's DST_START is the one that survives.
    assert "DST_START = (4, -1, 6, 2)" in text
    assert "DST_START = (3, -1, 6, 2)" not in text


def test_returns_created_state_when_sample_is_empty(tmp_path) -> None:
    """Even an empty sample is enough to materialize an empty config.py."""
    sample = tmp_path / "config.sample.py"
    _write(sample, "")
    target = tmp_path / "config.py"

    state = config_bootstrap.ensure_config(str(sample), str(target))

    assert state == config_bootstrap.CONFIG_CREATED
    assert target.exists()
    assert _read(target) == ""


def test_no_writes_when_target_has_every_key(tmp_path, monkeypatch) -> None:
    """Performance/flash-wear guard: a fully-synced config must not be rewritten."""
    sample = tmp_path / "config.sample.py"
    _write(sample, "FOO = 1\nBAR = 2\n")
    target = tmp_path / "config.py"
    _write(target, "FOO = 9\nBAR = 9\n")

    # Wrap builtins.open so we can detect any open(..., "w" | "a") call on target.
    write_opens: list[str] = []
    real_open = open

    def spy_open(path, mode="r", *args, **kwargs):
        if str(path) == str(target) and ("w" in mode or "a" in mode):
            write_opens.append(mode)
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", spy_open)
    state = config_bootstrap.ensure_config(str(sample), str(target))

    assert state == config_bootstrap.CONFIG_OK
    assert write_opens == [], f"unexpected writes to target: {write_opens}"


def test_multiline_tuple_value_is_preserved_when_appended(tmp_path) -> None:
    """A multi-line RHS in the sample must be copied verbatim when patched."""
    sample = tmp_path / "config.sample.py"
    _write(
        sample,
        (
            "FOO = 1\n"
            "\n"
            "# A multi-line config value spanning several lines.\n"
            "MULTI = (\n"
            "    (3, -1, 6, 2),\n"
            "    (10, -1, 6, 3),\n"
            ")\n"
            "AFTER = 99\n"
        ),
    )
    target = tmp_path / "config.py"
    _write(target, "FOO = 100\n")

    state = config_bootstrap.ensure_config(str(sample), str(target))

    assert state == config_bootstrap.CONFIG_PATCHED
    text = _read(target)
    # Every continuation line of MULTI must have made it through.
    assert "MULTI = (\n    (3, -1, 6, 2),\n    (10, -1, 6, 3),\n)\n" in text
    assert "AFTER = 99" in text
    # The appended block must parse — exec it to confirm no SyntaxError.
    exec_ns: dict = {}
    exec(text, exec_ns)
    assert exec_ns["MULTI"] == ((3, -1, 6, 2), (10, -1, 6, 3))
    assert exec_ns["AFTER"] == 99


def test_empty_target_is_overwritten_from_sample(tmp_path) -> None:
    """A target file with no recognised keys is treated as missing.

    Otherwise we'd risk appending blocks that need an import (e.g.
    ``const()``) into a file that doesn't declare it.
    """
    sample = tmp_path / "config.sample.py"
    sample_text = (
        "from micropython import const\n"
        "\n"
        "FONT_HEIGHT = const(8)\n"
        'WIFI_SSID = "SampleSSID"\n'
    )
    _write(sample, sample_text)
    target = tmp_path / "config.py"
    _write(target, "# user notes but no assignments\n")

    state = config_bootstrap.ensure_config(str(sample), str(target))

    assert state == config_bootstrap.CONFIG_CREATED
    assert _read(target) == sample_text


def test_missing_imports_are_forwarded_when_patching(tmp_path) -> None:
    """A partial user config lacking ``from micropython import const`` gets
    the import auto-added when the sample's missing blocks use ``const(...)``,
    so the patched file remains importable.
    """
    sample = tmp_path / "config.sample.py"
    _write(
        sample,
        (
            "from micropython import const\n"
            "\n"
            "TIMEOUT = const(30)\n"
            'WIFI_SSID = "Sample"\n'
        ),
    )
    target = tmp_path / "config.py"
    _write(target, 'WIFI_SSID = "Mine"\n')

    state = config_bootstrap.ensure_config(str(sample), str(target))

    assert state == config_bootstrap.CONFIG_PATCHED
    text = _read(target)
    assert 'WIFI_SSID = "Mine"' in text
    assert text.count("from micropython import const") == 1
    exec_ns: dict = {}
    exec(text, exec_ns)
    assert exec_ns["TIMEOUT"] == 30
    assert exec_ns["WIFI_SSID"] == "Mine"


def test_existing_imports_not_duplicated_when_patching(tmp_path) -> None:
    """An import the user already declared must not be appended again."""
    sample = tmp_path / "config.sample.py"
    _write(
        sample,
        (
            "from micropython import const\n"
            "\n"
            "TIMEOUT = const(30)\n"
            'WIFI_SSID = "Sample"\n'
        ),
    )
    target = tmp_path / "config.py"
    _write(
        target,
        (
            "from micropython import const\n"
            'WIFI_SSID = "Mine"\n'
        ),
    )

    state = config_bootstrap.ensure_config(str(sample), str(target))

    assert state == config_bootstrap.CONFIG_PATCHED
    text = _read(target)
    assert text.count("from micropython import const") == 1


def test_imports_not_forwarded_when_target_has_every_key(tmp_path) -> None:
    """CONFIG_OK path stays untouched even if sample declares an import
    the user's file lacks — we don't rewrite a fully-keyed config.
    """
    sample = tmp_path / "config.sample.py"
    _write(
        sample,
        (
            "from micropython import const\n"
            "\n"
            'WIFI_SSID = "Sample"\n'
        ),
    )
    target = tmp_path / "config.py"
    original = 'WIFI_SSID = "Mine"\n'
    _write(target, original)

    state = config_bootstrap.ensure_config(str(sample), str(target))

    assert state == config_bootstrap.CONFIG_OK
    assert _read(target) == original
