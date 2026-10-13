"""Win32 / ADB screencap helpers for the realtime preview tab."""
from __future__ import annotations

import ctypes
import re
import shutil
import subprocess
from ctypes import wintypes
from dataclasses import dataclass
from typing import Optional

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

PW_RENDERFULLCONTENT = 2
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    class_name: str

    def label(self) -> str:
        t = self.title if len(self.title) <= 64 else self.title[:61] + "..."
        return f"{t}  [{self.class_name}]  (0x{self.hwnd:X})"


@dataclass
class Frame:
    width: int
    height: int
    # top-down BGRA bytes, 4 * w * h
    bgra: bytes
    source: str = "win32"


EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def list_windows(title_filter: str = "") -> list[WindowInfo]:
    """Visible top-level windows with a non-empty title."""
    results: list[WindowInfo] = []
    filt = title_filter.strip()
    try:
        rx = re.compile(filt, re.I) if filt else None
    except re.error:
        rx = None
        needle = filt.lower()
    else:
        needle = None

    @EnumWindowsProc
    def _cb(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        if not title:
            return True
        if rx is not None:
            if not rx.search(title):
                return True
        elif needle is not None and needle not in title.lower():
            return True
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        results.append(WindowInfo(int(hwnd), title, cls.value))
        return True

    user32.EnumWindows(_cb, 0)
    results.sort(key=lambda w: w.title.lower())
    return results


def _client_size(hwnd: int) -> tuple[int, int]:
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        raise OSError("GetClientRect failed")
    return int(rect.right - rect.left), int(rect.bottom - rect.top)


def capture_hwnd(hwnd: int) -> Frame:
    """Capture window client area (PrintWindow, fallback BitBlt)."""
    if not user32.IsWindow(hwnd):
        raise OSError(f"Invalid hwnd: {hwnd}")

    w, h = _client_size(hwnd)
    if w <= 0 or h <= 0:
        raise OSError("Window client size is empty (minimized?)")

    hwnd_dc = user32.GetDC(hwnd)
    if not hwnd_dc:
        raise OSError("GetDC failed")
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
    old = gdi32.SelectObject(mem_dc, bmp)

    ok = bool(user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT))
    if not ok:
        ok = bool(user32.PrintWindow(hwnd, mem_dc, 0))
    if not ok:
        # last resort: BitBlt from window DC
        gdi32.BitBlt(mem_dc, 0, 0, w, h, hwnd_dc, 0, 0, SRCCOPY)

    bmi = BITMAPINFO()
    ctypes.memset(ctypes.byref(bmi), 0, ctypes.sizeof(bmi))
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h  # top-down
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = BI_RGB

    buf_size = w * h * 4
    buf = (ctypes.c_ubyte * buf_size)()
    got = gdi32.GetDIBits(mem_dc, bmp, 0, h, ctypes.byref(buf), ctypes.byref(bmi), DIB_RGB_COLORS)

    gdi32.SelectObject(mem_dc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, hwnd_dc)

    if got == 0:
        raise OSError("GetDIBits failed (black/empty capture)")

    return Frame(width=w, height=h, bgra=bytes(buf), source="win32")


def capture_adb(serial: str = "") -> Frame:
    """Capture via `adb exec-out screencap -p` (PNG). Requires adb on PATH."""
    adb = shutil.which("adb")
    if not adb:
        raise FileNotFoundError("adb not found on PATH")
    cmd = [adb]
    if serial.strip():
        cmd += ["-s", serial.strip()]
    cmd += ["exec-out", "screencap", "-p"]
    proc = subprocess.run(cmd, capture_output=True, timeout=15, check=False)
    if proc.returncode != 0 or not proc.stdout:
        err = (proc.stderr or b"").decode("utf-8", errors="replace")[:200]
        raise OSError(f"adb screencap failed: {err or proc.returncode}")
    # Decode PNG via Qt at call site — return raw PNG marked specially
    return Frame(width=0, height=0, bgra=proc.stdout, source="adb_png")


def find_hwnd_by_title(pattern: str) -> Optional[WindowInfo]:
    wins = list_windows(pattern)
    return wins[0] if wins else None
