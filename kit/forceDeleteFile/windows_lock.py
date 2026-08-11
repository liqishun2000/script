"""Small ctypes wrappers around Windows Restart Manager and MoveFileEx."""

from __future__ import annotations

import ctypes
import os
from contextlib import AbstractContextManager
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


if os.name != "nt":
    raise RuntimeError("forceDeleteFile only supports Windows")


ERROR_SUCCESS = 0
ERROR_MORE_DATA = 234
CCH_RM_MAX_APP_NAME = 255
CCH_RM_MAX_SVC_NAME = 63
CCH_RM_SESSION_KEY = 32
RM_FORCE_SHUTDOWN = 0x1
RM_CRITICAL_APP = 1000
MOVEFILE_DELAY_UNTIL_REBOOT = 0x4


class RM_UNIQUE_PROCESS(ctypes.Structure):
    _fields_ = [
        ("dwProcessId", wintypes.DWORD),
        ("ProcessStartTime", wintypes.FILETIME),
    ]


class RM_PROCESS_INFO(ctypes.Structure):
    _fields_ = [
        ("Process", RM_UNIQUE_PROCESS),
        ("strAppName", wintypes.WCHAR * (CCH_RM_MAX_APP_NAME + 1)),
        ("strServiceShortName", wintypes.WCHAR * (CCH_RM_MAX_SVC_NAME + 1)),
        ("ApplicationType", wintypes.UINT),
        ("AppStatus", wintypes.ULONG),
        ("TSSessionId", wintypes.DWORD),
        ("bRestartable", wintypes.BOOL),
    ]


APP_TYPE_NAMES = {
    0: "未知程序",
    1: "桌面程序",
    2: "窗口程序",
    3: "Windows 服务",
    4: "文件资源管理器",
    5: "控制台程序",
    RM_CRITICAL_APP: "系统关键进程",
}


@dataclass(frozen=True, slots=True)
class LockingProcess:
    pid: int
    application_name: str
    service_name: str
    application_type: int
    session_id: int
    restartable: bool

    @property
    def type_name(self) -> str:
        return APP_TYPE_NAMES.get(self.application_type, "其他程序")

    @property
    def display_name(self) -> str:
        return self.application_name or self.service_name or f"PID {self.pid}"

    @property
    def is_unsafe_to_shutdown(self) -> bool:
        return (
            self.pid in {0, 4, os.getpid()}
            or self.application_type == RM_CRITICAL_APP
        )


class RestartManagerError(OSError):
    def __init__(self, operation: str, error_code: int) -> None:
        detail = ctypes.FormatError(error_code).strip()
        super().__init__(error_code, f"{operation} 失败: {detail}")
        self.operation = operation
        self.error_code = error_code


class UnsafeLockingProcessError(RuntimeError):
    def __init__(self, processes: Iterable[LockingProcess]) -> None:
        self.processes = tuple(processes)
        names = ", ".join(
            f"{process.display_name} (PID {process.pid})"
            for process in self.processes
        )
        super().__init__(f"拒绝关闭系统关键进程或本程序: {names}")


_rstrtmgr = ctypes.WinDLL("Rstrtmgr", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)

_rstrtmgr.RmStartSession.argtypes = (
    ctypes.POINTER(wintypes.DWORD),
    wintypes.DWORD,
    wintypes.LPWSTR,
)
_rstrtmgr.RmStartSession.restype = wintypes.DWORD

_rstrtmgr.RmRegisterResources.argtypes = (
    wintypes.DWORD,
    wintypes.UINT,
    ctypes.POINTER(wintypes.LPCWSTR),
    wintypes.UINT,
    ctypes.c_void_p,
    wintypes.UINT,
    ctypes.c_void_p,
)
_rstrtmgr.RmRegisterResources.restype = wintypes.DWORD

_rstrtmgr.RmGetList.argtypes = (
    wintypes.DWORD,
    ctypes.POINTER(wintypes.UINT),
    ctypes.POINTER(wintypes.UINT),
    ctypes.POINTER(RM_PROCESS_INFO),
    ctypes.POINTER(wintypes.DWORD),
)
_rstrtmgr.RmGetList.restype = wintypes.DWORD

_rstrtmgr.RmShutdown.argtypes = (
    wintypes.DWORD,
    wintypes.ULONG,
    ctypes.c_void_p,
)
_rstrtmgr.RmShutdown.restype = wintypes.DWORD

