"""Host CSV plots retain missing-date slots and bind provenance to parsed bytes."""
import hashlib
import io
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import api, plotting


NS = {"s": "http://www.w3.org/2000/svg"}


def csv_plot(tmp_path, data, *, series=None, kind="line", **extra):
    project = tmp_path / "project"
    source = project / "outputs/growth.csv"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(data)
    ki = SimpleNamespace(root=project / "models/Demo")
    ki.root.mkdir(parents=True, exist_ok=True)
    args = {"output_path": "artifacts/growth.svg", "source_path": "outputs/growth.csv",
            "x_column": "date", "kind": kind,
            "series": series or [{"name": "LAI", "y_column": "LAI"}], **extra}
    cfg = SimpleNamespace(root=project, python=sys.executable, roles={})
    return project, source, ki, cfg, args


def call(case):
    project, _, ki, cfg, args = case
    result = api.execute_tool("create_project_plot", args, ki, cfg, project_mode=True)
    svg = ET.fromstring((project / args["output_path"]).read_text(encoding="utf-8"))
    metadata = svg.find("s:metadata", NS)
    return result, svg, json.loads(metadata.text) if metadata is not None else None


def polylines(svg, color):
    return [[tuple(map(float, point.split(","))) for point in line.attrib["points"].split()]
            for line in svg.findall("s:polyline", NS) if line.attrib["stroke"] == color]


def test_csv_leading_and_interior_blanks_preserve_dual_axis_date_grid(tmp_path):
    raw = (b"\xef\xbb\xbfdate,LAI,biomass\r\n"
           b"1980-01-01,,10\r\n1980-01-02,0,20\r\n1980-01-03,1,\r\n"
           b"1980-01-04,   ,40\r\n1980-01-05,3,50\r\n1980-01-06,4,60\r\n")
    c = csv_plot(tmp_path, raw, series=[{"y_column": "LAI"},
        {"y_column": "biomass", "axis": "right"}],
        source_metadata={"source_sha256": "forged"}, source_sha256="forged")
    result, svg, metadata = call(c)
    x = lambda index: round(76 + index * (900 - 76 - 78) / 5, 2)
    left = polylines(svg, plotting.PALETTE[0])
    right = polylines(svg, plotting.PALETTE[1])
    assert [[point[0] for point in segment] for segment in left] == [[x(1), x(2)], [x(4), x(5)]]
    assert [[point[0] for point in segment] for segment in right] == [[x(0), x(1)], [x(3), x(4), x(5)]]
    assert left[0][0][1] == 452  # The real zero remains at the zero baseline.
    texts = [node.text for node in svg.findall("s:text", NS)]
    assert "1980-01-01" in texts and "1980-01-06" in texts
    assert metadata["source_path"] == "outputs/growth.csv"
    assert metadata["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert metadata["source_bytes"] == len(raw)
    assert metadata["x_column"] == "date"
    assert metadata["source_row_count"] == metadata["sampled_row_count"] == 6
    assert metadata["sampled_source_row_indices"] == list(range(6))
    assert metadata["total_slots"] == metadata["source_value_count"] == 12
    assert metadata["valid_count"] == metadata["source_valid_count"] == 9
    assert metadata["missing_count"] == metadata["source_missing_count"] == 3
    assert metadata["series"][0]["missing_count"] == 2
    assert metadata["series"][1]["missing_count"] == 1
    returned = json.loads(next(line.removeprefix("[PLOT_SOURCE] ") for line in result.splitlines()
                              if line.startswith("[PLOT_SOURCE] ")))
    assert returned == metadata and "forged" not in result
    assert c[1].read_bytes() == raw


@pytest.mark.parametrize("kind", ["scatter", "bar"])
def test_scatter_and_bar_skip_missing_without_deleting_zero_or_slots(tmp_path, kind):
    _, svg, metadata = call(csv_plot(tmp_path, b"date,LAI\nA,\nB,0\nC,\nD,2\n", kind=kind))
    if kind == "scatter":
        marks = svg.findall("s:circle", NS)
        assert [float(mark.attrib["cx"]) for mark in marks] == pytest.approx([342, 874])
    else:
        marks = [node for node in svg.findall("s:rect", NS) if node.attrib["fill"] == plotting.PALETTE[0]]
        assert len(marks) == 2 and float(marks[0].attrib["height"]) == 0
        assert float(marks[1].attrib["x"]) - float(marks[0].attrib["x"]) == pytest.approx(399)
    assert len(marks) == 2
    assert metadata["total_slots"] == 4 and metadata["valid_count"] == metadata["missing_count"] == 2


@pytest.mark.parametrize("value", ["NA", "null", "bad", "NaN", "nan", "Inf", "-Infinity"])
def test_csv_only_blanks_are_missing_not_invalid_text_or_nonfinite(tmp_path, value):
    c = csv_plot(tmp_path, f"date,LAI\nA,0\nB,{value}\n".encode())
    with pytest.raises(api.ToolError, match="numbers|non-finite"):
        call(c)
    assert not (c[0] / "artifacts/growth.svg").exists()


@pytest.mark.parametrize("data", [b"date,LAI\nA,1\nB\n", b"date,LAI\nA,1,2\n",
    b"date,LAI,LAI\nA,1,2\n", b"date,,LAI\nA,1,2\n"])
def test_malformed_rows_or_ambiguous_headers_are_not_blanks(tmp_path, data):
    with pytest.raises(api.ToolError, match="malformed data row|unique, nonempty"):
        call(csv_plot(tmp_path, data))


def test_all_missing_series_is_rejected_even_beside_valid_series(tmp_path):
    c = csv_plot(tmp_path, b"date,LAI,biomass\nA,,0\nB, ,2\n",
        series=[{"y_column": "biomass"}, {"y_column": "LAI", "axis": "right"}])
    with pytest.raises(api.ToolError, match="no non-missing y values"):
        call(c)
    assert not (c[0] / "artifacts/growth.svg").exists()


def test_manual_values_allow_none_but_cannot_claim_csv_provenance(tmp_path):
    c = csv_plot(tmp_path, b"date,LAI\nA,1\n")
    c[4].pop("source_path")
    c[4].update(series=[{"x": [1, 2, 3, 4], "y": [None, 0, None, 2]}],
                source_metadata={"source_path": "outputs/growth.csv", "source_sha256": "forged"})
    result, svg, metadata = call(c)
    assert metadata is None and "PLOT_SOURCE" not in result and "forged" not in ET.tostring(svg).decode()
    assert len(svg.findall("s:circle", NS)) == 2
    assert len(polylines(svg, plotting.PALETTE[0])) == 2


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "", "bad"])
def test_manual_values_still_reject_nonfinite_or_text(tmp_path, value):
    with pytest.raises(plotting.PlotError, match="numbers|non-finite"):
        plotting.render_svg({"series": [{"y": [0, value]}]}, tmp_path / "invalid.svg")


