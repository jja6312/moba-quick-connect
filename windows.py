"""Windows integration: scoped key hook, foreground metadata, executable discovery."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path

from PySide6.QtCore import QObject, Signal


def discover_moba():
    """Executable paths only. Do not inspect session/password/key file contents."""
    if os.name != "nt":
        return ""
    import winreg
    candidates = []
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    callback_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_t, wintypes.LPARAM]
    @callback_t
    def collect(hwnd, _):
        path = process_path(hwnd)
        if "mobaxterm" in Path(path).name.lower():
            candidates.append(path)
        return True
    user32.EnumWindows(collect, 0)
    if candidates:
        return candidates[0]
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for key in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\MobaXterm.exe",
                    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\MobaXterm.exe"):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    candidates.append(winreg.QueryValue(handle, None))
            except OSError:
                pass
    for root in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")):
        candidates.append(str(Path(root) / "Mobatek/MobaXterm/MobaXterm.exe"))
    return next((p for p in candidates if Path(p).is_file()), "")


def reveal_window(hwnd):
    """A Startup shortcut may request SW_HIDE on the first native ShowWindow."""
    if os.name == "nt":
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow(hwnd, 9)


def process_path(hwnd):
    if os.name != "nt":
        return ""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(0x1000, False, pid.value)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        path = ctypes.create_unicode_buffer(size.value)
        return path.value if kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)) else ""
    finally:
        kernel32.CloseHandle(handle)


def accepts_hotkey(vk, ctrl, shift, alt, path, own_exe, selected_moba):
    if vk != 0x20 or not ctrl or not shift or alt or not path:
        return False
    actual = os.path.normcase(os.path.abspath(path))
    own = os.path.normcase(os.path.abspath(own_exe))
    chosen = os.path.normcase(os.path.abspath(selected_moba)) if selected_moba else ""
    return actual == own or actual == chosen or Path(path).name.lower().startswith("mobaxterm")


class ScopedHotkey(QObject):
    triggered = Signal()

    def __init__(self, own_exe, selected_moba, parent=None):
        super().__init__(parent)
        self.own_exe, self.selected_moba = own_exe, selected_moba
        self.hook = None
        self.callback = None
        self.consumed = False
        self.last_moba_pid = None

    def start(self):
        if os.name != "nt":
            return
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        lresult = ctypes.c_ssize_t
        self.callback_type = ctypes.WINFUNCTYPE(lresult, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        self.user32.SetWindowsHookExW.argtypes = [ctypes.c_int, self.callback_type, wintypes.HINSTANCE, wintypes.DWORD]
        self.user32.SetWindowsHookExW.restype = wintypes.HHOOK
        self.user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        self.user32.CallNextHookEx.restype = lresult
        self.user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.user32.GetAsyncKeyState.restype = ctypes.c_short
        self.kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self.kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        class KeyboardEvent(ctypes.Structure):
            _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

        @self.callback_type
        def callback(code, message, pointer):
            try:
                if code >= 0:
                    event = ctypes.cast(pointer, ctypes.POINTER(KeyboardEvent)).contents
                    if event.vkCode == 0x20:
                        down = message in (0x100, 0x104)
                        up = message in (0x101, 0x105)
                        if up and self.consumed:
                            self.consumed = False
                            return 1
                        if down and self.consumed:
                            return 1
                        if down and self.user32.GetAsyncKeyState(0x11) & 0x8000 and self.user32.GetAsyncKeyState(0x10) & 0x8000:
                            path = process_path(self.user32.GetForegroundWindow())
                            if accepts_hotkey(event.vkCode, True, True, bool(self.user32.GetAsyncKeyState(0x12) & 0x8000),
                                              path, self.own_exe, self.selected_moba):
                                if Path(path).name.lower().startswith("mobaxterm"):
                                    pid = wintypes.DWORD()
                                    self.user32.GetWindowThreadProcessId(self.user32.GetForegroundWindow(), ctypes.byref(pid))
                                    self.last_moba_pid = pid.value
                                self.consumed = True
                                self.triggered.emit()
                                return 1
            except Exception:
                # Never interrupt ordinary keyboard input if metadata is unavailable.
                pass
            return self.user32.CallNextHookEx(self.hook, code, message, pointer)
        self.callback = callback
        self.hook = self.user32.SetWindowsHookExW(13, self.callback, self.kernel32.GetModuleHandleW(None), 0)
        if not self.hook:
            raise OSError(ctypes.get_last_error(), "Ctrl+Shift+Space 단축키를 등록하지 못했습니다.")

    def stop(self):
        if self.hook:
            self.user32.UnhookWindowsHookEx(self.hook)
            self.hook = None
