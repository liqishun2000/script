# Android Toolbox

Windows desktop application using PySide6. The existing standalone tools remain available.

## Run

From the repository root:

```powershell
python -m pip install -r android/toolbox/requirements.txt
python -m android.toolbox
```

Alternatively, run `android/start_toolbox.bat` or `python android/android_toolbox.py`.

The source version uses installed Android/Java tools. Settings displays the resolved dependencies
and accepts explicit overrides. Building an executable and bundling those dependencies are a later
delivery step; the source tree does not contain the runtime binaries.

## Features

- APK/XAPK/APKS/APKM batch installation, split APKs and OBB transfer; individual results and failed-item retry.
- GPCheck analysis, original-package installation with the Play Store installer, supported Manifest patches,
  signing and launch verification. Unsupported patterns remain unsupported. Signature conflicts never
  automatically uninstall an existing application. Cleaner permissions are optional and disabled by default.
- SDK emulator shutdown, with disappearance verification. Physical devices are excluded.
- Shared device selection, background FIFO tasks, step-boundary cancellation, bounded log rendering,
  log export, task history and settings. A queued task captures its device, inputs and tools at submission.

Task cancellation stops subsequent steps. The current command finishes or times out (10 minutes by
default; device queries and emulator shutdown use shorter limits). Completed changes are not rolled back.
Interrupted jobs are recorded after restart but never automatically replayed. A failed or cancelled GPCheck
build may leave evidence and partial output; analyze again to create a fresh workspace before rebuilding.

Preferences, the latest 100 completed task records and their logs live in `%LOCALAPPDATA%/AndroidToolbox`.
Pending tasks are retained regardless of that limit. Workspaces and signing files are kept separately and
are not deleted when task history is cleared. Passwords stay in memory; command logging redacts signing
password arguments. The default lab signature uses alias `android-lab` and password `android` and creates
a per-user key on the first build. Configure a separate key and password when a different signature is needed.

## Extension Contract

1. Add a module with a page class accepting `AppContext`. `widgets.Page` provides inline status/error handling.
2. Register one `ToolSpec` in `registry.builtins()`: stable ID, title, category, standard Qt icon, importable
   `module:PageClass`, and dependencies. The window loads and caches pages lazily; module IDs must be unique.
3. Use `context.tools.snapshot()` and `context.target()` in the UI thread before submitting an operation.
   Copy all UI input into local immutable values. Workers must not read or modify widgets or preferences.
4. Submit with `context.tasks.submit(title, module_id, operation, target)`. The callable takes `Execution`
   and returns `Outcome(status, items, output, value)` or `None`. Status is `success`, `partial` or `failed`;
   each item has `name`, `status`, `detail`. `value` is an in-memory domain result; it is never persisted.
5. Use `Execution.run()` for child processes, `log()` for output, `checkpoint()` between local stages,
   and `item()` for incremental results. Do not catch `Cancelled` as an ordinary item failure.
6. Handle `context.tasks.finished` by task ID on the UI thread. Keep core logic free of GUI dependencies.
   Device commands must always include the captured serial; device discovery itself is unscoped.

New modules do not edit other pages or implement their own device polling, worker threads or log panes.
The registration test adds a sample module to the existing window without changing it.

## Runtime Layout for Later Packaging

Resource lookup priority is explicit setting, bundled runtime, then host discovery. Frozen-resource paths
use `sys._MEIPASS`; mutable data uses the user data directory, never the extraction directory.

```text
runtime/
  platform-tools/adb.exe        # Include matching platform-tools DLLs.
  jdk/bin/java.exe              # Include the complete compatible JDK runtime.
  jdk/bin/keytool.exe
  apktool/apktool.jar
  build-tools/zipalign.exe      # Include matching DLLs and remaining required tools.
  build-tools/lib/apksigner.jar
```

The eventual Windows 10/11 x64 distribution must contain Python, Qt, these dependencies and required
runtime libraries and notices. Validate on a clean offline machine after packaging. USB drivers and
device-side USB debugging authorization remain prerequisites for connecting physical phones.

## Verification

```powershell
python -m unittest discover -s android/toolbox/tests -v
```

From `android/removeGpCheck`:

```powershell
python -m unittest discover -s tests -v
```

Tests cover scoped ADB calls, batch failures, shutdown confirmation, command timeout, cancellation,
queue ordering, history recovery, snapshot isolation, navigation state, small windows and module registration.
GUI tests mock device discovery and do not install packages or close real devices.

Optional real build/signing test, using only the synthetic fixture in this test directory:

```powershell
$env:TOOLBOX_INTEGRATION = "1"
python -m unittest discover -s android/toolbox/tests -p test_integration.py -v
```

Native screenshot checks (repeat at `1`, `1.25`, `1.5`, `2`):

```powershell
$env:QT_SCALE_FACTOR = "1.5"
python -m android.toolbox.tests.visual_smoke
```
