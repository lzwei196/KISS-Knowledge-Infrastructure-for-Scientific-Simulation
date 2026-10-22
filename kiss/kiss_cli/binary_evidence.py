"""Text summaries of binary scientific files for frozen review evidence.

Reviewers and repair authors read text only. Without a summary, a NetCDF or
HDF5 output is just an inventory row (path, size, hash): its real layout —
dimensions, types, fill values, valid ranges, time units — stays invisible
and gets guessed. The host reads headers and a few values with the netCDF4
library; it never parses these formats itself. A summary describes the file
at capture time; it is not the file and grants nothing.
"""
from __future__ import annotations

import os
from pathlib import Path
import re

POLICY = "binary-evidence-summary-v1"
SUFFIX = ".geoforge-summary.txt"
MAGICS = (b"CDF\x01", b"CDF\x02", b"CDF\x05", b"\x89HDF\r\n\x1a\n")
MAX_SUMMARIES = 96
MAX_CHARS = 24000
SAMPLE = 8
FULL_STATS_LIMIT = 200000
MAX_ATTR_CHARS = 300


class SummaryUnavailable(RuntimeError):
    pass


def is_scientific_binary(path: Path) -> bool:
    try:
        with Path(path).open("rb") as stream:
            head = stream.read(8)
    except OSError:
        return False
    return head.startswith(MAGICS)


def series_key(relative: str) -> str:
    """Numbered outputs (201108260100.CHANOBS_DOMAIN1, ...) form one series."""
    return re.sub(r"\d+", "#", relative)


def select(candidates: list[tuple[str, float]]) -> list[tuple[str, int]]:
    """Choose (path, series size) pairs: first and last of each series.

    Groups under an outputs/ directory come first, then the most recently
    modified groups, so a capped packet still covers the run being investigated.
    """
    groups: dict[str, list[tuple[str, float]]] = {}
    for relative, mtime in sorted(candidates):
        groups.setdefault(series_key(relative), []).append((relative, mtime))
    ordered = sorted(groups.values(), key=lambda members: (
        "/outputs/" not in "/" + members[0][0], -max(m for _r, m in members), members[0][0]))
    chosen: list[tuple[str, int]] = []
    for members in ordered:
        picks = [members[0]] + ([members[-1]] if len(members) > 1 else [])
        for relative, _mtime in picks:
            if len(chosen) >= MAX_SUMMARIES:
                return chosen
            chosen.append((relative, len(members)))
    return chosen


def _short(value) -> str:
    text = repr(value.tolist() if hasattr(value, "tolist") else value)
    return text if len(text) <= MAX_ATTR_CHARS else text[:MAX_ATTR_CHARS] + "...(truncated)"


def _sample_index(shape) -> tuple:
    return tuple(slice(0, min(SAMPLE, n)) if i == len(shape) - 1 else 0 for i, n in enumerate(shape))


def summarize(path: Path, *, series_size: int = 1, series: str = "") -> str:
    try:
        import netCDF4
        import numpy
    except ImportError as error:
        raise SummaryUnavailable(f"netCDF4 is not installed in the GeoForge host ({error})") from None
    lines = [f"# GeoForge host summary of a binary scientific file ({POLICY}, netCDF4 {netCDF4.__version__}).",
             "# A description read with the netCDF4 library at capture time, not the file itself.",
             f"file: {Path(path).name}", f"bytes: {os.path.getsize(path)}"]
    if series_size > 1:
        lines.append(f"series: {series_size} files match {series}; this summary covers one of them")
    with netCDF4.Dataset(str(path), "r") as ds:
        lines += [f"data_model: {ds.data_model}", f"disk_format: {ds.disk_format}", "dimensions:"]
        lines += [f"  {name} = {len(dim)}{' (unlimited)' if dim.isunlimited() else ''}"
                  for name, dim in ds.dimensions.items()]
        lines.append("global attributes:")
        lines += [f"  {name} = {_short(ds.getncattr(name))}" for name in ds.ncattrs()]
        if ds.groups:
            lines.append(f"groups (not summarized): {sorted(ds.groups)}")
        lines.append("variables:")
        for name, var in ds.variables.items():
            lines.append(f"  {name}: dtype={var.dtype} dimensions={var.dimensions} shape={var.shape}")
            for attr in var.ncattrs():
                lines.append(f"    @{attr} = {_short(var.getncattr(attr))}")
            if var.size == 0 or not numpy.issubdtype(numpy.dtype(var.dtype), numpy.number):
                continue
            index = _sample_index(var.shape) if var.ndim else ()
            masked = numpy.ma.masked_array(var[index]).ravel()
            var.set_auto_maskandscale(False)
            try:
                raw = numpy.asarray(var[index]).ravel()
            finally:
                var.set_auto_maskandscale(True)
            lines.append(f"    sample (library masking/scaling applied): {_short(masked[:SAMPLE])}")
            lines.append(f"    sample (raw stored values): {_short(raw[:SAMPLE])}")
            if var.size <= FULL_STATS_LIMIT:
                values = numpy.ma.masked_array(var[...]).ravel()
                valid = values.compressed()
                stats = f"    all {var.size} values: masked={int(numpy.ma.count_masked(values))}"
                if valid.size:
                    stats += f" min={_short(valid.min())} max={_short(valid.max())}"
                lines.append(stats)
    text = "\n".join(lines) + "\n"
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n...(summary truncated at the host limit)\n"
    return text
