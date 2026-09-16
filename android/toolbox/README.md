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

## Device Observations

Device details and current Activity/Window follow the selected device. Visible pages refresh every
30 seconds and 2 seconds respectively; automatic refresh can be paused. Raw command output and
copyable snapshots are available. Foreground transitions retain the latest 100 observations in memory.
Activity owner and focused window are separate: keyboards and dialogs may hold window focus.
Missing vendor fields remain unavailable rather than becoming zero. Successive dumps are not atomic.

`AppContext.selection_changed` announces actual selection changes. Live modules use
`context.sessions.subscribe(owner, serial, kind)` and `unsubscribe(owner)` instead of the finite task
queue. Consumers share one collector per device and observation kind. Results are delivered on the
Qt thread; generations discard results after unsubscribe or disconnect. Pages release subscriptions
when hidden; reconnecting the same device resumes active subscriptions. Each command has an 8-second
timeout and cancellation is checked between commands. Shutdown prevents further commands; an in-flight
read may finish within that timeout. No packages are installed and no device settings are changed.

Performance history and Perfetto analysis remain subsequent batches.

## Screen Control

The Screen Control page opens one independent window per selected device. Windows remain bound
to their original serial. Mouse gestures and keyboard/clipboard input use the official scrcpy engine;
the toolbar provides Back, Home, Recents, Power, volume, screenshots, fullscreen, quality and reconnect.
PNG screenshots are written under the configured output directory's `screenshots` folder.
Changing quality reconnects that window. Disconnecting pauses it; reconnecting the same serial resumes.

Windows 10/11 x64 is currently supported. Prepare the pinned runtime once:

```powershell
python -m android.toolbox.download_runtime
```

The helper downloads the official [scrcpy 4.1 Windows archive](https://github.com/Genymobile/scrcpy/releases/tag/v4.1)
and verifies SHA-256 `5b12172b3264b2889f4583ee64752ce832e29bc8b1089dca81093459697165db`.
The complete extracted directory, including DLLs, server and license, is kept in `runtime/scrcpy/`
(ignored by Git). Alternatively configure an existing `scrcpy.exe` in Settings, keeping its companion
files beside it. GUI startup does not download dependencies. Packaging must include this entire directory
and all required third-party license notices; the current helper targets development, not an EXE build.

Native HWND lookup is restricted to the owned scrcpy PID. Qt embeds the window only after the first
texture is ready. Software rendering is used because the tested GPU backends could clip after native
reparenting/resizing. This favors reliable embedded resizing and may cost more CPU. Native child clicks
restore keyboard focus across the Qt/SDL threads. A window's exit closes its own process; it never kills
the ADB server or another scrcpy session.
Device input uses bounded QProcess commands outside the install queue and captures the original serial.
Normal Ctrl+V uses scrcpy clipboard synchronization; device IME/app restrictions still apply.

Optional live smoke test (changes the device's foreground UI, opens Recents/Home and notification shade):

```powershell
python -m android.toolbox.tests.screen_smoke --serial YOUR_SERIAL
```

Add `--settings-input` to open Settings search and verify Chinese clipboard paste via native mouse and
keyboard events. This optional check requires Settings with a Search accessibility label in Chinese or
English. Screenshots are local under `%TEMP%/toolbox-screen-visual`; they may contain device screen data.
The test restores the host clipboard and removes its device-side UI hierarchy dump.
Repeat with `QT_SCALE_FACTOR=2` for scaled layouts. Native desktop captures and pixel variation checks
are used because Qt widget-only captures omit the external GPU surface.

## Runtime Layout for Later Packaging

Resource lookup priority is explicit setting, bundled runtime, then host discovery. Frozen-resource paths
use `sys._MEIPASS`; mutable data uses the user data directory, never the extraction directory.

```text
runtime/
  scrcpy/scrcpy.exe             # Include server, DLLs and license from the verified archive.
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
