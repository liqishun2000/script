from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable
import xml.etree.ElementTree as ET


ANDROID_NS = "http://schemas.android.com/apk/res/android"
ANDROID_NAME = f"{{{ANDROID_NS}}}name"
ET.register_namespace("android", ANDROID_NS)

PAIRIP_APPLICATION = "com.pairip.application.Application"
PAIRIP_PROVIDER = "com.pairip.licensecheck.LicenseContentProvider"
PAIRIP_LICENSE_ACTIVITY = "com.pairip.licensecheck.LicenseActivity"
PLAY_STORE_PACKAGE = "com.android.vending"

LogFn = Callable[[str], None]


class GpCheckError(RuntimeError):
    pass


class CommandError(GpCheckError):
    def __init__(self, command: list[str], returncode: int, output: str):
        safe_command = _redact_command(command)
        super().__init__(f"Command failed ({returncode}): {subprocess.list2cmdline(safe_command)}")
        self.command = command
        self.returncode = returncode
        self.output = output


@dataclass
class Toolchain:
    java: Path
    keytool: Path
    adb: Path
    apktool_jar: Path
    build_tools: Path

    @property
    def zipalign(self) -> Path:
        return self.build_tools / "zipalign.exe"

    @property
    def apksigner_jar(self) -> Path:
        return self.build_tools / "lib" / "apksigner.jar"

    def validate_analysis(self) -> None:
        _assert_file(self.java, "java")
        _assert_file(self.apktool_jar, "Apktool JAR")

    def validate_build(self) -> None:
        self.validate_analysis()
        _assert_file(self.keytool, "keytool")
        _assert_file(self.zipalign, "zipalign")
        _assert_file(self.apksigner_jar, "apksigner.jar")

    def validate_device(self) -> None:
        _assert_file(self.adb, "adb")


@dataclass
class PatchAction:
    kind: str
    description: str
    old_value: str = ""
    new_value: str = ""


@dataclass
class AnalysisResult:
    xapk_path: Path
    workspace: Path
    extracted_dir: Path
    decoded_dir: Path
    manifest_json_path: Path
    manifest_xml_path: Path
    base_apk_path: Path
    base_apk_name: str
    package_name: str
    app_name: str
    version_name: str
    version_code: str
    main_activity: str
    application_name: str
    original_application_name: str = ""
    provider_found: bool = False
    pairip_activity_found: bool = False
    confidence: str = "unsupported"
    actions: list[PatchAction] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    split_apks: list[dict] = field(default_factory=list)
    xapk_sha256: str = ""

    @property
    def supported(self) -> bool:
        return bool(self.actions) and self.confidence in {"high", "medium"}

    def serializable(self) -> dict:
        value = asdict(self)
        for key in (
            "xapk_path",
            "workspace",
            "extracted_dir",
            "decoded_dir",
            "manifest_json_path",
            "manifest_xml_path",
            "base_apk_path",
        ):
            value[key] = str(value[key])
        value["supported"] = self.supported
        return value


@dataclass
class BuildResult:
    output_dir: Path
    signed_apk_dir: Path
    patched_xapk: Path
    dex_hashes: dict[str, dict[str, str | bool]]
    certificate_sha256: str
    signed_apks: list[Path]
    manifest_before: Path
    manifest_after: Path


@dataclass
class DeviceInfo:
    serial: str
    model: str
    sdk: str
    abi_list: list[str]
    density: int
    locale: str


@dataclass
class InstallResult:
    success: bool
    selected_apks: list[Path]
    foreground: str
    pid: str
    suspicious_logs: list[str]
    screenshot: Path | None
    output: str
    strategy: str = "manifest_patch"
    requested_installer: str = ""
    installer_package: str = ""
    installer_verified: bool = True


def _null_log(_: str) -> None:
    return


def _redact_command(command: Iterable[str | os.PathLike[str]]) -> list[str]:
    values = [str(item) for item in command]
    for index, value in enumerate(values[:-1]):
        if value in {"--ks-pass", "--key-pass", "-storepass", "-keypass"}:
            values[index + 1] = "***"
    return values


def _assert_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise GpCheckError(f"{label} not found: {path}")


def _version_key(path: Path) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", path.name)
    return tuple(int(value) for value in numbers) or (0,)


