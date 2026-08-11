"""Command-line entry point for ForceDeleteFile."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

try:
    from .delete_service import DeleteStatus, ForceDeleteService
    from .windows_lock import LockingProcess
except ImportError:  # Allow `python cli.py`.
    from delete_service import DeleteStatus, ForceDeleteService
    from windows_lock import LockingProcess


def _confirm(prompt: str) -> bool:
    try:
        return input(f"{prompt} [y/N]: ").strip().lower() in {"y", "yes"}
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="查询占用进程并永久删除 Windows 文件。"
    )
    parser.add_argument("files", nargs="+", type=Path, help="要删除的文件")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="跳过确认，包括关闭占用程序的确认",
    )
    parser.add_argument(
        "--no-close",
        action="store_true",
        help="发现占用程序时不尝试关闭",
    )
    parser.add_argument(
        "--schedule-on-reboot",
        action="store_true",
        help="无法立即删除时安排在重启后删除",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if not args.yes and not _confirm(
        f"将永久删除 {len(args.files)} 个文件，是否继续"
    ):
        print("操作已取消")
        return 2

    def logger(level: str, message: str) -> None:
        print(f"[{level}] {message}")

    def confirm_close(
        path: Path,
        processes: Sequence[LockingProcess],
    ) -> bool:
        if args.no_close:
            return False
        print(f"\n{path} 被以下程序占用:")
        for process in processes:
            print(
                f"  {process.display_name} | PID {process.pid} | "
                f"{process.type_name}"
            )
        return args.yes or _confirm("关闭这些程序后继续删除")

    service = ForceDeleteService(logger)
    results = [
        service.delete(
            path,
            confirm_close=confirm_close,
            schedule_on_reboot=args.schedule_on_reboot,
        )
        for path in args.files
    ]

    failures = sum(
        result.status in {DeleteStatus.FAILED, DeleteStatus.CANCELLED}
        for result in results
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

