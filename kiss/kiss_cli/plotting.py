"""Dependency-free quick plots for direct-API chat agents."""

from __future__ import annotations

import math
from html import escape
from pathlib import Path


PALETTE = ("#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9")


class PlotError(ValueError):
    pass


def _number(value, label: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise PlotError(f"{label} must contain numbers") from None
    if not math.isfinite(out):
        raise PlotError(f"{label} contains a non-finite value")
    return out


def _tick(value: float) -> str:
    if value == 0:
        return "0"
    if abs(value) >= 10_000 or abs(value) < 0.01:
        return f"{value:.2g}"
    return f"{value:.4g}"


def render_svg(spec: dict, output: Path) -> str:
    """Render a validated line, scatter, or bar plot to ``output``."""
    kind = str(spec.get("kind") or "line").lower()
    if kind not in {"line", "scatter", "bar"}:
        raise PlotError("kind must be line, scatter, or bar")
    raw_series = spec.get("series")
    if not isinstance(raw_series, list) or not 1 <= len(raw_series) <= 12:
        raise PlotError("series must contain between 1 and 12 data series")

    series = []
    total = 0
    all_numeric_x = True
    for index, item in enumerate(raw_series):
        if not isinstance(item, dict):
            raise PlotError("each series must be an object")
        ys = item.get("y")
        if not isinstance(ys, list) or not ys:
            raise PlotError(f"series {index + 1} needs a non-empty y array")
        xs = item.get("x")
        if xs is None:
            xs = list(range(len(ys)))
        if not isinstance(xs, list) or len(xs) != len(ys):
            raise PlotError(f"series {index + 1} x and y lengths differ")
        total += len(ys)
        if total > 5000:
            raise PlotError("a quick plot is limited to 5,000 total points")
        ynums = [_number(v, f"series {index + 1} y") for v in ys]
        try:
            xnums = [_number(v, f"series {index + 1} x") for v in xs]
        except PlotError:
            all_numeric_x = False
            xnums = [float(i) for i in range(len(xs))]
        series.append({
            "name": str(item.get("name") or f"Series {index + 1}")[:80],
            "x": xnums, "labels": [str(v)[:40] for v in xs], "y": ynums,
        })

    if not all_numeric_x:
        for item in series:
            item["x"] = [float(i) for i in range(len(item["y"]))]

    width, height = 800, 480
    left, right, top, bottom = 76, 26, 58, 68
    pw, ph = width - left - right, height - top - bottom
    all_x = [v for item in series for v in item["x"]]
    all_y = [v for item in series for v in item["y"]]
    if kind == "bar":
        xmin, xmax = -0.5, max(len(item["y"]) for item in series) - 0.5
        ymin, ymax = min(0.0, min(all_y)), max(0.0, max(all_y))
    else:
        xmin, xmax = min(all_x), max(all_x)
        ymin, ymax = min(all_y), max(all_y)
    if xmin == xmax:
        xmin -= 0.5
        xmax += 0.5
    if ymin == ymax:
        pad = abs(ymin) * 0.1 or 1.0
        ymin -= pad
        ymax += pad
    else:
        pad = (ymax - ymin) * 0.06
        ymin -= pad
        ymax += pad

    sx = lambda value: left + (value - xmin) / (xmax - xmin) * pw
    sy = lambda value: top + (ymax - value) / (ymax - ymin) * ph
    title = escape(str(spec.get("title") or "GeoForge plot")[:160])
    x_label = escape(str(spec.get("x_label") or "")[:100])
    y_label = escape(str(spec.get("y_label") or "")[:100])
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="480" viewBox="0 0 800 480">',
        '<rect width="800" height="480" fill="#ffffff"/>',
        '<style>text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;fill:#1b1b1c}'
        '.tick{font-size:11px;fill:#61666b}.label{font-size:13px}.legend{font-size:11px}</style>',
        f'<text x="{left}" y="30" font-size="18" font-weight="600">{title}</text>',
    ]
    for i in range(6):
        value = ymin + (ymax - ymin) * i / 5
        y = sy(value)
        parts.append(f'<line x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}" stroke="#e7e9ed"/>')
        parts.append(f'<text class="tick" x="{left-9}" y="{y+4:.2f}" text-anchor="end">{escape(_tick(value))}</text>')
    parts += [
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#81858c"/>',
        f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#81858c"/>',
    ]

    labels = series[0]["labels"]
    tick_count = min(8, len(labels))
    tick_indices = sorted({round(i * (len(labels) - 1) / max(1, tick_count - 1)) for i in range(tick_count)})
    for index in tick_indices:
        value = series[0]["x"][index]
        label = labels[index] if not all_numeric_x else _tick(value)
        x = sx(value)
        parts.append(f'<line x1="{x:.2f}" y1="{height-bottom}" x2="{x:.2f}" y2="{height-bottom+5}" stroke="#81858c"/>')
        parts.append(f'<text class="tick" x="{x:.2f}" y="{height-bottom+20}" text-anchor="middle">{escape(label)}</text>')

    if kind == "bar":
        group = 0.78
        bar_width = group / len(series)
        for si, item in enumerate(series):
            color = PALETTE[si % len(PALETTE)]
            for xvalue, yvalue in zip(item["x"], item["y"]):
                x0 = sx(xvalue - group / 2 + si * bar_width)
                x1 = sx(xvalue - group / 2 + (si + 1) * bar_width)
                y0, y1 = sy(0), sy(yvalue)
                parts.append(f'<rect x="{x0:.2f}" y="{min(y0,y1):.2f}" width="{max(1,x1-x0-1):.2f}" height="{abs(y1-y0):.2f}" fill="{color}" opacity=".9"/>')
    else:
        for si, item in enumerate(series):
            color = PALETTE[si % len(PALETTE)]
            points = " ".join(f'{sx(x):.2f},{sy(y):.2f}' for x, y in zip(item["x"], item["y"]))
            if kind == "line":
                parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>')
            radius = 3.2 if kind == "scatter" else 2.2
            if kind == "scatter" or len(item["y"]) <= 80:
                for xvalue, yvalue in zip(item["x"], item["y"]):
                    parts.append(f'<circle cx="{sx(xvalue):.2f}" cy="{sy(yvalue):.2f}" r="{radius}" fill="{color}"/>')

    if x_label:
        parts.append(f'<text class="label" x="{left+pw/2:.2f}" y="466" text-anchor="middle">{x_label}</text>')
    if y_label:
        parts.append(f'<text class="label" transform="translate(19 {top+ph/2:.2f}) rotate(-90)" text-anchor="middle">{y_label}</text>')
    legend_x = width - right - 8
    for si, item in enumerate(series[:8]):
        y = 24 + si * 17
        color = PALETTE[si % len(PALETTE)]
        parts.append(f'<line x1="{legend_x-105}" y1="{y}" x2="{legend_x-89}" y2="{y}" stroke="{color}" stroke-width="3"/>')
        parts.append(f'<text class="legend" x="{legend_x-84}" y="{y+4}">{escape(item["name"])}</text>')
    parts.append('</svg>')

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(parts), encoding="utf-8")
    return f"created {output.name} ({kind}, {len(series)} series, {total} points)"
