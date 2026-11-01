import micropython

from utilities.log import log_exception


def _raised(exc: Exception) -> Exception:
    try:
        raise exc
    except Exception as caught:
        return caught


def test_prints_tag_then_traceback_without_heap_summary(monkeypatch, capsys):
    heap_summaries = []
    monkeypatch.setattr(micropython, "mem_info", lambda: heap_summaries.append(1))

    log_exception("[x] err:", _raised(RuntimeError("boom")))

    out = capsys.readouterr().out
    assert out.startswith("[x] err:\nTraceback")
    assert "RuntimeError: boom" in out
    assert heap_summaries == []


def test_memory_error_prints_heap_summary_between_tag_and_traceback(monkeypatch, capsys):
    monkeypatch.setattr(micropython, "mem_info", lambda: print("<heap>"))

    log_exception("[x] err:", _raised(MemoryError("allocating 64 bytes")))

    out = capsys.readouterr().out
    assert out.startswith("[x] err:\n<heap>\nTraceback")
    assert "MemoryError: allocating 64 bytes" in out
