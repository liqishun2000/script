from __future__ import annotations

import ctypes
import os
import tempfile
import unittest
from ctypes import wintypes
from pathlib import Path

from kit.forceDeleteFile.windows_lock import find_locking_processes


GENERIC_READ = 0x80000000
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class RestartManagerTests(unittest.TestCase):
    def test_finds_process_with_exclusive_file_handle(self) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "locked.txt")
            path.write_text("test", encoding="utf-8")
            handle = kernel32.CreateFileW(
                str(path),
                GENERIC_READ,
                0,
                None,
                OPEN_EXISTING,
                FILE_ATTRIBUTE_NORMAL,
                None,
            )
            if handle == INVALID_HANDLE_VALUE:
                raise ctypes.WinError(ctypes.get_last_error())

            try:
                processes = find_locking_processes(path)
            finally:
                kernel32.CloseHandle(handle)

            owner = next(
                process for process in processes if process.pid == os.getpid()
            )
            self.assertTrue(owner.is_unsafe_to_shutdown)


if __name__ == "__main__":
    unittest.main()

