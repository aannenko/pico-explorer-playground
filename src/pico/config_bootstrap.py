"""Self-healing bootstrap for ``config.py``.

``config.py`` is git-ignored, so it can be missing or behind the codebase.
This module reconciles it against ``config.sample.py``:

  - target missing or has no recognised keys -> copy whole sample, return CONFIG_CREATED
  - target has all keys                      -> no-op,             return CONFIG_OK
  - target has some keys                     -> append missing keys (and any
                                                sample imports the target
                                                lacks), return CONFIG_PATCHED

The parser only recognises top-level ``UPPER_SNAKE_CASE = ...`` assignments;
right-hand sides (including multi-line tuples) are copied verbatim, never
evaluated.  Must not import anything that depends on ``config``.
"""

import os


_SAMPLE = "config.sample.py"
_TARGET = "config.py"

CONFIG_OK = 0
CONFIG_PATCHED = 1
CONFIG_CREATED = 2


def _assignment_key(line):  # (str) -> str | None
    """Return the LHS key if ``line`` starts a top-level UPPER_SNAKE_CASE assignment."""
    if not line or line[0] in " \t":
        return None

    # Identifier: first char must be A-Z or '_'; subsequent chars may also be 0-9.
    first = line[0]
    if first != "_" and not ("A" <= first <= "Z"):
        return None
    length = len(line)
    pos = 1
    while pos < length:
        ch = line[pos]
        if ch == "_" or "A" <= ch <= "Z" or "0" <= ch <= "9":
            pos += 1
        else:
            break
    key = line[:pos]

    # Require a single '=' after optional horizontal whitespace (reject '==').
    while pos < length and line[pos] in " \t":
        pos += 1
    if pos >= length or line[pos] != "=":
        return None
    if pos + 1 < length and line[pos + 1] == "=":
        return None
    return key


def _bracket_depth_delta(line: str) -> int:
    """Net change in (/[/{ vs )/]/} on ``line``, ignoring ``# comment`` tails.

    Good enough for config files (no nested strings with brackets) and keeps
    multi-line tuple/list/dict values together when copied forward.
    """
    delta = 0
    for ch in line:
        if ch == "#":
            break
        if ch in "([{":
            delta += 1
        elif ch in ")]}":
            delta -= 1
    return delta


def _parse_keys(path: str) -> set:
    keys = set()
    with open(path, "r") as f:
        for line in f:
            key = _assignment_key(line)
            if key is not None:
                keys.add(key)
    return keys


def _parse_imports(path: str) -> list:
    """Return top-level ``import`` / ``from ... import ...`` lines in order.

    Indented imports (inside functions or conditional blocks) are skipped.
    Each entry keeps its trailing newline so it can be re-emitted verbatim.
    """
    imports = []
    with open(path, "r") as f:
        for line in f:
            stripped = line.lstrip()
            if stripped == line and (
                stripped.startswith("import ") or stripped.startswith("from ")
            ):
                imports.append(line)
    return imports


def _parse_blocks(path: str) -> list:
    """Return ``[(key, block_text), ...]`` for each top-level assignment.

    ``block_text`` includes the contiguous comment lines immediately preceding
    the assignment (no blank line between them) and any continuation lines of
    a multi-line value, so the explanation and the full RHS travel together.
    """
    blocks = []
    pending_header = []
    with open(path, "r") as f:
        lines = f.readlines()

    idx = 0
    total = len(lines)
    while idx < total:
        line = lines[idx]

        if line.lstrip().startswith("#"):
            pending_header.append(line)
            idx += 1
            continue

        if not line.strip():
            pending_header = []
            idx += 1
            continue
        key = _assignment_key(line)
        if key is None:
            pending_header = []
            idx += 1
            continue

        body = [line]
        depth = _bracket_depth_delta(line)
        idx += 1
        while depth > 0 and idx < total:
            body.append(lines[idx])
            depth += _bracket_depth_delta(lines[idx])
            idx += 1
        blocks.append((key, "".join(pending_header) + "".join(body)))
        pending_header = []
    return blocks


def _copy_file(src: str, dst: str) -> None:
    with open(src, "r") as fsrc, open(dst, "w") as fdst:
        while True:
            chunk = fsrc.read(512)
            if not chunk:
                break
            fdst.write(chunk)


def _target_exists(path: str) -> bool:
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def ensure_config(sample_path: str = _SAMPLE, target_path: str = _TARGET) -> int:
    """Make ``target_path`` carry every key declared in ``sample_path``.

    Returns one of ``CONFIG_OK`` / ``CONFIG_PATCHED`` / ``CONFIG_CREATED``.
    Silent — callers handle any user-facing logging.
    """
    if not _target_exists(target_path):
        _copy_file(sample_path, target_path)
        return CONFIG_CREATED

    target_keys = _parse_keys(target_path)
    # An "empty" target (no recognised assignments) can't safely receive
    # appended blocks — it may lack required imports like ``from micropython
    # import const``.  Treat it as missing and overwrite from the sample.
    if not target_keys:
        _copy_file(sample_path, target_path)
        return CONFIG_CREATED

    sample_blocks = _parse_blocks(sample_path)
    missing_blocks = [(k, b) for k, b in sample_blocks if k not in target_keys]
    if not missing_blocks:
        return CONFIG_OK

    # Forward any sample imports the target lacks, so appended blocks that
    # need (e.g.) ``const`` remain importable.
    target_imports = {line.rstrip() for line in _parse_imports(target_path)}
    missing_imports = [
        line for line in _parse_imports(sample_path)
        if line.rstrip() not in target_imports
    ]

    with open(target_path, "a") as f:
        f.write("\n\n# --- Added by config_bootstrap from {} ---\n".format(sample_path))
        for line in missing_imports:
            f.write(line)
        if missing_imports:
            f.write("\n")
        for _key, block in missing_blocks:
            f.write(block)
    return CONFIG_PATCHED
