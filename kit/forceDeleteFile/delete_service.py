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

    @staticmethod
    def _directory_info(path: Path) -> tuple[bool, bool]:
        info = path.lstat()
        attributes = getattr(info, "st_file_attributes", 0)
        directory = stat.S_ISDIR(info.st_mode) or bool(attributes & stat.FILE_ATTRIBUTE_DIRECTORY)
        link = stat.S_ISLNK(info.st_mode) or bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return directory, link

    def _remove_entry(self, path: Path) -> None:
        directory, _ = self._directory_info(path)
        if directory:
            path.rmdir()
        else:
            path.unlink()

    def _unlink(self, path: Path) -> OSError | None:
        try:
            self._remove_entry(path)
            return None
        except FileNotFoundError:
            return None
        except PermissionError as first_error:
            try:
                attributes = path.lstat().st_file_attributes
            except (AttributeError, OSError):
                return first_error
            if not attributes & stat.FILE_ATTRIBUTE_READONLY or attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                return first_error
            try:
                path.chmod(stat.S_IWRITE)
                self._log("INFO", "已清除只读属性，正在重试")
                self._remove_entry(path)
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
            if self._is_cancelled(cancelled):
                return last_error
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
        path = Path(os.path.abspath(Path(raw_path).expanduser()))
        self._log("INFO", f"开始处理: {path}")

        if self._is_cancelled(cancelled):
            return DeleteResult(path, DeleteStatus.CANCELLED, "操作已取消")

        if not self._path_exists(path):
            message = "路径不存在，跳过"
            self._log("WARNING", message)
            return DeleteResult(path, DeleteStatus.NOT_FOUND, message)

        if path.parent == path:
            message = "不允许删除磁盘或共享根目录"
            self._log("ERROR", message)
            return DeleteResult(path, DeleteStatus.FAILED, message)

        try:
            directory, link = self._directory_info(path)
            if directory and not link:
                # Enumerate only this directory; links/reparse points are handled as leaf entries.
                children = list(path.iterdir())
                failed = scheduled = 0
                for child in children:
                    if self._is_cancelled(cancelled):
                        return DeleteResult(path, DeleteStatus.CANCELLED, "操作已取消，已删除的内容不会恢复")
                    result = self.delete(child, confirm_close=confirm_close,
                                         schedule_on_reboot=schedule_on_reboot, cancelled=cancelled)
                    if result.status == DeleteStatus.CANCELLED:
                        return DeleteResult(path, DeleteStatus.CANCELLED, "操作已取消，已删除的内容不会恢复")
                    failed += result.status == DeleteStatus.FAILED
                    scheduled += result.status == DeleteStatus.SCHEDULED
                if failed:
                    message = f"文件夹未完全删除：{failed} 个子项失败；已处理的内容不会恢复"
                    self._log("ERROR", message)
                    return DeleteResult(path, DeleteStatus.FAILED, message)
                if self._is_cancelled(cancelled):
                    return DeleteResult(path, DeleteStatus.CANCELLED, "操作已取消，已删除的内容不会恢复")
                if scheduled:
                    # Windows processes deferred deletions in registration order: children first.
                    schedule_delete_after_reboot(path)
                    message = "文件夹剩余内容已登记为重启后删除（子项先于父目录）"
                    self._log("SUCCESS", message)
                    return DeleteResult(path, DeleteStatus.SCHEDULED, message)
        except OSError as error:
            message = f"处理路径失败: {error}"
            self._log("ERROR", message)
            return DeleteResult(path, DeleteStatus.FAILED, message, error=error)

        delete_error = self._unlink(path)
        if delete_error is None:
            message = "文件夹已永久删除" if directory else "文件已永久删除"
            self._log("SUCCESS", message)
            return DeleteResult(path, DeleteStatus.DELETED, message)

        self._log("WARNING", f"直接删除失败: {delete_error}")
        locking_processes: tuple[LockingProcess, ...] = ()

        try:
            # Restart Manager resolves resource paths; do not query a link's external target.
            locking_processes = () if link else find_locking_processes(path)
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

                if delete_error is None and not self._is_cancelled(cancelled):
                    message = "占用程序关闭后，目标已永久删除"
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
                message = "目标已登记为下次 Windows 启动时删除"
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
