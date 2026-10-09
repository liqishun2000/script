from __future__ import annotations

import tempfile
import unittest
import stat
from pathlib import Path
from unittest.mock import patch

from kit.forceDeleteFile.delete_service import DeleteStatus, ForceDeleteService


class ForceDeleteServiceTests(unittest.TestCase):
    def test_deletes_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "delete-me.txt")
            path.write_text("test", encoding="utf-8")

            result = ForceDeleteService().delete(path)

            self.assertEqual(DeleteStatus.DELETED, result.status)
            self.assertFalse(path.exists())

    def test_missing_file_is_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "missing.txt")

            result = ForceDeleteService().delete(path)

            self.assertEqual(DeleteStatus.NOT_FOUND, result.status)

    def test_deletes_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "folder")
            path.mkdir()

            result = ForceDeleteService().delete(path)

            self.assertEqual(DeleteStatus.DELETED, result.status)
            self.assertFalse(path.exists())

    def test_deletes_nested_directory_with_readonly_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "测试 文件夹")
            child = root / "nested"
            child.mkdir(parents=True)
            (child / "readonly.txt").write_text("test")
            (child / "readonly.txt").chmod(stat.S_IREAD)
            (root / "empty").mkdir()
            self.assertEqual(ForceDeleteService().delete(root).status, DeleteStatus.DELETED)
            self.assertFalse(root.exists())

    def test_directory_junction_does_not_delete_target(self) -> None:
        import _winapi
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root, outside = base / "delete", base / "keep"
            root.mkdir()
            outside.mkdir()
            target = outside / "keep.txt"
            target.write_text("preserve")
            _winapi.CreateJunction(str(outside), str(root / "junction"))
            self.assertEqual(ForceDeleteService().delete(root).status, DeleteStatus.DELETED)
            self.assertEqual(target.read_text(), "preserve")

    def test_failed_child_keeps_parent_and_reports_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "folder")
            root.mkdir()
            child = root / "locked.txt"
            child.write_text("test")
            service = ForceDeleteService()
            with patch.object(service, "_unlink", return_value=PermissionError("locked")), patch(
                "kit.forceDeleteFile.delete_service.find_locking_processes", return_value=()
            ):
                result = service.delete(root)
            self.assertEqual(result.status, DeleteStatus.FAILED)
            self.assertTrue(child.exists())

    def test_reboot_deletion_registers_children_before_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "folder")
            nested = root / "nested"
            nested.mkdir(parents=True)
            child = nested / "locked.txt"
            child.write_text("test")
            service = ForceDeleteService()
            with patch.object(service, "_unlink", return_value=PermissionError("locked")), patch(
                "kit.forceDeleteFile.delete_service.find_locking_processes", return_value=()
            ), patch("kit.forceDeleteFile.delete_service.schedule_delete_after_reboot") as schedule:
                result = service.delete(root, schedule_on_reboot=True)
            self.assertEqual(result.status, DeleteStatus.SCHEDULED)
            self.assertEqual([call.args[0] for call in schedule.call_args_list], [child, nested, root])

    def test_cancel_mid_directory_stops_remaining_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "folder")
            root.mkdir()
            for name in ("one", "two"):
                (root / name).write_text("test")
            service = ForceDeleteService()
            removed = []
            original = service._unlink
            def remove(path):
                result = original(path)
                removed.append(path)
                return result
            with patch.object(service, "_unlink", side_effect=remove):
                result = service.delete(root, cancelled=lambda: bool(removed))
            self.assertEqual(result.status, DeleteStatus.CANCELLED)
            self.assertEqual(len(list(root.iterdir())), 1)

    def test_refuses_drive_root(self) -> None:
        root = Path.cwd().anchor
        self.assertEqual(ForceDeleteService().delete(root).status, DeleteStatus.FAILED)

    def test_clears_readonly_attribute_before_deleting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "readonly.txt")
            path.write_text("test", encoding="utf-8")
            path.chmod(stat.S_IREAD)

            result = ForceDeleteService().delete(path)

            self.assertEqual(DeleteStatus.DELETED, result.status)
            self.assertFalse(path.exists())

    def test_schedules_delete_after_reboot_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "locked.txt")
            path.write_text("test", encoding="utf-8")
            service = ForceDeleteService()

            with (
                patch.object(
                    service,
                    "_unlink",
                    return_value=PermissionError("access denied"),
                ),
                patch(
                    "kit.forceDeleteFile.delete_service.find_locking_processes",
                    return_value=(),
                ),
                patch(
                    "kit.forceDeleteFile.delete_service.schedule_delete_after_reboot"
                ) as schedule,
            ):
                result = service.delete(path, schedule_on_reboot=True)

            self.assertEqual(DeleteStatus.SCHEDULED, result.status)
            schedule.assert_called_once_with(path.absolute())


if __name__ == "__main__":
    unittest.main()
