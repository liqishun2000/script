from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from gpcheck_core import (
    ANDROID_NS,
    PAIRIP_APPLICATION,
    PAIRIP_PROVIDER,
    AnalysisResult,
    CommandError,
    DeviceInfo,
    GpCheckError,
    PatchAction,
    _find_wrapper_parent,
    _parse_manifest_xml,
    _patch_manifest,
    _safe_extract_zip,
    choose_device_apks,
)


MANIFEST_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.example.cleaner">
    <application android:name="{application}">
        {provider}
        <activity android:name=".MainActivity" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
"""


class ManifestTests(unittest.TestCase):
    def test_parse_launcher_and_pairip_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "AndroidManifest.xml"
            path.write_text(
                MANIFEST_TEMPLATE.format(
                    application="com.example.BusinessApplication",
                    provider=(
                        '<provider android:name="com.pairip.licensecheck.LicenseContentProvider" '
                        'android:authorities="com.example.provider" android:exported="false" />'
                    ),
                ),
                encoding="utf-8",
            )
            parsed = _parse_manifest_xml(path, "com.example.cleaner")
            self.assertEqual(parsed["main_activity"], "com.example.cleaner.MainActivity")
            self.assertIn(PAIRIP_PROVIDER, parsed["providers"])

    def test_patch_application_and_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            decoded = root / "decoded"
            decoded.mkdir()
            manifest = decoded / "AndroidManifest.xml"
            manifest.write_text(
                MANIFEST_TEMPLATE.format(
                    application=PAIRIP_APPLICATION,
                    provider=(
                        '<provider android:name="com.pairip.licensecheck.LicenseContentProvider" '
                        'android:authorities="com.example.provider" android:exported="false" />'
                    ),
                ),
                encoding="utf-8",
            )
            placeholder = root / "placeholder"
            placeholder.write_bytes(b"")
            analysis = AnalysisResult(
                xapk_path=placeholder,
                workspace=root,
                extracted_dir=root,
                decoded_dir=decoded,
                manifest_json_path=placeholder,
                manifest_xml_path=manifest,
                base_apk_path=placeholder,
                base_apk_name="base.apk",
                package_name="com.example.cleaner",
                app_name="Example",
                version_name="1.0",
                version_code="1",
                main_activity="com.example.cleaner.MainActivity",
                application_name=PAIRIP_APPLICATION,
                original_application_name="com.example.BusinessApplication",
                provider_found=True,
                confidence="high",
                actions=[
                    PatchAction(
                        kind="restore_application",
                        description="restore",
                        old_value=PAIRIP_APPLICATION,
                        new_value="com.example.BusinessApplication",
                    ),
                    PatchAction(
                        kind="remove_pairip_provider",
                        description="remove provider",
                        old_value=PAIRIP_PROVIDER,
                    ),
                ],
            )
            _patch_manifest(analysis, root / "evidence")
            parsed = _parse_manifest_xml(manifest, "com.example.cleaner")
            self.assertEqual(parsed["application_name"], "com.example.BusinessApplication")
            self.assertNotIn(PAIRIP_PROVIDER, parsed["providers"])


class WrapperTests(unittest.TestCase):
    def test_extract_business_application_superclass(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            wrapper = (
                Path(temp)
                / "smali_classes2"
                / "com"
                / "pairip"
                / "application"
                / "Application.smali"
            )
            wrapper.parent.mkdir(parents=True)
            wrapper.write_text(
                ".class public Lcom/pairip/application/Application;\n"
                ".super Lgol/zli/mcc/FeiApplication;\n"
                ".method protected attachBaseContext(Landroid/content/Context;)V\n"
                "invoke-static {p1}, Lcom/pairip/licensecheck/LicenseClient;->checkLicense(Landroid/content/Context;)V\n"
                ".end method\n",
                encoding="utf-8",
            )
            parent, found_path, calls_check = _find_wrapper_parent(Path(temp))
            self.assertEqual(parent, "gol.zli.mcc.FeiApplication")
            self.assertEqual(found_path, wrapper)
            self.assertTrue(calls_check)


class SplitSelectionTests(unittest.TestCase):
    def test_aura_clean_device_set(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            entries = [
                {"id": "base", "file": "base.apk"},
                {"id": "config.armeabi_v7a", "file": "config.armeabi_v7a.apk"},
                {"id": "config.hdpi", "file": "config.hdpi.apk"},
                {"id": "config.en", "file": "config.en.apk"},
                {"id": "config.zh", "file": "config.zh.apk"},
            ]
            for entry in entries:
                (root / entry["file"]).write_bytes(b"apk")
            device = DeviceInfo(
                serial="serial",
                model="phone",
                sdk="33",
                abi_list=["arm64-v8a", "armeabi-v7a"],
                density=420,
                locale="en-US",
            )
            selected = choose_device_apks(entries, root, device)
            self.assertEqual(
                [path.name for path in selected],
                ["base.apk", "config.armeabi_v7a.apk", "config.hdpi.apk", "config.en.apk"],
            )


class ArchiveSafetyTests(unittest.TestCase):
    def test_rejects_zip_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive_path = root / "bad.xapk"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../outside.txt", "bad")
            with self.assertRaises(GpCheckError):
                _safe_extract_zip(archive_path, root / "output")


class LoggingSafetyTests(unittest.TestCase):
    def test_command_error_redacts_keystore_passwords(self) -> None:
        error = CommandError(
            ["apksigner", "--ks-pass", "pass:secret", "--key-pass", "pass:secret"],
            1,
            "failed",
        )
        self.assertNotIn("secret", str(error))
        self.assertIn("***", str(error))


if __name__ == "__main__":
    unittest.main()
