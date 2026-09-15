"""Task adapters. Inputs are captured before the task enters the queue."""

from pathlib import Path

from .. import xapk_installer
from ..closeEmulator.close_emulators import close_emulator
from ..removeGpCheck import gpcheck_core as gp
from .services import Cancelled, Outcome, Tools


def install_packages(context, files, serial, tools, keep_data=False, downgrade=False):
    Tools.require(tools, "adb")
    items = []
    for source in files:
        context.checkpoint()
        try:
            xapk_installer.install_xapk(Path(source), serial=serial, keep_data=keep_data,
                                       downgrade=downgrade, log=context.log,
                                       adb_path=tools["adb"], runner=context.run)
            item = {"name": str(source), "status": "success", "detail": "安装完成"}
        except Cancelled:
            raise
        except Exception as exc:
            item = {"name": str(source), "status": "failed", "detail": str(exc)}
            context.log(str(exc))
        items.append(item)
        context.item(**item)
    return Outcome(batch_status(items), items)


def batch_status(items):
    successes = sum(item["status"] == "success" for item in items)
    return "success" if successes == len(items) else "partial" if successes else "failed"


def close_devices(context, serials, tools):
    Tools.require(tools, "adb")
    items = []
    for serial in serials:
        context.checkpoint()
        try:
            close_emulator(serial, tools["adb"], context.run)
            item = {"name": serial, "status": "success", "detail": "模拟器已退出"}
        except Cancelled:
            raise
        except Exception as exc:
            item = {"name": serial, "status": "failed", "detail": str(exc)}
            context.log(str(exc))
        items.append(item)
        context.item(**item)
    return Outcome(batch_status(items), items)


def analyze(context, source, output, tools):
    Tools.require(tools, "java", "apktool")
    result = gp.analyze_xapk(Path(source), Path(output), Tools.chain(tools, context), context.log)
    return Outcome(output=str(result.workspace), value=result)


def build(context, analysis, tools, keystore, alias, password):
    Tools.require(tools, "java", "keytool", "apktool", "build_tools")
    if gp.sha256_file(analysis.xapk_path) != analysis.xapk_sha256:
        raise RuntimeError("输入文件已改变，请重新分析。")
    result = gp.build_patched_xapk(analysis, Tools.chain(tools, context), Path(keystore), alias,
                                   password, context.log)
    return Outcome(output=str(result.output_dir), value=result)


def verify(context, analysis, build_result, serial, tools, permissions=False):
    Tools.require(tools, "adb")
    chain = Tools.chain(tools, context, serial)
    if build_result:
        result = gp.install_and_verify(analysis, build_result, chain, permissions, context.log)
    else:
        result = gp.install_original_as_play_store_and_verify(analysis, chain, permissions, context.log)
    items = [{"name": "启动验证", "status": "success" if result.success else "failed",
              "detail": result.foreground + "\n" + "\n".join(result.suspicious_logs)}]
    return Outcome("success" if result.success else "partial", items, str(analysis.workspace), result)
