"""Tests for cross_platform.py — binary detection and execution."""
import os
import pytest
from ki_tools_common.cross_platform import detect_binary_type, check_wine_available


class TestDetectBinaryType:
    def test_dlbreach_pe32_console(self):
        path = "KISSPATH_BINARIES/dlbreach/bin/DLBreach_Barrier.exe"
        if not os.path.isfile(path):
            pytest.skip("DLBreach binary not available")
        info = detect_binary_type(path)
        assert info['type'] == 'pe32_console'
        assert info['details']['subsystem'] == 3

    def test_summa_elf_native(self):
        path = "KISSPATH_BINARIES/summa/bin/summa.exe"
        if not os.path.isfile(path):
            pytest.skip("SUMMA binary not available")
        info = detect_binary_type(path)
        assert info['type'] in ('elf_native', 'elf_broken_interp')

    def test_nonexistent_file(self):
        info = detect_binary_type("/tmp/nonexistent_binary_12345")
        assert info['type'] == 'unknown'
        assert not info['runnable']
        assert len(info['issues']) > 0


class TestCheckWine:
    def test_returns_dict(self):
        result = check_wine_available()
        assert isinstance(result, dict)
        assert 'available' in result
        assert 'version' in result
        assert 'path' in result