_rstrtmgr.RmEndSession.argtypes = (wintypes.DWORD,)
_rstrtmgr.RmEndSession.restype = wintypes.DWORD

_kernel32.MoveFileExW.argtypes = (
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
)
_kernel32.MoveFileExW.restype = wintypes.BOOL

_shell32.IsUserAnAdmin.argtypes = ()
_shell32.IsUserAnAdmin.restype = wintypes.BOOL


def _raise_on_error(operation: str, result: int) -> None:
    if result != ERROR_SUCCESS:
        raise RestartManagerError(operation, result)


class RestartManagerSession(AbstractContextManager["RestartManagerSession"]):
    def __init__(self) -> None:
        self.handle = wintypes.DWORD()
        session_key = ctypes.create_unicode_buffer(CCH_RM_SESSION_KEY + 1)
        result = _rstrtmgr.RmStartSession(
            ctypes.byref(self.handle), 0, session_key
        )
        _raise_on_error("RmStartSession", result)
        self._closed = False

    def register_files(self, paths: Iterable[os.PathLike[str] | str]) -> None:
        resolved = tuple(str(Path(path).resolve()) for path in paths)
        if not resolved:
            raise ValueError("至少需要注册一个文件")

        file_array = (wintypes.LPCWSTR * len(resolved))(*resolved)
        result = _rstrtmgr.RmRegisterResources(
            self.handle,
            len(resolved),
            file_array,
            0,
            None,
            0,
            None,
        )
        _raise_on_error("RmRegisterResources", result)

    def get_locking_processes(self) -> tuple[LockingProcess, ...]:
        needed = wintypes.UINT(0)
        count = wintypes.UINT(0)
        reboot_reasons = wintypes.DWORD(0)

        result = _rstrtmgr.RmGetList(
            self.handle,
            ctypes.byref(needed),
            ctypes.byref(count),
            None,
            ctypes.byref(reboot_reasons),
        )
        if result == ERROR_SUCCESS:
            return ()
        if result != ERROR_MORE_DATA:
            raise RestartManagerError("RmGetList", result)

        while True:
            count = wintypes.UINT(needed.value)
            process_array = (RM_PROCESS_INFO * count.value)()
            result = _rstrtmgr.RmGetList(
                self.handle,
                ctypes.byref(needed),
                ctypes.byref(count),
                process_array,
                ctypes.byref(reboot_reasons),
            )
            if result == ERROR_MORE_DATA:
                continue
            _raise_on_error("RmGetList", result)
            return tuple(
                LockingProcess(
                    pid=int(info.Process.dwProcessId),
                    application_name=str(info.strAppName),
                    service_name=str(info.strServiceShortName),
                    application_type=int(info.ApplicationType),
                    session_id=int(info.TSSessionId),
                    restartable=bool(info.bRestartable),
                )
                for info in process_array[: count.value]
            )

    def shutdown_locking_processes(self, force: bool = True) -> None:
        processes = self.get_locking_processes()
        unsafe = tuple(
            process for process in processes if process.is_unsafe_to_shutdown
        )
        if unsafe:
            raise UnsafeLockingProcessError(unsafe)

        flags = RM_FORCE_SHUTDOWN if force else 0
        result = _rstrtmgr.RmShutdown(self.handle, flags, None)
        _raise_on_error("RmShutdown", result)

    def close(self) -> None:
        if not self._closed:
            _rstrtmgr.RmEndSession(self.handle)
            self._closed = True

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


def find_locking_processes(
    path: os.PathLike[str] | str,
) -> tuple[LockingProcess, ...]:
    with RestartManagerSession() as session:
        session.register_files((path,))
        return session.get_locking_processes()


def shutdown_processes_locking_file(
    path: os.PathLike[str] | str,
    *,
    force: bool = True,
) -> None:
    # Use a fresh session so the shutdown decision is based on current owners.
    with RestartManagerSession() as session:
        session.register_files((path,))
        session.shutdown_locking_processes(force=force)


def schedule_delete_after_reboot(path: os.PathLike[str] | str) -> None:
    resolved = str(Path(path).resolve())
    ctypes.set_last_error(0)
    if not _kernel32.MoveFileExW(
        resolved, None, MOVEFILE_DELAY_UNTIL_REBOOT
    ):
        raise ctypes.WinError(ctypes.get_last_error())


def is_current_process_elevated() -> bool:
    try:
        return bool(_shell32.IsUserAnAdmin())
    except OSError:
        return False

