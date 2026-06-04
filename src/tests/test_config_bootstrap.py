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


# ─────────────────────────────────────────────────────────────────────
# Schema-version reconciliation: # bootstrap: schema v<N>
# ─────────────────────────────────────────────────────────────────────


def test_schema_bump_replaces_stale_target_block(tmp_path) -> None:
    """Sample marker > target marker (or missing) → block is rewritten verbatim."""
    sample = tmp_path / "config.sample.py"
    _write(
        sample,
        (
            "FOO = 1\n"
            "\n"
            "# bootstrap: schema v2\n"
            "# Bands now use 5 ascending edges.\n"
            "BANDS = (10, 20, 30, 40, 50)\n"
            "\n"
            "AFTER = 99\n"
        ),
    )
    target = tmp_path / "config.py"
    _write(
        target,
        (
            "FOO = 1\n"
            "BANDS = (20, 30, 40)\n"  # old shape, no marker
            "AFTER = 99\n"
        ),
    )

    state = config_bootstrap.ensure_config(str(sample), str(target))

    assert state == config_bootstrap.CONFIG_RESYNCED
    text = _read(target)
    # New block (with marker) is present.
    assert "# bootstrap: schema v2" in text
    assert "BANDS = (10, 20, 30, 40, 50)" in text
    # Old block is gone.
    assert "BANDS = (20, 30, 40)" not in text
    # Surrounding unrelated keys untouched.
    assert "FOO = 1" in text
    assert "AFTER = 99" in text


def test_schema_marker_no_op_when_versions_match(tmp_path) -> None:
    """Sample.version == target.version → no replacement."""
    sample = tmp_path / "config.sample.py"
    _write(
        sample,
        (
            "# bootstrap: schema v2\n"
            "BANDS = (10, 20, 30, 40, 50)\n"
        ),
    )
    target = tmp_path / "config.py"
    # User has their own 5-edge values at v2 — should NOT be replaced.
    original = (
        "# bootstrap: schema v2\n"
        "BANDS = (15, 25, 35, 45, 55)\n"
    )
    _write(target, original)

    state = config_bootstrap.ensure_config(str(sample), str(target))

    assert state == config_bootstrap.CONFIG_OK
    assert _read(target) == original


def test_schema_marker_replaces_when_target_lacks_marker(tmp_path) -> None:
    """Target's missing marker is treated as v0 → any sample marker triggers resync."""
    sample = tmp_path / "config.sample.py"
    _write(
        sample,
        (
            "# bootstrap: schema v1\n"
            "BANDS = (10, 20, 30, 40, 50)\n"
        ),
    )
    target = tmp_path / "config.py"
    _write(target, "BANDS = (1, 2, 3, 4, 5)\n")  # no marker → v0

    state = config_bootstrap.ensure_config(str(sample), str(target))

    assert state == config_bootstrap.CONFIG_RESYNCED
    text = _read(target)
    assert "# bootstrap: schema v1" in text
    assert "BANDS = (10, 20, 30, 40, 50)" in text


def test_schema_marker_no_op_without_markers(tmp_path) -> None:
    """If neither side has the marker, the existing PATCHED/OK paths still rule."""
    sample = tmp_path / "config.sample.py"
    _write(sample, "FOO = 1\nBAR = 2\n")
    target = tmp_path / "config.py"
    original = "FOO = 100\n"
    _write(target, original)

    state = config_bootstrap.ensure_config(str(sample), str(target))

    assert state == config_bootstrap.CONFIG_PATCHED
    text = _read(target)
    assert "FOO = 100" in text
    assert "BAR = 2" in text


def test_schema_resync_takes_precedence_over_patched(tmp_path) -> None:
    """If both missing keys and stale-schema keys are present, RESYNCED wins."""
    sample = tmp_path / "config.sample.py"
    _write(
        sample,
        (
            "# bootstrap: schema v2\n"
            "BANDS = (10, 20, 30, 40, 50)\n"
            "\n"
            "NEW_KEY = 42\n"
        ),
    )
    target = tmp_path / "config.py"
    _write(target, "BANDS = (1, 2, 3)\n")  # stale + missing NEW_KEY

    state = config_bootstrap.ensure_config(str(sample), str(target))

    assert state == config_bootstrap.CONFIG_RESYNCED
    text = _read(target)
    assert "BANDS = (10, 20, 30, 40, 50)" in text
    # NEW_KEY was appended (PATCHED logic) AND BANDS was rewritten (RESYNCED).
    assert "NEW_KEY = 42" in text
    assert "BANDS = (1, 2, 3)" not in text


