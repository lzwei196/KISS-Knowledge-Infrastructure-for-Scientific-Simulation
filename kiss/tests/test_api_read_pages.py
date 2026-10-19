"""File reads expose exact coverage without binary decoding or silent offsets."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from kiss_cli import api, provider_diagnostics as diagnostics


def test_complete_line_pages_reconstruct_full_file_without_gaps(tmp_path):
    path = tmp_path / "SKILL.md"
    content = "".join(f"{n}:" + "文" * 997 + "\n" for n in range(130))
    path.write_text(content, encoding="utf-8", newline="")
    start, collected, pages = 1, [], []
    while True:
        page = api._read_text_page(path, start, 1000)
        meta = page.read_metadata
        assert len(page.content) <= 60000 and page.content.endswith("\n")
        assert meta["read_page_sha256"] == hashlib.sha256(page.content.encode()).hexdigest()
        assert meta["read_start_line"] == start
        assert meta["read_end_line"] == start + len(page.content.splitlines()) - 1
        assert meta["read_total_lines"] == 130
        pages.append(meta); collected.append(page.content)
        if meta["read_eof"]:
            assert meta["next_start_line"] is None
            break
        start = meta["next_start_line"]
    assert len(pages) == 3 and "".join(collected) == content
    assert len({p["read_file_sha256"] for p in pages}) == 1


def test_line_count_and_eof_are_explicit(tmp_path):
    path = tmp_path / "readme.txt"
    path.write_bytes(b"first\r\nsecond\r\nthird")
    first = api._read_text_page(path, 1, 2)
    assert first.content == "first\nsecond\n"
    assert first.read_metadata["next_start_line"] == 3 and not first.read_metadata["read_eof"]
    last = api._read_text_page(path, 3, 2)
    assert last.content == "third" and last.read_metadata["read_eof"]
    absent = api._read_text_page(path, 4, 2)
    assert absent.content == "" and absent.read_metadata["read_eof"]
    assert absent.read_metadata["read_start_line"] is None


@pytest.mark.parametrize("name,raw,label", [
    ("manual.pdf", b"%PDF-1.7\nPRIVATE_BINARY_CONTENT", "pdf"),
    ("renamed.txt", b"%PDF-1.7\nPRIVATE_BINARY_CONTENT", "pdf"),
    ("data.nc", b"CDF\x01PRIVATE_BINARY_CONTENT", "binary"),
    ("data.bin", b"hello\x00PRIVATE_BINARY_CONTENT", "binary"),
])
def test_pdf_and_binary_return_no_fake_document_text(tmp_path, name, raw, label):
    path = tmp_path / name; path.write_bytes(raw)
    with pytest.raises(api.ToolError, match="not a text page") as caught:
        api._read_text_page(path)
    assert caught.value.read_metadata["read_kind"] == label
    assert "PRIVATE_BINARY_CONTENT" not in str(caught.value)
    assert "read_page_sha256" not in caught.value.read_metadata


def test_overlong_line_is_explicit_never_skipped_or_reported_complete(tmp_path):
    path = tmp_path / "long.json"
    path.write_text("short\n" + "x" * 60001 + "\nlast\n")
    first = api._read_text_page(path)
    assert first.content == "short\n" and first.read_metadata["next_start_line"] == 2
    with pytest.raises(api.ToolError, match="No partial line") as caught:
        api._read_text_page(path, 2)
    assert caught.value.read_metadata["read_kind"] == "overlong_line"
    assert "read_eof" not in caught.value.read_metadata


@pytest.mark.parametrize("start,count", [(True, 1), (1.5, 1), (1, False), (0, 1), (1, 0), (1, 2001)])
def test_invalid_page_numbers_are_not_silently_coerced(tmp_path, start, count):
    with pytest.raises(api.ToolError):
        api._read_text_page(tmp_path / "unused", start, count)


@pytest.mark.parametrize("name,setup_mode", [("read_ki_file", False), ("read_work_file", True)])
def test_unknown_offset_is_rejected_before_reading(tmp_path, monkeypatch, name, setup_mode):
    monkeypatch.setattr(api, "_read_text_page", lambda *a, **k: pytest.fail("offset must not read first page"))
    with pytest.raises(api.ToolError, match="start_line.*offset"):
        api._execute_tool(name, {"path": "SKILL.md", "offset": 1000},
            SimpleNamespace(root=tmp_path), SimpleNamespace(root=tmp_path), setup_mode=setup_mode)


def test_read_schemas_disclose_paging_and_reject_extra_parameters(tmp_path):
    schemas = {row["name"]: row for row in api.tool_schemas(SimpleNamespace(root=tmp_path), setup_mode=True)}
    for name in ("read_ki_file", "read_work_file"):
        assert schemas[name]["input_schema"]["additionalProperties"] is False
        assert "next_start_line" in schemas[name]["description"]
        assert "offset" not in schemas[name]["input_schema"]["properties"]


def test_provider_diagnostics_distinguish_repeated_pages_without_contents(tmp_path, monkeypatch):
    path = tmp_path / "SKILL.md"; path.write_text("PRIVATE_CONTENT\nsecond\n")
    pdf = tmp_path / "manual.pdf"; pdf.write_bytes(b"%PDF-1.7\nSECRET_PDF")
    monkeypatch.setenv("READ_TEST_KEY", "PRIVATE_PROVIDER_KEY")
    prov = api.ApiProvider("diag", "Diag", "openai", "https://invalid.example", "READ_TEST_KEY", {"m": "m"}, "m")
    calls = [("SKILL.md", 1), ("SKILL.md", 1), ("SKILL.md", 2), ("manual.pdf", 1)]
    responses = [({"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
        {"id": f"c{i}", "function": {"name": "read_ki_file", "arguments": json.dumps({"path": name, "start_line": start})}}]},
        "finish_reason": "tool_calls"}]}) for i, (name, start) in enumerate(calls)]
    responses.append({"choices": [{"message": {"role": "assistant", "content": "finished"}, "finish_reason": "stop"}]})
    iterator = iter(responses)
    monkeypatch.setattr(api, "_post", lambda *a, **k: next(iterator))
    monkeypatch.setattr(api, "tool_schemas", lambda *a, **k: [])
    monkeypatch.setattr(api, "execute_tool", lambda _name, args, *a, **k:
        api._read_text_page(tmp_path / args["path"], args["start_line"], 1))
    flow = SimpleNamespace(project=tmp_path, state=SimpleNamespace(value="EXECUTING"), approval_id="approval1")
    list(api.run(prov, SimpleNamespace(), SimpleNamespace(root=tmp_path), "system", "task", project_mode=True, flow=flow))
    log = (tmp_path / diagnostics.LOG).read_text()
    rows = [json.loads(line) for line in log.splitlines() if json.loads(line)["event"] == "tool_result"]
    assert len(rows) == 4
    assert rows[0]["read_page_sha256"] == rows[1]["read_page_sha256"] != rows[2]["read_page_sha256"]
    assert rows[0]["read_start_line"] == 1 and rows[2]["read_start_line"] == 2
    assert rows[0]["read_source_sha256"] == rows[2]["read_source_sha256"]
    assert rows[3]["read_kind"] == "pdf"
    assert "PRIVATE_CONTENT" not in log and "SECRET_PDF" not in log and "PRIVATE_PROVIDER_KEY" not in log
