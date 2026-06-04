"""Self-healing bootstrap for ``config.py``.

``config.py`` is git-ignored, so it can be missing or behind the codebase.
This module reconciles it against ``config.sample.py``:

  - target missing or has no recognised keys -> copy whole sample, return CONFIG_CREATED
  - target has all keys                      -> no-op,             return CONFIG_OK
  - target has some keys                     -> append missing keys (and any
                                                sample imports the target
                                                lacks), return CONFIG_PATCHED
  - target has stale-schema blocks           -> rewrite those blocks with
                                                sample's version,      return CONFIG_RESYNCED

The parser only recognises top-level ``UPPER_SNAKE_CASE = ...`` assignments;
right-hand sides (including multi-line tuples) are copied verbatim, never
evaluated.  Must not import anything that depends on ``config``.

**Schema-version reconciliation.** A sample block can declare a per-key
schema version by including a ``# bootstrap: schema v<N>`` line anywhere
in its preceding comment block.  When the sample's version is higher than
the target's (target lacking the marker counts as v0), the bootstrap
rewrites the target's block (header comments + value, bracket-balanced)
with the sample's block.  Use this to silently roll out schema changes;
user customisations of the affected key are clobbered by design.

Return-code precedence when multiple actions could apply in one boot:
``CREATED > RESYNCED > PATCHED > OK``.  ``CREATED`` is mutually exclusive
with the others (the file is rewritten from scratch); ``RESYNCED`` and
``PATCHED`` can in principle co-occur (user has missing keys *and*
stale-schema keys), in which case ``RESYNCED`` is returned.
"""

import os


_SAMPLE = "config.sample.py"
_TARGET = "config.py"

CONFIG_OK = 0
CONFIG_PATCHED = 1
CONFIG_CREATED = 2
CONFIG_RESYNCED = 3


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


def _extract_schema_version(block_text: str):  # (str) -> int | None
    """Return integer N if a ``# bootstrap: schema v<N>`` marker is present.

    Whitespace-tolerant: matches any positive whitespace between the
    tokens ``bootstrap:``, ``schema``, and ``v<digits>``.  Only comment
    lines are considered, so a ``bootstrap: schema v...`` substring in a
    string literal won't trigger.  Returns ``None`` if no marker is found
    or the version digits are missing.
    """
    for line in block_text.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            continue
        # str.split() with no args collapses any whitespace run.
        tokens = stripped[1:].split()
        for i in range(len(tokens) - 2):
            if (
                tokens[i] == "bootstrap:"
                and tokens[i + 1] == "schema"
                and len(tokens[i + 2]) > 1
                and tokens[i + 2][0] == "v"
                and tokens[i + 2][1:].isdigit()
            ):
                return int(tokens[i + 2][1:])
    return None


def _rewrite_with_replaced_blocks(target_path: str, replacements: dict) -> None:
    """Rewrite ``target_path`` swapping in ``replacements[key]`` for each named block.

    Each replacement is the full new block text (header comments + assignment
    + any multi-line continuation).  Surrounding content (other blocks, blank
    lines, unrelated lines) is preserved verbatim.  The original block's
    preceding comment header is dropped along with its body.
    """
    with open(target_path, "r") as f:
        lines = f.readlines()

    output = []
    idx = 0
    total = len(lines)
    pending_header = []

    while idx < total:
        line = lines[idx]

        if line.lstrip().startswith("#"):
            pending_header.append(line)
            idx += 1
            continue

        if not line.strip():
            output.extend(pending_header)
            pending_header = []
            output.append(line)
            idx += 1
            continue

        key = _assignment_key(line)
        if key is None:
            output.extend(pending_header)
            pending_header = []
            output.append(line)
            idx += 1
            continue

        # Start of an assignment block. Consume the body (multi-line allowed).
        body = [line]
        depth = _bracket_depth_delta(line)
        idx += 1
        while depth > 0 and idx < total:
            body.append(lines[idx])
            depth += _bracket_depth_delta(lines[idx])
            idx += 1

        if key in replacements:
            output.append(replacements[key])
            pending_header = []
        else:
            output.extend(pending_header)
            output.extend(body)
            pending_header = []

    output.extend(pending_header)

    with open(target_path, "w") as f:
        f.writelines(output)


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
    """Make ``target_path`` carry every key declared in ``sample_path`` at the
    sample's schema version.

    Returns one of ``CONFIG_OK`` / ``CONFIG_PATCHED`` / ``CONFIG_RESYNCED`` /
    ``CONFIG_CREATED``.  Precedence when multiple actions apply:
    ``CREATED > RESYNCED > PATCHED > OK``.  Silent — callers handle any
    user-facing logging.
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

    patched = False
    missing_blocks = [(k, b) for k, b in sample_blocks if k not in target_keys]
    if missing_blocks:
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
        patched = True

    # Schema-version reconciliation pass: for any sample block that carries
    # a ``# bootstrap: schema v<N>`` marker, replace the target's block when
    # the sample's version is higher (target missing the marker = v0).
    sample_marked = {}
    for key, block in sample_blocks:
        version = _extract_schema_version(block)
        if version is not None:
            sample_marked[key] = (version, block)

    if sample_marked:
        target_blocks = _parse_blocks(target_path)  # re-read after possible patch
        replacements = {}
        for key, target_block in target_blocks:
            if key not in sample_marked:
                continue
            sample_version, sample_block = sample_marked[key]
            target_version = _extract_schema_version(target_block)
            if target_version is None or sample_version > target_version:
                replacements[key] = sample_block

        if replacements:
            _rewrite_with_replaced_blocks(target_path, replacements)
            return CONFIG_RESYNCED

    if patched:
        return CONFIG_PATCHED
    return CONFIG_OK
