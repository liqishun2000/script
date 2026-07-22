from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from gpcheck_core import (
    ANDROID_NS,
    PAIRIP_APPLICATION,
    PAIRIP_PROVIDER,
    PLAY_STORE_PACKAGE,
    AnalysisResult,
    CommandError,
    DeviceInfo,
    GpCheckError,
    PatchAction,
    Toolchain,
    _build_install_command,
    _find_wrapper_parent,
    _parse_manifest_xml,
    _parse_installer_package,
    _patch_manifest,
    _safe_extract_zip,
    choose_device_apks,
    install_original_as_play_store_and_verify,
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


class InstallerStrategyTests(unittest.TestCase):
    def test_install_command_sets_installer_before_apk_paths(self) -> None:
        command = _build_install_command(
            [Path("base.apk"), Path("config.en.apk")],
            PLAY_STORE_PACKAGE,
        )
        self.assertEqual(
            command,
            [
                "install-multiple",
                "--no-incremental",
                "-r",
                "-i",
                PLAY_STORE_PACKAGE,
                "base.apk",
                "config.en.apk",
            ],
        )

    def test_parse_installer_requires_exact_package(self) -> None:
        output = (
            "package:com.example.cleaner.beta installer=com.example.store\n"
            "package:com.example.cleaner  installer=com.android.vending\n"
        )
        self.assertEqual(
            _parse_installer_package("com.example.cleaner", output),
            PLAY_STORE_PACKAGE,
        )

    def test_original_strategy_verifies_recorded_play_store_installer(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = root / "original"
            original.mkdir()
            base_apk = original / "base.apk"
            base_apk.write_bytes(b"apk")
            placeholder = root / "placeholder"
            placeholder.write_bytes(b"")
            analysis = AnalysisResult(
                xapk_path=placeholder,
                workspace=root,
                extracted_dir=original,
                decoded_dir=root,
                manifest_json_path=placeholder,
                manifest_xml_path=placeholder,
                base_apk_path=base_apk,
                base_apk_name="base.apk",
                package_name="com.example.cleaner",
                app_name="Example",
                version_name="1.0",
                version_code="1",
                main_activity="com.example.cleaner.MainActivity",
                application_name="",
                split_apks=[{"id": "base", "file": "base.apk"}],
            )
            device = DeviceInfo(
                serial="serial",
                model="phone",
                sdk="33",
                abi_list=["arm64-v8a"],
                density=420,
                locale="en-US",
            )
            toolchain = Toolchain(
                java=Path("java"),
                keytool=Path("keytool"),
                adb=Path("adb"),
                apktool_jar=Path("apktool.jar"),
                build_tools=Path("build-tools"),
            )
            install_commands: list[list[str]] = []

            def fake_adb(_toolchain, args, _log, check=True, stream_output=True):
                del _toolchain, check, stream_output
                if args[:3] == ["shell", "pm", "path"]:
                    return 0, "package:/system/priv-app/Phonesky/Phonesky.apk"
                if args[0] == "install-multiple":
                    install_commands.append(args)
                    return 0, "Success"
                if args[:5] == ["shell", "pm", "list", "packages", "-i"]:
                    return 0, "package:com.example.cleaner installer=com.android.vending"
                if args[:3] == ["shell", "dumpsys", "window"]:
                    return 0, "mCurrentFocus=com.example.cleaner/.MainActivity"
                if args[:3] == ["shell", "pidof", "com.example.cleaner"]:
                    return 0, "1234"
                return 0, ""

            with (
                patch("gpcheck_core.read_device_info", return_value=device),
                patch("gpcheck_core._adb", side_effect=fake_adb),
                patch("gpcheck_core.time.sleep"),
            ):
                result = install_original_as_play_store_and_verify(
                    analysis,
                    toolchain,
                    grant_cleaner_permissions=False,
                )

            self.assertTrue(result.success)
            self.assertTrue(result.installer_verified)
            self.assertEqual(result.installer_package, PLAY_STORE_PACKAGE)
            self.assertEqual(result.strategy, "play_store_installer")
            self.assertEqual(install_commands[0][3:5], ["-i", PLAY_STORE_PACKAGE])


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
