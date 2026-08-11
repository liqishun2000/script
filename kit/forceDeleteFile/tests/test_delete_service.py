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

    def test_refuses_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "folder")
            path.mkdir()

            result = ForceDeleteService().delete(path)

            self.assertEqual(DeleteStatus.FAILED, result.status)
            self.assertTrue(path.exists())

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
