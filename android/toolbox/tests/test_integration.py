"""Opt-in, real toolchain test using a self-contained synthetic package. No device access."""

import hashlib
import json
import os
import queue
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from android.toolbox import operations
from android.toolbox.services import Execution, Preferences, Task, Tools


@unittest.skipUnless(os.environ.get("TOOLBOX_INTEGRATION") == "1", "Set TOOLBOX_INTEGRATION=1 for real Java/Android tools")
class BuildIntegrationTests(unittest.TestCase):
    def test_analyze_build_sign_and_preserve_dex(self):
        with tempfile.TemporaryDirectory(prefix="toolbox integration ") as folder:
            root = Path(folder)
            preferences = Preferences(root / "settings")
            tools = Tools(preferences).snapshot()
            Tools.require(tools, "java", "keytool", "apktool", "build_tools")
            source = root / "source"
            shutil.copytree(Path(__file__).parent / "fixtures" / "sample", source)
            task = Task("integration", "gpcheck", None)
            context = Execution(task, queue.Queue(), preferences.logs / "integration.log")
            apk = root / "base.apk"
            context.run([tools["java"], "-jar", tools["apktool"], "b", source, "-o", apk])
            package = root / "fixture.xapk"
            metadata = {"package_name": "com.example.toolboxfixture", "name": "Toolbox Fixture",
                        "version_name": "1.0", "version_code": "1", "split_apks": [{"id": "base", "file": "base.apk"}]}
            with zipfile.ZipFile(package, "w") as archive:
                archive.write(apk, "base.apk")
                archive.writestr("manifest.json", json.dumps(metadata))
            original_digest = hashlib.sha256(package.read_bytes()).hexdigest()
            analysis = operations.analyze(context, package, root / "workspace", tools).value
            self.assertTrue(analysis.supported)
            self.assertTrue(analysis.provider_found)
            result = operations.build(context, analysis, tools, root / "key.jks", "test", "test-password").value
            self.assertTrue(result.patched_xapk.is_file())
            self.assertTrue(result.certificate_sha256)
            self.assertTrue(result.dex_hashes)
            self.assertTrue(all(item["unchanged"] for item in result.dex_hashes.values()))
            self.assertEqual(hashlib.sha256(package.read_bytes()).hexdigest(), original_digest)
            self.assertNotIn("com.pairip.licensecheck.LicenseContentProvider",
                             result.manifest_after.read_text(encoding="utf-8"))
            self.assertNotIn("test-password", context.log_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
