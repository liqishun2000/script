"""Windows handles for embedding only the scrcpy process owned by this app."""
import ctypes
import os
from ctypes import wintypes


def owned_window(pid):
    if os.name != "nt" or not pid:
        return 0
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    result = []

    @callback_type
    def visit(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title, len(title))
            if title.value.startswith("AndroidToolbox-"):
                result.append(int(hwnd))
                return False
        return True

    user32.EnumWindows(visit, 0)
    return result[0] if result else 0


def request_close(hwnd):
    if os.name == "nt" and hwnd:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE lets scrcpy clean its server and tunnel.


def focus_window(hwnd):
    if os.name != "nt" or not hwnd:
        return
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.SetFocus.argtypes = [wintypes.HWND]
    user32.SetFocus.restype = wintypes.HWND
    current = ctypes.windll.kernel32.GetCurrentThreadId()
    target = user32.GetWindowThreadProcessId(hwnd, None)
    if not target:
        return
    attached = target != current and user32.AttachThreadInput(current, target, True)
    try:
        user32.SetFocus(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(current, target, False)


def fit_window(hwnd, host, x, y, width, height):
    if os.name != "nt" or not hwnd:
        return
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.MapWindowPoints.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.POINTER(wintypes.POINT), wintypes.UINT]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, wintypes.UINT]
    bounds, client = wintypes.RECT(), wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(client)) or not user32.GetWindowRect(hwnd, ctypes.byref(bounds)):
        return
    parent = user32.GetParent(hwnd)
    if not parent:
        return
    origin = wintypes.POINT(bounds.left, bounds.top)
    user32.MapWindowPoints(None, parent, ctypes.byref(origin), 1)
    target = wintypes.POINT(x, y)
    user32.MapWindowPoints(host, parent, ctypes.byref(target), 1)
    if (origin.x, origin.y, client.right, client.bottom) != (target.x, target.y, width, height):
        user32.SetWindowPos(hwnd, None, target.x, target.y, width, height, 0x0014)
