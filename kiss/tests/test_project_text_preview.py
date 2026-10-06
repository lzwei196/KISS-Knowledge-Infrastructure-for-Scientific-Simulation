"""Bounded raw-data previews must not become bulk reads or private-card access."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import api


def read_project(project, relative):
    env = SimpleNamespace(root=project)
    return api.execute_tool("read_project_file", {"path": relative}, env, env,
                            project_mode=True)


def test_large_csv_header_is_visible_without_reading_the_whole_file(tmp_path, monkeypatch):
    path = tmp_path / "observations.csv"
    header = "Station,date,latitude,longitude,soil temp (C)\n"
    path.write_bytes(header.encode() + b"station,2020-01-01,45,-72,2.0\n" * 200000)
    assert path.stat().st_size > 5_000_000
    original_open = Path.open
    reads = []
    byte_positions = []

    class WatchedStream:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def read(self, size=-1):
            assert 0 < size <= 120001, "unbounded dataset read"
            reads.append(size)
            result = self.stream.read(size)
            byte_positions.append(self.stream.buffer.tell())
            return result

    def watched_open(candidate, *args, **kwargs):
        stream = original_open(candidate, *args, **kwargs)
        return WatchedStream(stream) if candidate == path else stream

    monkeypatch.setattr(Path, "open", watched_open)
    result = read_project(tmp_path, path.name)
    assert result.startswith(header)
    assert reads == [120001]
    assert max(byte_positions) < 200000 < path.stat().st_size
    preview, warning = result.split("\n\n[TRUNCATED PREVIEW:", 1)
    assert len(preview) == 120000
    assert "does not establish full-file coverage or record counts" in warning


@pytest.mark.parametrize("content", [b"small text\n", "soil temp (°C)\nQuébec\n".encode(),
                                     b"soil temp (\xb0C)\n"])
def test_small_text_preserves_existing_utf8_replacement_behavior(tmp_path, content):
    path = tmp_path / "small.csv"
    path.write_bytes(content)
    assert read_project(tmp_path, path.name) == content.decode("utf-8", errors="replace")


@pytest.mark.parametrize("length", [119999, 120000, 120001])
def test_preview_limit_counts_characters_and_warns_only_when_truncated(tmp_path, length):
    path = tmp_path / "unicode.txt"
    text = "é" * length
    path.write_text(text, encoding="utf-8")
    result = read_project(tmp_path, path.name)
    if length <= 120000:
        assert result == text
    else:
        assert result.startswith(text[:120000])
        assert "[TRUNCATED PREVIEW:" in result
        assert "record counts" in result


@pytest.mark.parametrize("content", [b"SQLite format 3\x00" + b"\x00" * 100,
                                     b"SQLite format 3", b"column,value\nrow,\x00\n"])
def test_binary_or_sqlite_preview_requires_a_format_aware_reader(tmp_path, content):
    path = tmp_path / "data.bin"
    path.write_bytes(content)
    with pytest.raises(api.ToolError, match="binary project file.*format-aware KI reader"):
        read_project(tmp_path, path.name)


@pytest.mark.parametrize("relative", ["setup-request.json", "setup-request-old.json",
                                      ".geoforge/manual-download-details.json"])
def test_private_cards_are_rejected_before_any_preview_read(tmp_path, monkeypatch, relative):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"url":"private-link","code":"private-code"}', encoding="utf-8")
    original_open = Path.open

    def guarded_open(candidate, *args, **kwargs):
        assert candidate != path, "private request card was opened"
        return original_open(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    with pytest.raises(api.ToolError, match="request card for the user"):
        read_project(tmp_path, relative)


def test_preview_still_rejects_project_path_escape(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "outside.txt").write_text("outside", encoding="utf-8")
    with pytest.raises(api.ToolError, match="escapes the chat project"):
        read_project(project, "../outside.txt")