def test_bound_counts_missing_slots_and_isolated_long_line_point_is_visible(tmp_path):
    output = tmp_path / "plot.svg"
    with pytest.raises(plotting.PlotError, match="5,000"):
        plotting.render_svg({"series": [{"y": [None] * 5000 + [0]}]}, output)
    plotting.render_svg({"series": [{"y": [None] * 4999 + [0]}]}, output)
    svg = ET.fromstring(output.read_text())
    circles = svg.findall("s:circle", NS)
    assert len(circles) == 1 and circles[0].attrib["cx"] == "874.00"


def test_sampling_is_bounded_common_to_series_and_discloses_source_counts(tmp_path):
    raw = ("date,LAI,biomass\n" + "".join(f"D{i},{i},{i * 2}\n" for i in range(5001))).encode()
    _, svg, metadata = call(csv_plot(tmp_path, raw,
        series=[{"y_column": "LAI"}, {"y_column": "biomass", "axis": "right"}]))
    assert metadata["source_row_count"] == 5001 and metadata["sampled_row_count"] == 2500
    assert metadata["total_slots"] == 5000 and metadata["source_value_count"] == 10002
    assert metadata["sampled_source_row_indices"][0] == 0
    assert metadata["sampled_source_row_indices"][-1] == 5000
    assert metadata["sampling"] == "uniform_endpoints"
    left, right = (polylines(svg, color)[0] for color in plotting.PALETTE[:2])
    assert [point[0] for point in left] == [point[0] for point in right]


@pytest.mark.parametrize("hidden", ["bad", "NaN", ""])
def test_unsampled_invalid_values_and_hidden_line_gaps_are_not_silently_ignored(tmp_path, hidden):
    kept = {round(i * 5000 / 4999) for i in range(5000)}
    omitted = next(i for i in range(5001) if i not in kept)
    raw = ("date,LAI\n" + "".join(f"D{i},{hidden if i == omitted else 1}\n" for i in range(5001))).encode()
    with pytest.raises(api.ToolError, match="numbers|non-finite|hide a missing-value gap"):
        call(csv_plot(tmp_path, raw))


def test_provenance_hashes_the_single_byte_snapshot_that_was_parsed(tmp_path, monkeypatch):
    raw = b"date,LAI\r\nA,0\r\nB,4\r\n"
    c = csv_plot(tmp_path, raw)
    replacement = b"date,LAI\nA,1000\nB,2000\n"
    original_open, reads = Path.open, []

    class ChangingStream(io.BytesIO):
        def read(self, size=-1):
            reads.append(size)
            snapshot = super().read(size)
            c[1].write_bytes(replacement)
            return snapshot

    def opening(path, mode="r", *args, **kwargs):
        if path == c[1] and mode == "rb":
            return ChangingStream(raw)
        return original_open(path, mode, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", opening)
        _, svg, metadata = call(c)
    assert reads == [20_000_001]
    assert metadata["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert c[1].read_bytes() == replacement
    assert polylines(svg, plotting.PALETTE[0])[0][0][1] == 452


@pytest.mark.parametrize("kind", ["line", "scatter", "bar"])
def test_nonmissing_manual_plot_contract_stays_unchanged(tmp_path, kind):
    output = tmp_path / "valid.svg"
    result = plotting.render_svg({"kind": kind, "title": "Original", "series": [
        {"x": [0, 1, 2], "y": [0, 3, 6]}]}, output)
    assert result == f"created valid.svg ({kind}, 1 series, 3 points)"
    svg = ET.fromstring(output.read_text())
    assert svg.find("s:metadata", NS) is None
    if kind == "line":
        assert len(polylines(svg, plotting.PALETTE[0])) == 1
    if kind in {"line", "scatter"}:
        assert len(svg.findall("s:circle", NS)) == 3
