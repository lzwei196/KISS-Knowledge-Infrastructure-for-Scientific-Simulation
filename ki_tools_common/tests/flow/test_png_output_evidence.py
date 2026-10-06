"""PNG integrity is presentation evidence, never numerical model evidence."""
import builtins
import struct
import zlib

import pytest
from PIL import Image, PngImagePlugin

from ki_tools_common.flow import receipts

FACTS = {"errored": False, "output_nonempty": True}


@pytest.fixture
def png(tmp_path):
    target = tmp_path / "figure.png"
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("model-notes", "\n0 NaN inf 1 2\n")
    Image.new("RGB", (2, 3), (15, 20, 40)).save(target, pnginfo=metadata)
    return target


def validate(png, *, physical=False, extra=()):
    return receipts.validate_outputs(png.parent, [png, *extra], physical=physical, run_facts=FACTS)


def test_real_png_decoder_accepts_image_without_scanning_binary_as_numbers(png, monkeypatch):
    def no_numeric_probe(*args):
        pytest.fail("PNG must not enter the numeric/text parser")
    monkeypatch.setattr(receipts, "_load_series", no_numeric_probe)
    result = validate(png)
    assert result["status"] == "passed"
    check = next(c for c in result["checks"] if c["check"].startswith("png_decode:"))
    assert check["ok"] and "2x3 PNG decoded" in check["detail"]
    assert "excluded from numeric model evidence" in check["detail"]
    assert not any(c["check"].startswith("no_nan_inf:") for c in result["checks"])


def test_png_alone_cannot_pass_a_physical_model_step(png):
    result = validate(png, physical=True)
    assert result["status"] == "warning"
    assert any(c["check"] == "any_numeric_output" and not c["ok"] for c in result["checks"])


def test_png_with_real_model_series_keeps_numeric_validation(png):
    series = png.parent / "output.csv"
    series.write_text("time,discharge\n1,2\n2,3\n3,5\n", encoding="utf-8")
    assert validate(png, physical=True, extra=[series])["status"] == "passed"
    series.write_text("time,discharge\n1,NaN\n2,3\n3,5\n", encoding="utf-8")
    assert validate(png, physical=True, extra=[series])["status"] == "failed"


def chunk(kind, payload):
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))


@pytest.mark.parametrize("damage", ["not_png", "truncated", "bad_crc", "short_pixels",
                                    "iend_missing_1", "iend_missing_4", "iend_bad_crc",
                                    "trailing_bytes", "duplicate_iend"])
def test_invalid_container_and_incomplete_pixel_stream_fail(png, damage):
    original = png.read_bytes()
    if damage == "not_png":
        data = b"this is numeric text\n1 2 3\n"
    elif damage == "truncated":
        data = original[:-15]
    elif damage == "bad_crc":
        data = bytearray(original)
        at = data.index(b"IDAT") + 4
        data[at] ^= 1
    elif damage == "iend_missing_1":
        data = original[:-1]
    elif damage == "iend_missing_4":
        data = original[:-4]
    elif damage == "iend_bad_crc":
        data = original[:-1] + bytes([original[-1] ^ 1])
    elif damage == "trailing_bytes":
        data = original + b"trailing bytes"
    elif damage == "duplicate_iend":
        data = original + chunk(b"IEND", b"")
    else:
        # Correct PNG signature/chunk CRC and valid zlib, but insufficient RGB pixels.
        data = (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 3, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(b"\0\1\2\3")) + chunk(b"IEND", b""))
    png.write_bytes(data)
    result = validate(png)
    assert result["status"] == "failed"
    assert any(c["check"].startswith("png_decode:") and not c["ok"] for c in result["checks"])


def test_missing_decoder_fails_closed(png, monkeypatch):
    original_import = builtins.__import__
    def missing(name, *args, **kwargs):
        if name == "PIL":
            raise ImportError("decoder unavailable")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", missing)
    result = validate(png)
    assert result["status"] == "failed"
    assert any("ImportError" in c["detail"] for c in result["checks"])


def test_excessive_image_dimensions_fail_closed(png, monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1)
    assert validate(png)["status"] == "failed"