def discover_toolchain(app_root: Path) -> Toolchain:
    java = Path(shutil.which("java") or "java")
    keytool = Path(shutil.which("keytool") or "keytool")
    adb = Path(shutil.which("adb") or "adb")

    apktool_candidates: list[Path] = []
    if os.environ.get("APKTOOL_JAR"):
        apktool_candidates.append(Path(os.environ["APKTOOL_JAR"]))
    apktool_candidates.extend(sorted((app_root / "tools").glob("apktool*.jar"), reverse=True))

    user_profile = Path(os.environ.get("USERPROFILE", "C:/Users/a"))
    apktool_candidates.extend(
        sorted((user_profile / "auraclean_analysis" / "tools").glob("apktool*.jar"), reverse=True)
    )
    apktool_jar = next((item for item in apktool_candidates if item.is_file()), Path())

    sdk_roots: list[Path] = []
    for env_name in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        if os.environ.get(env_name):
            sdk_roots.append(Path(os.environ[env_name]))
    if os.environ.get("LOCALAPPDATA"):
        sdk_roots.append(Path(os.environ["LOCALAPPDATA"]) / "Android" / "Sdk")

    build_tool_dirs: list[Path] = []
    for sdk_root in sdk_roots:
        build_root = sdk_root / "build-tools"
        if build_root.is_dir():
            build_tool_dirs.extend(item for item in build_root.iterdir() if item.is_dir())
    build_tools = max(build_tool_dirs, key=_version_key) if build_tool_dirs else Path()

    return Toolchain(
        java=java,
        keytool=keytool,
        adb=adb,
        apktool_jar=apktool_jar,
        build_tools=build_tools,
    )


