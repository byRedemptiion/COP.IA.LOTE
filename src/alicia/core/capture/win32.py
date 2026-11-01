"""Accès Win32 en lecture seule : liste des fenêtres, géométrie, écrans, PrintWindow.

Aucune fonction ici n'envoie d'entrée, n'injecte de code ni ne lit la mémoire d'un processus.
Le module s'importe sur toutes les plateformes ; les appels exigent Windows.
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

import numpy as np

from alicia.core.capture.models import Rect, WindowInfo
from alicia.core.errors import CaptureError, UnsupportedPlatformError

_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_NOACTIVATE = 0x08000000
_GW_OWNER = 4
# Bureau et barre des tâches de Windows : pas une application à regarder.
_DESKTOP_CLASSES = {
    "Progman",  # bureau
    "WorkerW",
    "Shell_TrayWnd",  # barre des tâches
    "Shell_SecondaryTrayWnd",
    "Windows.UI.Core.CoreWindow",  # menu Démarrer, Rechercher, centre de notifications
    "XamlExplorerHostIslandWindow",  # Alt+Tab
    "ForegroundStaging",
}
_DWMWA_EXTENDED_FRAME_BOUNDS = 9
_DWMWA_CLOAKED = 14
_MONITOR_DEFAULTTONEAREST = 2
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PW_CLIENTONLY = 0x1
_PW_RENDERFULLCONTENT = 0x2
_SMTO_ABORTIFHUNG = 0x2
_DPI_AWARENESS_PER_MONITOR_V2 = -4
_MAX_PIXELS = 64 * 1024 * 1024


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class _BitmapInfoHeader(ctypes.Structure):
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


class _BitmapInfo(ctypes.Structure):
    _fields_ = [("bmiHeader", _BitmapInfoHeader), ("bmiColors", wintypes.DWORD * 1)]


def _rect(value: wintypes.RECT) -> Rect:
    return Rect(value.left, value.top, value.right, value.bottom)


def enable_dpi_awareness() -> bool:
    """Coordonnées en pixels physiques (125 %, 150 %…). À appeler avant de créer l'UI."""
    if sys.platform != "win32":
        return False
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SetProcessDpiAwarenessContext.argtypes = [wintypes.HANDLE]
        user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        return bool(user32.SetProcessDpiAwarenessContext(_DPI_AWARENESS_PER_MONITOR_V2))
    except (AttributeError, OSError):
        return False


