"""Tiny dependency-free Windows notification-area presence indicator."""

from __future__ import annotations

import ctypes
import os
import threading
import webbrowser
from ctypes import wintypes
from typing import Callable


WM_DESTROY = 0x0002
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_APP = 0x8000
TRAY_MESSAGE = WM_APP + 17
NIM_ADD = 0
NIM_DELETE = 2
NIF_MESSAGE = 0x01
NIF_ICON = 0x02
NIF_TIP = 0x04
IDI_APPLICATION = 32512
MF_STRING = 0x0000
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
CMD_OPEN = 1001
CMD_EXIT = 1002


class _NotifyIconData(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeoutOrVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


def _exit(on_exit: Callable[[], object] | None) -> None:
    """Leave the process, first ending what the Desktop launched.

    ``os._exit`` skips atexit, and Windows does not end a parent's children:
    without ``on_exit`` calibration workers and agent CLIs outlive the app.
    """
    if on_exit is not None:
        try:
            on_exit()
        except Exception:  # noqa: BLE001 — exit regardless; cleanup is best effort
            pass
    os._exit(0)


def start(url: str, on_exit: Callable[[], object] | None = None) -> threading.Thread | None:
    """Show a tray icon whose double-click reopens *url*. Never blocks startup.

    ``on_exit`` runs when the user chooses Exit, before the process ends.
    """
    if not hasattr(ctypes, "windll"):
        return None

    def run() -> None:
        user32, shell32, kernel32 = (
            ctypes.windll.user32, ctypes.windll.shell32, ctypes.windll.kernel32)
        user32.DefWindowProcW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
        user32.LoadIconW.restype = wintypes.HICON
        user32.CreatePopupMenu.argtypes = []
        user32.CreatePopupMenu.restype = wintypes.HMENU
        user32.AppendMenuW.argtypes = [
            wintypes.HMENU, wintypes.UINT, wintypes.WPARAM, wintypes.LPCWSTR]
        user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.TrackPopupMenu.argtypes = [
            wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
        user32.TrackPopupMenu.restype = wintypes.UINT
        user32.DestroyMenu.argtypes = [wintypes.HMENU]
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        wndproc_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
            wintypes.WPARAM, wintypes.LPARAM)

        @wndproc_type
        def wndproc(hwnd, message, wparam, lparam):
            if message == TRAY_MESSAGE and lparam == WM_LBUTTONDBLCLK:
                webbrowser.open(url)
                return 0
            if message == TRAY_MESSAGE and lparam == WM_RBUTTONUP:
                menu = user32.CreatePopupMenu()
                if menu:
                    user32.AppendMenuW(menu, MF_STRING, CMD_OPEN, "Open GeoForge")
                    user32.AppendMenuW(menu, MF_STRING, CMD_EXIT, "Exit GeoForge")
                    point = wintypes.POINT()
                    user32.GetCursorPos(ctypes.byref(point))
                    # Required by TrackPopupMenu so clicking elsewhere dismisses
                    # the menu correctly for a notification-area-only window.
                    user32.SetForegroundWindow(hwnd)
                    command = user32.TrackPopupMenu(
                        menu, TPM_RIGHTBUTTON | TPM_RETURNCMD,
                        point.x, point.y, 0, hwnd, None)
                    user32.DestroyMenu(menu)
                    if command == CMD_OPEN:
                        webbrowser.open(url)
                    elif command == CMD_EXIT:
                        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))
                        user32.DestroyWindow(hwnd)
                        # gui.serve() owns the main thread and has no external
                        # shutdown handle. End this self-contained local server
                        # after removing its icon; settings writes are atomic.
                        _exit(on_exit)
                return 0
            if message == WM_DESTROY:
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)

        class WndClass(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT), ("lpfnWndProc", wndproc_type),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
            ]

        instance = kernel32.GetModuleHandleW(None)
        class_name = f"GeoForgeTray-{kernel32.GetCurrentProcessId()}"
        wc = WndClass(0, wndproc, 0, 0, instance, None, None, None, None, class_name)
        if not user32.RegisterClassW(ctypes.byref(wc)):
            return
        hwnd = user32.CreateWindowExW(
            0, class_name, "GeoForge Desktop", 0, 0, 0, 0, 0,
            None, None, instance, None)
        if not hwnd:
            return
        # PyInstaller stores the application icon as resource 1. Fall back to
        # Windows' application icon if that resource is unavailable.
        icon = user32.LoadIconW(instance, ctypes.c_void_p(1))
        if not icon:
            icon = user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))
        data = _NotifyIconData()
        data.cbSize = ctypes.sizeof(data)
        data.hWnd, data.uID = hwnd, 1
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        data.uCallbackMessage, data.hIcon = TRAY_MESSAGE, icon
        data.szTip = "GeoForge Desktop — double-click to open"
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data))
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    thread = threading.Thread(target=run, name="geoforge-tray", daemon=True)
    thread.start()
    return thread