def test_schema_resync_preserves_multiline_block(tmp_path) -> None:
    """A multi-line replacement block is emitted verbatim, brackets balanced."""
    sample = tmp_path / "config.sample.py"
    _write(
        sample,
        (
            "# bootstrap: schema v2\n"
            "# A multi-line replacement spanning several lines.\n"
            "DST = (\n"
            "    (3, -1, 6, 2),\n"
            "    (10, -1, 6, 3),\n"
            ")\n"
        ),
    )
    target = tmp_path / "config.py"
    _write(target, "DST = (1, 2, 3, 4)\n")

    state = config_bootstrap.ensure_config(str(sample), str(target))

    assert state == config_bootstrap.CONFIG_RESYNCED
    text = _read(target)
    assert "# bootstrap: schema v2" in text
    assert "DST = (\n    (3, -1, 6, 2),\n    (10, -1, 6, 3),\n)\n" in text
    # File still parses.
    exec_ns: dict = {}
    exec(text, exec_ns)
    assert exec_ns["DST"] == ((3, -1, 6, 2), (10, -1, 6, 3))


def test_schema_resync_drops_original_target_block_header(tmp_path) -> None:
    """The target's preceding comment header for a replaced block is dropped
    (so user-added comments on the stale block don't survive). The
    replacement carries the sample's header.
    """
    sample = tmp_path / "config.sample.py"
    _write(
        sample,
        (
            "# bootstrap: schema v2\n"
            "# Sample explanation for the new shape.\n"
            "BANDS = (10, 20, 30, 40, 50)\n"
        ),
    )
    target = tmp_path / "config.py"
    _write(
        target,
        (
            "# My old comment for the old shape.\n"
            "BANDS = (20, 30, 40)\n"
        ),
    )

    state = config_bootstrap.ensure_config(str(sample), str(target))

    assert state == config_bootstrap.CONFIG_RESYNCED
    text = _read(target)
    assert "# My old comment for the old shape." not in text
    assert "# Sample explanation for the new shape." in text
    assert "BANDS = (10, 20, 30, 40, 50)" in text


def test_schema_resync_replaces_only_marked_keys(tmp_path) -> None:
    """Unrelated user-customized keys (no marker on either side) survive untouched."""
    sample = tmp_path / "config.sample.py"
    _write(
        sample,
        (
            "WIFI_SSID = \"SampleSSID\"\n"
            "\n"
            "# bootstrap: schema v2\n"
            "BANDS = (10, 20, 30, 40, 50)\n"
        ),
    )
    target = tmp_path / "config.py"
    _write(
        target,
        (
            "WIFI_SSID = \"MyNetwork\"\n"
            "BANDS = (1, 2, 3)\n"
        ),
    )

    state = config_bootstrap.ensure_config(str(sample), str(target))

    assert state == config_bootstrap.CONFIG_RESYNCED
    text = _read(target)
    # User WIFI_SSID preserved (no marker on either side).
    assert 'WIFI_SSID = "MyNetwork"' in text
    assert 'WIFI_SSID = "SampleSSID"' not in text
    # BANDS resynced.
    assert "BANDS = (10, 20, 30, 40, 50)" in text


def test_schema_marker_only_recognised_in_comment_lines(tmp_path) -> None:
    """A 'bootstrap: schema v…' substring in a string literal must NOT trigger."""
    sample = tmp_path / "config.sample.py"
    _write(
        sample,
        (
            "# bootstrap: schema v2\n"
            "BANDS = (10, 20, 30, 40, 50)\n"
        ),
    )
    target = tmp_path / "config.py"
    # The string literal contains the marker but it isn't in a comment line.
    _write(
        target,
        (
            'NOTE = "bootstrap: schema v9 (just a string)"\n'
            "BANDS = (1, 2, 3)\n"
        ),
    )

    state = config_bootstrap.ensure_config(str(sample), str(target))

    # The NOTE block has no real marker → BANDS still resyncs because target's
    # BANDS block also has no real marker (target version = v0 < sample v2).
    assert state == config_bootstrap.CONFIG_RESYNCED
    text = _read(target)
    assert 'NOTE = "bootstrap: schema v9 (just a string)"' in text
    assert "BANDS = (10, 20, 30, 40, 50)" in text


def test_extract_schema_version_parses_marker() -> None:
    """Direct unit test for the marker parser."""
    fn = config_bootstrap._extract_schema_version
    assert fn("# bootstrap: schema v2\nFOO = 1\n") == 2
    assert fn("# leading comment\n# bootstrap: schema v37\nFOO = 1\n") == 37
    assert fn("FOO = 1\n") is None
    assert fn("# unrelated comment\nFOO = 1\n") is None
    # Marker without digits → None.
    assert fn("# bootstrap: schema v\nFOO = 1\n") is None
    # Marker inside a string literal (not a comment line) → None.
    assert fn('FOO = "bootstrap: schema v3"\n') is None


def test_extract_schema_version_is_whitespace_tolerant() -> None:
    """O2 fix: extra whitespace between tokens must still match."""
    fn = config_bootstrap._extract_schema_version
    # Multiple spaces.
    assert fn("#  bootstrap:  schema  v4\nFOO = 1\n") == 4
    # Tab separators.
    assert fn("#\tbootstrap:\tschema\tv5\nFOO = 1\n") == 5
    # Mixed.
    assert fn("# \t bootstrap: \t schema \t v6\nFOO = 1\n") == 6
    # Leading whitespace before the # is fine.
    assert fn("   # bootstrap: schema v7\nFOO = 1\n") == 7