class Win32:
    """Façade ctypes. Une instance par processus suffit."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise UnsupportedPlatformError("La capture de fenêtres nécessite Windows.")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.dwmapi = ctypes.WinDLL("dwmapi")
        self.enum_windows_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.enum_monitors_proc = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HMONITOR,
            wintypes.HDC,
            ctypes.POINTER(wintypes.RECT),
            wintypes.LPARAM,
        )
        u, g, k = self.user32, self.gdi32, self.kernel32
        signatures = [
            (u.EnumWindows, [self.enum_windows_proc, wintypes.LPARAM], wintypes.BOOL),
            (
                u.EnumDisplayMonitors,
                [wintypes.HDC, ctypes.c_void_p, self.enum_monitors_proc, wintypes.LPARAM],
                wintypes.BOOL,
            ),
            (u.IsWindow, [wintypes.HWND], wintypes.BOOL),
            (u.IsWindowVisible, [wintypes.HWND], wintypes.BOOL),
            (u.IsIconic, [wintypes.HWND], wintypes.BOOL),
            (u.GetWindow, [wintypes.HWND, wintypes.UINT], wintypes.HWND),
            (u.GetWindowLongW, [wintypes.HWND, ctypes.c_int], wintypes.LONG),
            (u.GetWindowTextLengthW, [wintypes.HWND], ctypes.c_int),
            (u.GetWindowTextW, [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            (
                u.GetWindowThreadProcessId,
                [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)],
                wintypes.DWORD,
            ),
            (u.GetWindowRect, [wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            (u.GetClientRect, [wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            (u.MonitorFromWindow, [wintypes.HWND, wintypes.DWORD], wintypes.HMONITOR),
            (u.GetMonitorInfoW, [wintypes.HMONITOR, ctypes.POINTER(_MonitorInfo)], wintypes.BOOL),
            (u.GetDC, [wintypes.HWND], wintypes.HDC),
            (u.ReleaseDC, [wintypes.HWND, wintypes.HDC], ctypes.c_int),
            (u.PrintWindow, [wintypes.HWND, wintypes.HDC, wintypes.UINT], wintypes.BOOL),
            (
                u.SendMessageTimeoutW,
                [
                    wintypes.HWND,
                    wintypes.UINT,
                    wintypes.WPARAM,
                    wintypes.LPARAM,
                    wintypes.UINT,
                    wintypes.UINT,
                    ctypes.POINTER(ctypes.c_size_t),
                ],
                wintypes.LPARAM,
            ),
            (g.CreateCompatibleDC, [wintypes.HDC], wintypes.HDC),
            (g.DeleteDC, [wintypes.HDC], wintypes.BOOL),
            (
                g.CreateCompatibleBitmap,
                [wintypes.HDC, ctypes.c_int, ctypes.c_int],
                wintypes.HBITMAP,
            ),
            (g.SelectObject, [wintypes.HDC, wintypes.HANDLE], wintypes.HANDLE),
            (g.DeleteObject, [wintypes.HANDLE], wintypes.BOOL),
            (
                g.GetDIBits,
                [
                    wintypes.HDC,
                    wintypes.HBITMAP,
                    wintypes.UINT,
                    wintypes.UINT,
                    ctypes.c_void_p,
                    ctypes.POINTER(_BitmapInfo),
                    wintypes.UINT,
                ],
                ctypes.c_int,
            ),
            (k.OpenProcess, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            (k.CloseHandle, [wintypes.HANDLE], wintypes.BOOL),
            (
                k.QueryFullProcessImageNameW,
                [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)],
                wintypes.BOOL,
            ),
            (
                self.dwmapi.DwmGetWindowAttribute,
                [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD],
                ctypes.c_long,
            ),
        ]
        for function, argtypes, restype in signatures:
            function.argtypes = argtypes
            function.restype = restype

    # --- lecture d'informations -------------------------------------------------------------

    def title(self, hwnd: int) -> str:
        length = self.user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value.strip()

    def process_id(self, hwnd: int) -> int:
        pid = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def exe_name(self, pid: int) -> str:
        return os.path.basename(self.exe_path(pid))

    def exe_path(self, pid: int) -> str:
        handle = self.kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(1024)
            buffer = ctypes.create_unicode_buffer(size.value)
            if self.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return buffer.value
            return ""
        finally:
            self.kernel32.CloseHandle(handle)

    def is_cloaked(self, hwnd: int) -> bool:
        cloaked = wintypes.DWORD()
        result = self.dwmapi.DwmGetWindowAttribute(
            hwnd, _DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
        )
        return result == 0 and cloaked.value != 0

    def window_rect(self, hwnd: int) -> Rect | None:
        """Cadre visible (sans l'ombre DWM), en pixels physiques."""
        rect = wintypes.RECT()
        if (
            self.dwmapi.DwmGetWindowAttribute(
                hwnd, _DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect)
            )
            == 0
        ):
            return _rect(rect)
        if self.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return _rect(rect)
        return None

    def monitors(self) -> list[tuple[int, Rect]]:
        """Écrans dans l'ordre Windows ; l'index 1 correspond au premier."""
        found: list[tuple[int, Rect]] = []

        @self.enum_monitors_proc
        def visit(hmonitor, _hdc, _rect_ptr, _param):  # type: ignore[no-untyped-def]
            info = _MonitorInfo()
            info.cbSize = ctypes.sizeof(_MonitorInfo)
            if self.user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                found.append((int(hmonitor), _rect(info.rcMonitor)))
            return True

        self.user32.EnumDisplayMonitors(None, None, visit, 0)
        return found

    def cursor(self) -> tuple[int, int, int | None, Rect | None]:
        """Position du curseur (pixels physiques) et écran sous le curseur."""
        point = wintypes.POINT()
        if not self.user32.GetCursorPos(ctypes.byref(point)):
            raise CaptureError("Position du curseur introuvable.")
        x, y = int(point.x), int(point.y)
        for index, (_handle, rect) in enumerate(self.monitors(), start=1):
            if rect.left <= x < rect.right and rect.top <= y < rect.bottom:
                return x, y, index, rect
        return x, y, None, None

    def monitor_of(self, hwnd: int) -> tuple[int | None, Rect | None]:
        hmonitor = self.user32.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST)
        if not hmonitor:
            return None, None
        for index, (handle, rect) in enumerate(self.monitors(), start=1):
            if handle == int(hmonitor):
                return index, rect
        return None, None

    def describe(self, hwnd: int) -> WindowInfo:
        pid = self.process_id(hwnd)
        monitor_index, monitor_rect = self.monitor_of(hwnd)
        path = self.exe_path(pid)
        return WindowInfo(
            handle=int(hwnd),
            title=self.title(hwnd),
            process_id=pid,
            exe_name=os.path.basename(path),
            exe_path=path,
            rect=self.window_rect(hwnd),
            monitor_index=monitor_index,
            monitor_rect=monitor_rect,
            minimized=bool(self.user32.IsIconic(hwnd)),
        )

    def list_windows(self) -> list[WindowInfo]:
        own_pid = os.getpid()
        handles: list[int] = []

        @self.enum_windows_proc
        def visit(hwnd, _param):  # type: ignore[no-untyped-def]
            if not self.user32.IsWindowVisible(hwnd) or self.user32.GetWindow(hwnd, _GW_OWNER):
                return True
            ex_style = self.user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            if ex_style & (_WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE):
                return True
            if self.is_cloaked(hwnd) or not self.title(hwnd):
                return True
            if self.process_id(hwnd) == own_pid:
                return True
            handles.append(int(hwnd))
            return True

        if not self.user32.EnumWindows(visit, 0):
            raise CaptureError("Impossible d'énumérer les fenêtres Windows.")
        windows = [self.describe(hwnd) for hwnd in handles]
        return sorted(windows, key=lambda w: (w.title.casefold(), w.handle))

    def check_still_valid(self, window: WindowInfo) -> WindowInfo:
        """Rafraîchit la géométrie et refuse une fenêtre fermée ou remplacée."""
        if not self.user32.IsWindow(window.handle):
            raise CaptureError("La fenêtre sélectionnée a été fermée. Actualise la liste.")
        if self.process_id(window.handle) != window.process_id:
            raise CaptureError("La fenêtre sélectionnée a changé. Actualise la liste.")
        current = self.describe(window.handle)
        if current.minimized:
            raise CaptureError(
                "La fenêtre du jeu est réduite : en plein écran, le jeu se réduit dès que tu "
                "cliques sur Alicia. Appuie sur le raccourci (F9) directement en jeu pour capturer "
                "et analyser sans le quitter.",
                detail=f"fenêtre réduite (IsIconic), taille {current.rect}",
            )
        return current

    def foreground_window(self) -> WindowInfo | None:
        """Fenêtre au premier plan (le jeu, quand le raccourci est pressé en jeu)."""
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd or self.process_id(hwnd) == os.getpid():
            return None
        if self.class_name(int(hwnd)) in _DESKTOP_CLASSES:
            return None  # bureau ou barre des tâches : on regardera l'écran entier
        return self.describe(int(hwnd))

    def class_name(self, hwnd: int) -> str:
        buffer = ctypes.create_unicode_buffer(256)
        try:
            self.user32.GetClassNameW(wintypes.HWND(hwnd), buffer, 256)
        except (AttributeError, OSError):
            return ""
        return buffer.value

    # --- PrintWindow (repli) ----------------------------------------------------------------

    def printwindow_pixels(self, hwnd: int) -> np.ndarray:
        """Capture GDI de la zone cliente ; renvoie un tableau BGRA H×W×4."""
        response = ctypes.c_size_t()
        if not self.user32.SendMessageTimeoutW(
            hwnd, 0, 0, 0, _SMTO_ABORTIFHUNG, 500, ctypes.byref(response)
        ):
            raise CaptureError("La fenêtre ne répond pas.")
        client = wintypes.RECT()
        if not self.user32.GetClientRect(hwnd, ctypes.byref(client)):
            raise CaptureError("Impossible de lire les dimensions de la fenêtre.")
        width, height = client.right - client.left, client.bottom - client.top
        if width <= 0 or height <= 0 or width * height > _MAX_PIXELS:
            raise CaptureError("Dimensions de fenêtre invalides.")

        window_dc = memory_dc = bitmap = previous = None
        try:
            window_dc = self.user32.GetDC(hwnd)
            memory_dc = self.gdi32.CreateCompatibleDC(window_dc) if window_dc else None
            bitmap = (
                self.gdi32.CreateCompatibleBitmap(window_dc, width, height) if memory_dc else None
            )
            if not bitmap:
                raise CaptureError("Impossible de préparer la capture GDI.")
            previous = self.gdi32.SelectObject(memory_dc, bitmap)
            if not self.user32.PrintWindow(hwnd, memory_dc, _PW_CLIENTONLY | _PW_RENDERFULLCONTENT):
                raise CaptureError("La fenêtre ne fournit pas d'image via PrintWindow.")
            self.gdi32.SelectObject(memory_dc, previous)
            previous = None
            info = _BitmapInfo()
            info.bmiHeader.biSize = ctypes.sizeof(_BitmapInfoHeader)
            info.bmiHeader.biWidth = width
            info.bmiHeader.biHeight = -height  # lignes de haut en bas
            info.bmiHeader.biPlanes = 1
            info.bmiHeader.biBitCount = 32
            buffer = ctypes.create_string_buffer(width * height * 4)
            if (
                self.gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer, ctypes.byref(info), 0)
                != height
            ):
                raise CaptureError("La lecture des pixels GDI a échoué.")
            return np.frombuffer(buffer.raw, dtype=np.uint8).reshape(height, width, 4)
        finally:
            if previous:
                self.gdi32.SelectObject(memory_dc, previous)
            if bitmap:
                self.gdi32.DeleteObject(bitmap)
            if memory_dc:
                self.gdi32.DeleteDC(memory_dc)
            if window_dc:
                self.user32.ReleaseDC(hwnd, window_dc)
