"""Deletion workflow used by both the command line and desktop UI."""

from __future__ import annotations

import os
import stat
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Sequence

try:
    from .windows_lock import (
        LockingProcess,
        RestartManagerError,
        UnsafeLockingProcessError,
        find_locking_processes,
        schedule_delete_after_reboot,
        shutdown_processes_locking_file,
    )
except ImportError:  # Allow direct execution from this directory.
    from windows_lock import (
        LockingProcess,
        RestartManagerError,
        UnsafeLockingProcessError,
        find_locking_processes,
        schedule_delete_after_reboot,
        shutdown_processes_locking_file,
    )


LogCallback = Callable[[str, str], None]
LockDecisionCallback = Callable[[Path, Sequence[LockingProcess]], bool]
CancelCallback = Callable[[], bool]


class DeleteStatus(str, Enum):
    DELETED = "deleted"
    NOT_FOUND = "not_found"
    SCHEDULED = "scheduled"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class DeleteResult:
    path: Path
    status: DeleteStatus
    message: str
    locking_processes: tuple[LockingProcess, ...] = ()
    error: BaseException | None = None


class ForceDeleteService:
    def __init__(self, logger: LogCallback | None = None) -> None:
        self._logger = logger or (lambda level, message: None)

    def _log(self, level: str, message: str) -> None:
        self._logger(level, message)

    @staticmethod
    def _is_cancelled(callback: CancelCallback | None) -> bool:
        return bool(callback and callback())

    @staticmethod
    def _path_exists(path: Path) -> bool:
        return os.path.lexists(path)

    def _unlink(self, path: Path) -> OSError | None:
        try:
            path.unlink()
            return None
        except FileNotFoundError:
            return None
        except PermissionError as first_error:
            try:
                attributes = path.stat().st_file_attributes
            except (AttributeError, OSError):
                return first_error
            if not attributes & stat.FILE_ATTRIBUTE_READONLY:
                return first_error
            try:
                path.chmod(stat.S_IWRITE)
                self._log("INFO", "已清除只读属性，正在重试")
                path.unlink()
                return None
            except FileNotFoundError:
                return None
            except OSError as retry_error:
                return retry_error
        except OSError as error:
            return error

    def _retry_unlink(
        self,
        path: Path,
        cancelled: CancelCallback | None,
    ) -> OSError | None:
        last_error: OSError | None = None
        for delay in (0.0, 0.15, 0.4, 0.8):
            if self._is_cancelled(cancelled):
                return last_error
            if delay:
                time.sleep(delay)
            last_error = self._unlink(path)
            if last_error is None:
                return None
        return last_error

    def delete(
        self,
        raw_path: os.PathLike[str] | str,
        *,
        confirm_close: LockDecisionCallback | None = None,
        schedule_on_reboot: bool = False,
        cancelled: CancelCallback | None = None,
    ) -> DeleteResult:
        path = Path(raw_path).expanduser().absolute()
        self._log("INFO", f"开始处理: {path}")

        if self._is_cancelled(cancelled):
            return DeleteResult(path, DeleteStatus.CANCELLED, "操作已取消")

        if not self._path_exists(path):
            message = "文件不存在，跳过"
            self._log("WARNING", message)
            return DeleteResult(path, DeleteStatus.NOT_FOUND, message)

        if path.is_dir() and not path.is_symlink():
            message = "当前版本只删除文件，不处理文件夹"
            self._log("ERROR", message)
            return DeleteResult(path, DeleteStatus.FAILED, message)

        delete_error = self._unlink(path)
        if delete_error is None:
            message = "文件已永久删除"
            self._log("SUCCESS", message)
            return DeleteResult(path, DeleteStatus.DELETED, message)

        self._log("WARNING", f"直接删除失败: {delete_error}")
        locking_processes: tuple[LockingProcess, ...] = ()

        try:
            locking_processes = find_locking_processes(path)
        except RestartManagerError as error:
            self._log("WARNING", f"无法查询占用进程: {error}")

        if locking_processes:
            for process in locking_processes:
                self._log(
                    "WARNING",
                    "占用者: "
                    f"{process.display_name} (PID {process.pid}, "
                    f"{process.type_name})",
                )

            should_close = bool(
                confirm_close and confirm_close(path, locking_processes)
            )
            if should_close and not self._is_cancelled(cancelled):
                self._log("INFO", "正在请求关闭占用程序")
                try:
                    shutdown_processes_locking_file(path, force=True)
                    delete_error = self._retry_unlink(path, cancelled)
                except UnsafeLockingProcessError as error:
                    delete_error = PermissionError(str(error))
                    self._log("ERROR", str(error))
                except (RestartManagerError, OSError) as error:
                    delete_error = error
                    self._log("ERROR", f"关闭占用程序失败: {error}")

                if delete_error is None:
                    message = "占用程序关闭后，文件已永久删除"
                    self._log("SUCCESS", message)
                    return DeleteResult(
                        path,
                        DeleteStatus.DELETED,
                        message,
                        locking_processes,
                    )
            else:
                self._log("INFO", "用户未允许关闭占用程序")
        else:
            self._log(
                "WARNING",
                "未发现普通占用进程，可能是权限、ACL 或内核驱动限制",
            )

        if self._is_cancelled(cancelled):
            return DeleteResult(
                path,
                DeleteStatus.CANCELLED,
                "操作已取消",
                locking_processes,
                delete_error,
            )

        if schedule_on_reboot:
            self._log("INFO", "正在登记为重启后删除")
            try:
                schedule_delete_after_reboot(path)
            except OSError as error:
                delete_error = error
                self._log("ERROR", f"登记重启后删除失败: {error}")
            else:
                message = "文件将在下次 Windows 启动时删除"
                self._log("SUCCESS", message)
                return DeleteResult(
                    path,
                    DeleteStatus.SCHEDULED,
                    message,
                    locking_processes,
                )

        detail = str(delete_error) if delete_error else "未知错误"
        message = f"删除失败: {detail}"
        self._log("ERROR", message)
        return DeleteResult(
            path,
            DeleteStatus.FAILED,
            message,
            locking_processes,
            delete_error,
        )