def run_command(
    command: Iterable[str | os.PathLike[str]],
    log: LogFn = _null_log,
    cwd: Path | None = None,
    check: bool = True,
    stream_output: bool = True,
) -> tuple[int, str]:
    args = [str(item) for item in command]
    display_args = _redact_command(args)
    display = subprocess.list2cmdline(display_args)
    log(f"> {display}")

    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        args,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )

    lines: list[str] = []
    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.rstrip()
        lines.append(line)
        if line and stream_output:
            log(line)
    returncode = process.wait()
    output = "\n".join(lines)
    if check and returncode != 0:
        raise CommandError(args, returncode, output)
    return returncode, output


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _safe_extract_zip(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    destination_resolved = destination.resolve()
    with zipfile.ZipFile(source) as archive:
        for info in archive.infolist():
            candidate = (destination / info.filename).resolve()
            try:
                candidate.relative_to(destination_resolved)
            except ValueError as exc:
                raise GpCheckError(f"Unsafe path in XAPK: {info.filename}") from exc
        archive.extractall(destination)


def _new_workspace(root: Path, xapk_path: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", xapk_path.stem).strip("._") or "xapk"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = root / f"{stem}-{timestamp}"
    counter = 1
    while candidate.exists():
        candidate = root / f"{stem}-{timestamp}-{counter}"
        counter += 1
    candidate.mkdir()
    return candidate


def _resolve_component(package_name: str, class_name: str) -> str:
    if not class_name:
        return ""
    if class_name.startswith("."):
        return package_name + class_name
    if "." not in class_name:
        return package_name + "." + class_name
    return class_name


def _parse_manifest_xml(manifest_path: Path, package_name: str) -> dict:
    tree = ET.parse(manifest_path)
    root = tree.getroot()
    application = root.find("application")
    if application is None:
        raise GpCheckError("Decoded AndroidManifest.xml has no <application> element.")

    providers = [item.get(ANDROID_NAME, "") for item in application.findall("provider")]
    activities = [item.get(ANDROID_NAME, "") for item in application.findall("activity")]
    main_activity = ""

    for element_name in ("activity", "activity-alias"):
        for activity in application.findall(element_name):
            for intent_filter in activity.findall("intent-filter"):
                actions = {item.get(ANDROID_NAME, "") for item in intent_filter.findall("action")}
                categories = {item.get(ANDROID_NAME, "") for item in intent_filter.findall("category")}
                if (
                    "android.intent.action.MAIN" in actions
                    and "android.intent.category.LAUNCHER" in categories
                ):
                    target = activity.get(ANDROID_NAME, "")
                    if element_name == "activity-alias":
                        target = activity.get(f"{{{ANDROID_NS}}}targetActivity", target)
                    main_activity = _resolve_component(package_name, target)
                    break
            if main_activity:
                break
        if main_activity:
            break

    return {
        "tree": tree,
        "root": root,
        "application": application,
        "application_name": application.get(ANDROID_NAME, ""),
        "providers": providers,
        "activities": activities,
        "main_activity": main_activity,
    }


def _find_wrapper_parent(smali_dir: Path) -> tuple[str, Path | None, bool]:
    candidates = list(smali_dir.glob("smali*/com/pairip/application/Application.smali"))
    if not candidates:
        return "", None, False

    wrapper = candidates[0]
    content = wrapper.read_text(encoding="utf-8", errors="replace")
    parent_match = re.search(r"^\.super\s+L([^;]+);", content, re.MULTILINE)
    parent = parent_match.group(1).replace("/", ".") if parent_match else ""
    calls_check_license = bool(
        re.search(
            r"LicenseClient;->(?:checkLicense|initializeLicenseCheck)",
            content,
        )
    )
    return parent, wrapper, calls_check_license


def analyze_xapk(
    xapk_path: Path,
    workspace_root: Path,
    toolchain: Toolchain,
    log: LogFn = _null_log,
) -> AnalysisResult:
    xapk_path = xapk_path.resolve()
    if not xapk_path.is_file() or xapk_path.suffix.lower() != ".xapk":
        raise GpCheckError(f"Select a valid .xapk file: {xapk_path}")
    toolchain.validate_analysis()

    workspace = _new_workspace(workspace_root.resolve(), xapk_path)
    extracted_dir = workspace / "original"
    decoded_dir = workspace / "decoded-base"
    manifest_json_path = extracted_dir / "manifest.json"

    log(f"Workspace: {workspace}")
    log(f"XAPK SHA-256: {sha256_file(xapk_path)}")
    log("Extracting XAPK...")
    _safe_extract_zip(xapk_path, extracted_dir)

    if not manifest_json_path.is_file():
        raise GpCheckError("manifest.json was not found in the XAPK.")
    metadata = json.loads(manifest_json_path.read_text(encoding="utf-8-sig"))
    split_apks = metadata.get("split_apks", [])
    base_entry = next((item for item in split_apks if item.get("id") == "base"), None)
    if not base_entry:
        raise GpCheckError("manifest.json does not define a base APK.")

    base_apk_name = str(base_entry["file"])
    base_apk_path = extracted_dir / base_apk_name
    _assert_file(base_apk_path, "Base APK")

    log("Decoding Manifest while preserving raw DEX files...")
    run_command(
        [
            toolchain.java,
            "-jar",
            toolchain.apktool_jar,
            "d",
            "-f",
            "-s",
            base_apk_path,
            "-o",
            decoded_dir,
        ],
        log=log,
    )

    manifest_xml_path = decoded_dir / "AndroidManifest.xml"
    parsed = _parse_manifest_xml(manifest_xml_path, str(metadata.get("package_name", "")))

    application_name = str(parsed["application_name"])
    provider_found = PAIRIP_PROVIDER in parsed["providers"]
    pairip_activity_found = PAIRIP_LICENSE_ACTIVITY in parsed["activities"]
    original_application_name = ""
    actions: list[PatchAction] = []
    evidence: list[str] = []
    confidence = "unsupported"

    if application_name == PAIRIP_APPLICATION:
        log("PairIP Application wrapper found. Decoding smali for inheritance evidence...")
        smali_dir = workspace / "smali-readonly"
        run_command(
            [
                toolchain.java,
                "-jar",
                toolchain.apktool_jar,
                "d",
                "-f",
                "-r",
                base_apk_path,
                "-o",
                smali_dir,
            ],
            log=log,
        )
        parent, wrapper_path, calls_check = _find_wrapper_parent(smali_dir)
        if wrapper_path:
            evidence.append(f"Wrapper smali: {wrapper_path}")
        if calls_check:
            evidence.append("Wrapper attachBaseContext calls PairIP LicenseClient.")

        invalid_parent = (
            not parent
            or parent.startswith("android.")
            or parent.startswith("com.pairip.")
        )
        if invalid_parent:
            evidence.append("A safe business Application superclass could not be derived.")
        else:
            original_application_name = parent
            actions.append(
                PatchAction(
                    kind="restore_application",
                    description=f"Restore business Application: {application_name} -> {parent}",
                    old_value=application_name,
                    new_value=parent,
                )
            )
            evidence.append(f"Wrapper superclass: {parent}")
            confidence = "high" if calls_check else "medium"

    if provider_found:
        actions.append(
            PatchAction(
                kind="remove_pairip_provider",
                description=f"Remove manifest registration for {PAIRIP_PROVIDER}",
                old_value=PAIRIP_PROVIDER,
            )
        )
        evidence.append("Manifest registers PairIP LicenseContentProvider.")
        confidence = "high"

    if pairip_activity_found:
        evidence.append("Manifest contains PairIP LicenseActivity.")
    if not actions:
        evidence.append("No supported exact PairIP startup pattern was found; no patch will be offered.")

    result = AnalysisResult(
        xapk_path=xapk_path,
        workspace=workspace,
        extracted_dir=extracted_dir,
        decoded_dir=decoded_dir,
        manifest_json_path=manifest_json_path,
        manifest_xml_path=manifest_xml_path,
        base_apk_path=base_apk_path,
        base_apk_name=base_apk_name,
        package_name=str(metadata.get("package_name", "")),
        app_name=str(metadata.get("name", "")),
        version_name=str(metadata.get("version_name", "")),
        version_code=str(metadata.get("version_code", "")),
        main_activity=str(parsed["main_activity"]),
        application_name=application_name,
        original_application_name=original_application_name,
        provider_found=provider_found,
        pairip_activity_found=pairip_activity_found,
        confidence=confidence,
        actions=actions,
        evidence=evidence,
        split_apks=split_apks,
        xapk_sha256=sha256_file(xapk_path),
    )

    (workspace / "analysis.json").write_text(
        json.dumps(result.serializable(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log(f"Detection confidence: {confidence}")
    for action in actions:
        log(f"Proposed: {action.description}")
    return result


def load_analysis(analysis_json: Path) -> AnalysisResult:
    data = json.loads(analysis_json.read_text(encoding="utf-8"))
    data.pop("supported", None)
    for key in (
        "xapk_path",
        "workspace",
        "extracted_dir",
        "decoded_dir",
        "manifest_json_path",
        "manifest_xml_path",
        "base_apk_path",
    ):
        data[key] = Path(data[key])
    data["actions"] = [PatchAction(**item) for item in data.get("actions", [])]
    return AnalysisResult(**data)


def _patch_manifest(result: AnalysisResult, evidence_dir: Path) -> tuple[Path, Path]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    before_path = evidence_dir / "AndroidManifest.before.xml"
    after_path = evidence_dir / "AndroidManifest.after.xml"
    shutil.copy2(result.manifest_xml_path, before_path)

    parsed = _parse_manifest_xml(result.manifest_xml_path, result.package_name)
    tree: ET.ElementTree = parsed["tree"]
    application: ET.Element = parsed["application"]

    for action in result.actions:
        if action.kind == "restore_application":
            current = application.get(ANDROID_NAME, "")
            if current != action.old_value:
                raise GpCheckError(
                    f"Application changed since analysis: expected {action.old_value}, found {current}"
                )
            application.set(ANDROID_NAME, action.new_value)
        elif action.kind == "remove_pairip_provider":
            matches = [
                item
                for item in application.findall("provider")
                if item.get(ANDROID_NAME, "") == PAIRIP_PROVIDER
            ]
            if len(matches) != 1:
                raise GpCheckError(
                    f"Expected one PairIP provider registration, found {len(matches)}."
                )
            application.remove(matches[0])
        else:
            raise GpCheckError(f"Unsupported patch action: {action.kind}")

    tree.write(result.manifest_xml_path, encoding="utf-8", xml_declaration=True)
    shutil.copy2(result.manifest_xml_path, after_path)
    return before_path, after_path


def _zip_dex_hashes(apk_path: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    with zipfile.ZipFile(apk_path) as archive:
        names = sorted(
            (name for name in archive.namelist() if re.fullmatch(r"classes(?:\d+)?\.dex", name)),
            key=lambda name: (len(name), name),
        )
        for name in names:
            digest = hashlib.sha256()
            with archive.open(name) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            hashes[name] = digest.hexdigest().upper()
    return hashes


def ensure_lab_keystore(
    toolchain: Toolchain,
    keystore_path: Path,
    alias: str,
    password: str,
    log: LogFn = _null_log,
) -> None:
    if keystore_path.is_file():
        return
    keystore_path.parent.mkdir(parents=True, exist_ok=True)
    log(f"Creating lab keystore: {keystore_path}")
    run_command(
        [
            toolchain.keytool,
            "-genkeypair",
            "-noprompt",
            "-storetype",
            "PKCS12",
            "-keystore",
            keystore_path,
            "-storepass",
            password,
            "-keypass",
            password,
            "-alias",
            alias,
            "-keyalg",
            "RSA",
            "-keysize",
            "2048",
            "-validity",
            "3650",
            "-dname",
            "CN=Android Lab, OU=Research, O=Local, C=CN",
        ],
        log=log,
    )


def _sign_apk(
    toolchain: Toolchain,
    apk_path: Path,
    keystore_path: Path,
    alias: str,
    password: str,
    log: LogFn,
) -> str:
    run_command(
        [
            toolchain.java,
            "-jar",
            toolchain.apksigner_jar,
            "sign",
            "--ks",
            keystore_path,
            "--ks-key-alias",
            alias,
            "--ks-pass",
            f"pass:{password}",
            "--key-pass",
            f"pass:{password}",
            "--v1-signing-enabled",
            "true",
            "--v2-signing-enabled",
            "true",
            "--v3-signing-enabled",
            "true",
            "--v4-signing-enabled",
            "false",
            apk_path,
        ],
        log=log,
    )
    _, output = run_command(
        [
            toolchain.java,
            "-jar",
            toolchain.apksigner_jar,
            "verify",
            "--verbose",
            "--print-certs",
            apk_path,
        ],
        log=log,
    )
    match = re.search(r"certificate SHA-256 digest:\s*([0-9a-fA-F]+)", output)
    if not match:
        raise GpCheckError(f"Could not read signer certificate digest: {apk_path.name}")
    return match.group(1).upper()


def build_patched_xapk(
    result: AnalysisResult,
    toolchain: Toolchain,
    keystore_path: Path,
    alias: str,
    password: str,
    log: LogFn = _null_log,
) -> BuildResult:
    if not result.supported:
        raise GpCheckError("This analysis has no supported high-confidence patch.")
    if not password:
        raise GpCheckError("Keystore password cannot be empty.")
    toolchain.validate_build()
    ensure_lab_keystore(toolchain, keystore_path, alias, password, log)

    dist_dir = result.workspace / "dist"
    signed_apk_dir = dist_dir / "signed-apks"
    if dist_dir.exists():
        raise GpCheckError(f"Build output already exists: {dist_dir}")
    signed_apk_dir.mkdir(parents=True)
    evidence_dir = result.workspace / "evidence"

    log("Applying reviewed Manifest actions...")
    manifest_before, manifest_after = _patch_manifest(result, evidence_dir)

    unsigned_base = dist_dir / "base-unsigned.apk"
    aligned_base = signed_apk_dir / result.base_apk_name
    log("Building patched base APK...")
    run_command(
        [
            toolchain.java,
            "-jar",
            toolchain.apktool_jar,
            "b",
            result.decoded_dir,
            "-o",
            unsigned_base,
        ],
        log=log,
    )
    run_command(
        [toolchain.zipalign, "-f", "-p", "4", unsigned_base, aligned_base],
        log=log,
    )

    apk_names = [str(item.get("file", "")) for item in result.split_apks]
    if result.base_apk_name not in apk_names:
        apk_names.insert(0, result.base_apk_name)

    signed_apks: list[Path] = []
    for apk_name in apk_names:
        if not apk_name:
            continue
        destination = signed_apk_dir / apk_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if apk_name != result.base_apk_name:
            source = result.extracted_dir / apk_name
            _assert_file(source, f"Split APK {apk_name}")
            shutil.copy2(source, destination)
        signed_apks.append(destination)

    certificate_digests: set[str] = set()
    for index, apk_path in enumerate(signed_apks, start=1):
        log(f"Signing {index}/{len(signed_apks)}: {apk_path.name}")
        certificate_digests.add(
            _sign_apk(toolchain, apk_path, keystore_path, alias, password, log)
        )
    if len(certificate_digests) != 1:
        raise GpCheckError("Signed APK files do not share one certificate.")
    certificate_sha256 = next(iter(certificate_digests))

    original_hashes = _zip_dex_hashes(result.base_apk_path)
    patched_hashes = _zip_dex_hashes(aligned_base)
    dex_report: dict[str, dict[str, str | bool]] = {}
    for dex_name, original_hash in original_hashes.items():
        patched_hash = patched_hashes.get(dex_name, "")
        unchanged = original_hash == patched_hash
        dex_report[dex_name] = {
            "original": original_hash,
            "patched": patched_hash,
            "unchanged": unchanged,
        }
        log(f"DEX {dex_name}: unchanged={unchanged}")
        if not unchanged:
            raise GpCheckError(f"DEX changed unexpectedly: {dex_name}")

    metadata = json.loads(result.manifest_json_path.read_text(encoding="utf-8-sig"))
    metadata["total_size"] = sum(path.stat().st_size for path in signed_apks)
    patched_xapk = dist_dir / f"{result.xapk_path.stem}-patched.xapk"
    signed_lookup = {path.relative_to(signed_apk_dir).as_posix(): path for path in signed_apks}

    log(f"Packaging patched XAPK: {patched_xapk.name}")
    with zipfile.ZipFile(patched_xapk, "w") as output_zip:
        for source in result.extracted_dir.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(result.extracted_dir).as_posix()
            if relative == "manifest.json":
                output_zip.writestr(
                    relative,
                    json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
                    compress_type=zipfile.ZIP_DEFLATED,
                )
            elif relative in signed_lookup:
                output_zip.write(signed_lookup[relative], relative, compress_type=zipfile.ZIP_STORED)
            elif relative.lower().endswith(".apk"):
                raise GpCheckError(f"Unsigned APK would be copied into output XAPK: {relative}")
            else:
                output_zip.write(source, relative, compress_type=zipfile.ZIP_DEFLATED)

    build_report = {
        "package_name": result.package_name,
        "patched_xapk": str(patched_xapk),
        "certificate_sha256": certificate_sha256,
        "actions": [asdict(action) for action in result.actions],
        "dex_hashes": dex_report,
        "signed_apks": [str(path) for path in signed_apks],
    }
    (dist_dir / "build-report.json").write_text(
        json.dumps(build_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    log(f"Build complete: {patched_xapk}")
    return BuildResult(
        output_dir=dist_dir,
        signed_apk_dir=signed_apk_dir,
        patched_xapk=patched_xapk,
        dex_hashes=dex_report,
        certificate_sha256=certificate_sha256,
        signed_apks=signed_apks,
        manifest_before=manifest_before,
        manifest_after=manifest_after,
    )


def _adb(
    toolchain: Toolchain,
    args: list[str],
    log: LogFn,
    check: bool = True,
    stream_output: bool = True,
) -> tuple[int, str]:
    return run_command(
        [toolchain.adb, *args],
        log=log,
        check=check,
        stream_output=stream_output,
    )


def _build_install_command(
    selected_apks: list[Path],
    installer_package: str = "",
) -> list[str]:
    command = ["install-multiple", "--no-incremental", "-r"]
    if installer_package:
        command.extend(["-i", installer_package])
    command.extend(str(path) for path in selected_apks)
    return command


def _parse_installer_package(package_name: str, output: str) -> str:
    for line in output.splitlines():
        match = re.fullmatch(r"package:(\S+)\s+installer=(\S+)", line.strip())
        if match and match.group(1) == package_name:
            installer = match.group(2)
            return "" if installer == "null" else installer
    return ""


def _read_installer_package(
    toolchain: Toolchain,
    package_name: str,
    log: LogFn,
) -> str:
    _, output = _adb(
        toolchain,
        ["shell", "pm", "list", "packages", "-i", package_name],
        log,
        check=False,
        stream_output=False,
    )
    return _parse_installer_package(package_name, output)


def read_device_info(toolchain: Toolchain, log: LogFn = _null_log) -> DeviceInfo:
    toolchain.validate_device()
    _, devices_output = _adb(toolchain, ["devices"], log)
    serials = []
    for line in devices_output.splitlines():
        match = re.match(r"^(\S+)\s+device$", line.strip())
        if match:
            serials.append(match.group(1))
    if len(serials) != 1:
        raise GpCheckError(f"Expected exactly one authorized adb device, found {len(serials)}.")

    def prop(name: str) -> str:
        return _adb(toolchain, ["shell", "getprop", name], log)[1].strip()

    _, density_output = _adb(toolchain, ["shell", "wm", "density"], log)
    density_matches = re.findall(r"(?:Physical|Override) density:\s*(\d+)", density_output)
    density = int(density_matches[-1]) if density_matches else 0
    abi_list = [item for item in prop("ro.product.cpu.abilist").split(",") if item]
    locale = prop("persist.sys.locale") or prop("ro.product.locale")
    return DeviceInfo(
        serial=serials[0],
        model=prop("ro.product.model"),
        sdk=prop("ro.build.version.sdk"),
        abi_list=abi_list,
        density=density,
        locale=locale,
    )


_DENSITY_VALUES = {
    "ldpi": 120,
    "mdpi": 160,
    "tvdpi": 213,
    "hdpi": 240,
    "xhdpi": 320,
    "xxhdpi": 480,
    "xxxhdpi": 640,
}


def choose_device_apks(
    split_apks: list[dict],
    signed_apk_dir: Path,
    device: DeviceInfo,
) -> list[Path]:
    entries = [(str(item.get("id", "")), str(item.get("file", ""))) for item in split_apks]
    selected: list[str] = [file_name for split_id, file_name in entries if split_id == "base"]
    if not selected:
        raise GpCheckError("No base APK exists in split metadata.")

    abi_entries: dict[str, str] = {}
    density_entries: dict[str, str] = {}
    language_entries: dict[str, str] = {}
    for split_id, file_name in entries:
        config = split_id.removeprefix("config.")
        normalized_abi = config.replace("_", "-")
        if normalized_abi in {"arm64-v8a", "armeabi-v7a", "x86", "x86-64"}:
            abi_entries[normalized_abi] = file_name
        elif config in _DENSITY_VALUES:
            density_entries[config] = file_name
        elif re.fullmatch(r"[a-z]{2,3}(?:-r[A-Z]{2})?", config):
            language_entries[config] = file_name

    for abi in device.abi_list:
        if abi in abi_entries:
            selected.append(abi_entries[abi])
            break
    else:
        if len(abi_entries) == 1:
            selected.append(next(iter(abi_entries.values())))
        elif abi_entries:
            raise GpCheckError(
                f"No compatible ABI split. Device={device.abi_list}, XAPK={list(abi_entries)}"
            )

    if density_entries:
        nearest_density = min(
            density_entries,
            key=lambda name: abs(_DENSITY_VALUES[name] - device.density),
        )
        selected.append(density_entries[nearest_density])

    locale_key = device.locale.split("-")[0].lower() if device.locale else ""
    if locale_key in language_entries:
        selected.append(language_entries[locale_key])
    elif "en" in language_entries:
        selected.append(language_entries["en"])

    paths = [signed_apk_dir / name for name in dict.fromkeys(selected)]
    for path in paths:
        _assert_file(path, "Selected split APK")
    return paths


def _install_from_directory_and_verify(
    analysis: AnalysisResult,
    apk_directory: Path,
    toolchain: Toolchain,
    grant_cleaner_permissions: bool = True,
    installer_package: str = "",
    strategy: str = "manifest_patch",
    screenshot_name: str = "installed-launch.png",
    log: LogFn = _null_log,
) -> InstallResult:
    if not analysis.main_activity:
        raise GpCheckError("No MAIN/LAUNCHER activity was found.")
    device = read_device_info(toolchain, log)
    log(
        f"Device: {device.model}, API {device.sdk}, ABI={','.join(device.abi_list)}, "
        f"density={device.density}, locale={device.locale}"
    )
    selected_apks = choose_device_apks(analysis.split_apks, apk_directory, device)
    log("Selected APKs: " + ", ".join(path.name for path in selected_apks))

    if installer_package:
        installer_code, installer_path = _adb(
            toolchain,
            ["shell", "pm", "path", installer_package],
            log,
            check=False,
            stream_output=False,
        )
        if installer_code != 0 or not any(
            line.startswith("package:") for line in installer_path.splitlines()
        ):
            raise GpCheckError(
                f"Requested installer is not installed on the device: {installer_package}"
            )

    install_command = _build_install_command(selected_apks, installer_package)
    returncode, install_output = _adb(toolchain, install_command, log, check=False)
    if returncode != 0 or "Success" not in install_output:
        if "UPDATE_INCOMPATIBLE" in install_output:
            raise GpCheckError(
                "Installed package uses a different signature. The tool will not uninstall it automatically "
                "because uninstalling clears app data."
            )
        raise CommandError([str(toolchain.adb), *install_command], returncode, install_output)

    recorded_installer = _read_installer_package(toolchain, analysis.package_name, log)
    installer_verified = not installer_package or recorded_installer == installer_package
    requested_label = installer_package or "(not specified)"
    recorded_label = recorded_installer or "(none)"
    log(f"Installer source: requested={requested_label}, recorded={recorded_label}")

    if grant_cleaner_permissions:
        _adb(
            toolchain,
            ["shell", "appops", "set", analysis.package_name, "MANAGE_EXTERNAL_STORAGE", "allow"],
            log,
            check=False,
        )
        _adb(
            toolchain,
            ["shell", "appops", "set", analysis.package_name, "GET_USAGE_STATS", "allow"],
            log,
            check=False,
        )
        _adb(
            toolchain,
            [
                "shell",
                "pm",
                "grant",
                analysis.package_name,
                "android.permission.POST_NOTIFICATIONS",
            ],
            log,
            check=False,
        )

    _adb(toolchain, ["logcat", "-c"], log, check=False)
    _adb(toolchain, ["shell", "am", "force-stop", analysis.package_name], log)
    component = f"{analysis.package_name}/{analysis.main_activity}"
    _adb(toolchain, ["shell", "am", "start", "-W", "-n", component], log)
    time.sleep(6)

    _, window_output = _adb(
        toolchain,
        ["shell", "dumpsys", "window"],
        log,
        stream_output=False,
    )
    foreground_lines = [
        line.strip()
        for line in window_output.splitlines()
        if "mCurrentFocus=" in line or "mFocusedApp=" in line
    ]
    foreground = "\n".join(foreground_lines)
    _, pid_output = _adb(toolchain, ["shell", "pidof", analysis.package_name], log, check=False)
    pid = pid_output.strip()
    _, log_output = _adb(
        toolchain,
        ["logcat", "-d", "-v", "brief"],
        log,
        check=False,
        stream_output=False,
    )
    suspicious_logs = [
        line
        for line in log_output.splitlines()
        if re.search(r"pairip|LicenseActivity|FATAL EXCEPTION", line, re.IGNORECASE)
    ]

    screenshot = analysis.workspace / "evidence" / screenshot_name
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    remote_screenshot = f"/sdcard/gpcheck-{analysis.package_name}.png"
    _adb(toolchain, ["shell", "screencap", "-p", remote_screenshot], log, check=False)
    pull_code, _ = _adb(
        toolchain,
        ["pull", remote_screenshot, str(screenshot)],
        log,
        check=False,
    )
    if pull_code != 0 or not screenshot.is_file():
        screenshot = None

    foreground_ok = (
        analysis.package_name in foreground or "permissioncontroller" in foreground
    ) and PAIRIP_LICENSE_ACTIVITY not in foreground
    success = bool(pid) and foreground_ok and not suspicious_logs and installer_verified
    return InstallResult(
        success=success,
        selected_apks=selected_apks,
        foreground=foreground,
        pid=pid,
        suspicious_logs=suspicious_logs,
        screenshot=screenshot,
        output=install_output,
        strategy=strategy,
        requested_installer=installer_package,
        installer_package=recorded_installer,
        installer_verified=installer_verified,
    )


def install_original_as_play_store_and_verify(
    analysis: AnalysisResult,
    toolchain: Toolchain,
    grant_cleaner_permissions: bool = True,
    log: LogFn = _null_log,
) -> InstallResult:
    log("Priority 1: installing the unmodified APK set with Google Play as installer...")
    return _install_from_directory_and_verify(
        analysis=analysis,
        apk_directory=analysis.extracted_dir,
        toolchain=toolchain,
        grant_cleaner_permissions=grant_cleaner_permissions,
        installer_package=PLAY_STORE_PACKAGE,
        strategy="play_store_installer",
        screenshot_name="original-play-store-launch.png",
        log=log,
    )


def install_and_verify(
    analysis: AnalysisResult,
    build: BuildResult,
    toolchain: Toolchain,
    grant_cleaner_permissions: bool = True,
    log: LogFn = _null_log,
) -> InstallResult:
    log("Fallback: installing the manifest-patched APK set...")
    return _install_from_directory_and_verify(
        analysis=analysis,
        apk_directory=build.signed_apk_dir,
        toolchain=toolchain,
        grant_cleaner_permissions=grant_cleaner_permissions,
        strategy="manifest_patch",
        log=log,
    )
