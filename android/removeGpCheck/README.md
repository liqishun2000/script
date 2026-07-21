# Android XAPK 去除 Google Play 启动校验实验手册

> 适用范围：你有权分析和测试的 APK/XAPK，例如导师提供的实验样本、自己的应用或公司授权样本。
>
> 本文目标不是伪造许可证结果，而是定位“为什么应用在无 Google 账号设备上无法进入业务页面”，然后用最小改动关闭自动启动的分发校验组件，用于离线功能测试。

## 0. 图形化工具

目录中现在包含一个可拖放 XAPK 的桌面工具：

```text
remove_gp_check_gui.py   图形界面
gpcheck_core.py          可测试的分析、构建和安装核心
run_gui.bat              Windows 启动入口
requirements.txt         拖放依赖
tests/                   单元测试
```

首次使用：

```powershell
cd E:\code\py\android\removeGpCheck
python -m pip install -r requirements.txt
python remove_gp_check_gui.py
```

也可以双击 `run_gui.bat`。当前实验环境已安装 `tkinterdnd2`。

操作顺序：

1. 把 XAPK 拖入窗口，工具立即开始分析；也可以点击“选择 XAPK”后点击“分析”。
2. 查看检测模式、业务 Application、置信度、静态证据和拟执行修改。
3. 只有高/中置信度的精确已知模式才会启用“构建实验版 XAPK”。
4. 确认修改后，工具重建 base、签名全部 split、验证全部 DEX 哈希并生成新 XAPK。
5. “安装并验证”会按连接设备的 ABI、密度和语言选择 split，冷启动后检查前台窗口、PID、PairIP 和崩溃日志。

工具不会覆盖原始 XAPK，不会自动卸载不同签名的旧版本，也不会执行清理按钮。每次分析使用独立时间戳工作目录，主要输出：

```text
workspace/<样本-时间>/
  analysis.json
  original/
  decoded-base/
  smali-readonly/              # 仅 Application 包装型需要
  evidence/
    AndroidManifest.before.xml
    AndroidManifest.after.xml
    installed-launch.png
  dist/
    signed-apks/
    build-report.json
    <原文件名>-patched.xapk
```

当前自动修改白名单只有：

- `com.pairip.application.Application`，且能解析出可信的非 PairIP 父类。
- `com.pairip.licensecheck.LicenseContentProvider` 的精确 Manifest 注册。

出现相同 Google Play 页面但不符合上述静态证据时，工具只报告“未知模式”，需要人工分析。

## 1. 先建立正确的认识

### 1.1 XAPK 是什么

XAPK 通常就是一个 ZIP 容器，里面包含：

- 主 APK（base APK）：代码、Manifest 和主要资源。
- ABI split：例如 `config.arm64_v8a.apk`。
- 屏幕密度 split：例如 `config.xxhdpi.apk`。
- 语言 split：例如 `config.en.apk`、`config.zh.apk`。
- `manifest.json`：描述包名、版本和 split 列表。

安装 split APK 时，主 APK 和所选 split 必须：

1. 包名和版本一致；
2. 使用同一张签名证书；
3. 包含设备需要的 ABI、密度和语言 split。

### 1.2 为什么会跳转 Google Play

本次 Flare Cleaner 使用了 PairIP 许可证组件。Android 启动应用时，`ContentProvider` 会早于 `Application.onCreate()` 和 Activity 创建。原包注册了：

```xml
<provider
    android:name="com.pairip.licensecheck.LicenseContentProvider"
    android:authorities="com.flare.cleaner.storage.com.pairip.licensecheck.LicenseContentProvider"
    android:exported="false" />
```

它的 `onCreate()` 会执行：

```smali
new-instance v0, Lcom/pairip/licensecheck/LicenseClient;
invoke-direct {v0, v1}, Lcom/pairip/licensecheck/LicenseClient;-><init>(Landroid/content/Context;)V
invoke-virtual {v0}, Lcom/pairip/licensecheck/LicenseClient;->initializeLicenseCheck()V
```

无 Google 账号时，检查失败并打开 `com.pairip.licensecheck.LicenseActivity`，随后跳到 Google Play。

### 1.3 PairIP 常见的两种入口

不要拿到任何包都机械地删同一行。先确认它属于哪一种：

- Application 包装型：Manifest 的 `android:name` 是 `com.pairip.application.Application`。应找到原业务 Application，并把入口恢复为原类。
- Provider 自动初始化型：Manifest 已经使用业务 Application，但注册了 `LicenseContentProvider`。应只移除该 Provider 注册。

两个导师样本的差异：

| 样本 | PairIP 入口 | 触发方法 | 本次实际修改 |
| --- | --- | --- | --- |
| AuraClean V1.1.5 | `com.pairip.application.Application` | `attachBaseContext()` 调用 `LicenseClient.checkLicense()` | 把 Manifest Application 恢复成 `gol.zli.mcc.FeiApplication` |
| Flare Cleaner 1.0.2 | `LicenseContentProvider` | Provider 的 `onCreate()` 调用 `initializeLicenseCheck()` | 删除 Provider 的 Manifest 注册 |

所以你记得 AuraClean 涉及“一个方法”是对的：分析时必须阅读 `attachBaseContext()`。但最终补丁没有改这个方法的 smali，而是让系统不再实例化这个包装类，因此所有 DEX 都保持不变。

## 2. 准备工具

本文使用 Windows PowerShell，示例环境：

- Android SDK Build Tools：`aapt2`、`zipalign`、`apksigner`
- Android Platform Tools：`adb`
- Java 17 或兼容版本
- Apktool 3.0.2
- JADX 1.5.5（辅助阅读，不负责重新构建）

检查工具：

```powershell
adb version
java -version
Get-ChildItem "$env:LOCALAPPDATA\Android\Sdk\build-tools" -Directory
```

本文脚本不会下载工具，需要你通过 Android Studio SDK Manager 或可信来源提前安装。

如果系统提示“running scripts is disabled”，只为当前 PowerShell 进程临时放行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

关闭当前 PowerShell 窗口后该设置自动失效，不要为了本实验修改系统级永久策略。也可以单次执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\01-Extract-Xapk.ps1 <参数>
```

## 3. 建立实验目录并保留原件

不要直接修改导师给的 XAPK。建议目录结构：

```text
work/
  original/       # XAPK 原始解压内容
  decoded-base/   # Apktool 解码目录
  patched/        # 重建并签名后的 APK
  evidence/       # 截图、UI XML 和日志
```

使用配套脚本解包：

```powershell
.\scripts\01-Extract-Xapk.ps1 `
  -XapkPath 'E:\tem\auraclean_xapk\Flare+Cleaner_1.0.2_APKPure.xapk' `
  -OutputDirectory 'E:\lab\flare\original'
```

脚本会拒绝写入非空目录，以免覆盖已有分析结果。

手工命令等价于：

```powershell
New-Item -ItemType Directory -Path 'E:\lab\flare\original'
tar -xf 'E:\tem\auraclean_xapk\Flare+Cleaner_1.0.2_APKPure.xapk' `
  -C 'E:\lab\flare\original'
Get-Content -Raw 'E:\lab\flare\original\manifest.json' | ConvertFrom-Json
```

## 4. 确认设备需要哪些 split

```powershell
adb devices -l
adb shell getprop ro.product.cpu.abi
adb shell wm density
adb shell getprop persist.sys.locale
adb shell getprop ro.build.version.sdk
```

本次测试设备是 Android 13、API 33、ARM64、xxhdpi，使用：

```text
com.flare.cleaner.storage.apk
config.arm64_v8a.apk
config.xxhdpi.apk
config.en.apk
config.zh.apk
```

如果漏掉 ABI split，常见错误是 `INSTALL_FAILED_NO_MATCHING_ABIS`；漏掉必需 split，可能出现 `INSTALL_FAILED_MISSING_SPLIT` 或启动时资源异常。

## 5. 先测试原包，记录“失败基线”

不要一上来就修改。先证明原包为什么不能运行：

```powershell
$original = 'E:\lab\flare\original'

adb install-multiple -r `
  "$original\com.flare.cleaner.storage.apk" `
  "$original\config.arm64_v8a.apk" `
  "$original\config.xxhdpi.apk" `
  "$original\config.en.apk" `
  "$original\config.zh.apk"

adb logcat -c
adb shell am force-stop com.flare.cleaner.storage
adb shell am start -W -n `
  com.flare.cleaner.storage/com.liam.garbagecleaner.MainActivity

Start-Sleep -Seconds 5
adb shell dumpsys window | Select-String 'mCurrentFocus|mFocusedApp'
adb shell pidof com.flare.cleaner.storage
adb logcat -d -v threadtime |
  Select-String 'pairip|LicenseActivity|vending|FATAL EXCEPTION'
```

本样本的关键现象：

```text
com.flare.cleaner.storage/com.pairip.licensecheck.LicenseActivity
com.android.vending/...UnauthenticatedMainActivity
```

这说明失败发生在 PairIP 许可证层，而不是业务首页自己要求 Google 登录。

## 6. 解码主 APK

```powershell
$apktool = 'C:\tools\apktool_3.0.2.jar'
$base = 'E:\lab\flare\original\com.flare.cleaner.storage.apk'
$decoded = 'E:\lab\flare\decoded-base'

java -jar $apktool d -f -s $base -o $decoded
```

参数说明：

- `d`：decode。
- `-f`：允许覆盖 Apktool 自己生成的目标目录。
- `-s`：不反汇编 DEX，直接保留原始 `classes*.dex`。这是本实验的关键，因为我们只改 Manifest，不需要重新编译业务代码。

检查 Application 和 PairIP 组件：

```powershell
Select-String `
  -Path "$decoded\AndroidManifest.xml" `
  -Pattern '<application|pairip|LicenseContentProvider|LicenseActivity'
```

如果需要确认 Provider 的代码，可以额外生成只用于阅读的 smali 目录：

```powershell
java -jar $apktool d -f -r $base -o 'E:\lab\flare\smali-readonly'

rg -n 'initializeLicenseCheck|Lcom/pairip' `
  'E:\lab\flare\smali-readonly'
```

`-r` 保留原始资源但反汇编 DEX。这个目录只用于阅读，不拿来构建最终 APK。

## 7A. 样本一：AuraClean 的 Application 包装型修改

这一节对应导师给的第一个文件：

```text
E:\tem\auraclean_xapk\AuraClean.xapk
```

样本信息：

```text
应用名：AuraClean
包名：com.auraclean.clean
版本：V1.1.5 (versionCode 16)
minSdk：24
targetSdk：35
启动 Activity：gol.zli.mcc.activitys.MainActivity
```

### 7A.1 解包并选择 split

```powershell
.\scripts\01-Extract-Xapk.ps1 `
  -XapkPath 'E:\tem\auraclean_xapk\AuraClean.xapk' `
  -OutputDirectory 'E:\lab\auraclean\original'
```

该 XAPK 只提供 `armeabi-v7a` 原生库。ARM64 Android 设备如果支持 32 位兼容，可以安装以下集合：

```text
com.auraclean.clean.apk
config.armeabi_v7a.apk
config.hdpi.apk
config.en.apk
config.zh.apk
```

原包基线安装：

```powershell
$original = 'E:\lab\auraclean\original'

adb install-multiple -r `
  "$original\com.auraclean.clean.apk" `
  "$original\config.armeabi_v7a.apk" `
  "$original\config.hdpi.apk" `
  "$original\config.en.apk" `
  "$original\config.zh.apk"

adb logcat -c
adb shell am force-stop com.auraclean.clean
adb shell am start -W -n `
  com.auraclean.clean/gol.zli.mcc.activitys.MainActivity
Start-Sleep -Seconds 5
adb shell dumpsys window | Select-String 'mCurrentFocus|mFocusedApp'
adb shell pidof com.auraclean.clean
```

原包会转到未登录的 Google Play：[原包跳转截图](evidence/auraclean-original-google-play.png)。

### 7A.2 查看原始 Application 入口

可以不解码，先直接读取二进制 Manifest：

```powershell
$buildTools = "$env:LOCALAPPDATA\Android\Sdk\build-tools\37.0.0"
$base = 'E:\lab\auraclean\original\com.auraclean.clean.apk'

& "$buildTools\aapt2.exe" dump xmltree `
  --file AndroidManifest.xml $base |
  Select-String 'E: application|A: android:name' -Context 0,4
```

关键输出：

```text
E: application
A: android:name="com.pairip.application.Application"
```

这表明 Android 首先创建的是 PairIP 包装类，而不是业务 Application。

### 7A.3 找到包装类中触发校验的方法

创建阅读用 smali：

```powershell
$apktool = 'C:\tools\apktool_3.0.2.jar'

java -jar $apktool d -f -r `
  'E:\lab\auraclean\original\com.auraclean.clean.apk' `
  -o 'E:\lab\auraclean\smali-readonly'

rg -n 'checkLicense|com/pairip/application/Application|FeiApplication' `
  'E:\lab\auraclean\smali-readonly'
```

包装类内容：

```smali
.class public Lcom/pairip/application/Application;
.super Lgol/zli/mcc/FeiApplication;

.method protected attachBaseContext(Landroid/content/Context;)V
    .locals 0

    invoke-static {p1}, Lcom/pairip/licensecheck/LicenseClient;->checkLicense(Landroid/content/Context;)V
    invoke-super {p0, p1}, Lcom/pairip/application/Application;->attachBaseContext(Landroid/content/Context;)V
    return-void
.end method
```

这里可以得到两个重要结论：

1. `checkLicense()` 是 Google Play 校验的触发方法。
2. PairIP 包装类继承 `gol.zli.mcc.FeiApplication`，所以后者就是需要恢复的业务 Application。

还可以搜索业务代码对 `FeiApplication` 的引用进行交叉验证：

```powershell
rg -n 'Lgol/zli/mcc/FeiApplication' 'E:\lab\auraclean\smali-readonly'
```

该样本有大量业务类直接使用 `FeiApplication`，进一步证明它不是随便猜出的类名。

### 7A.4 两种可行思路及本次选择

方法补丁思路：删除或替换 `attachBaseContext()` 中这条调用：

```smali
invoke-static {p1}, Lcom/pairip/licensecheck/LicenseClient;->checkLicense(Landroid/content/Context;)V
```

这确实能阻止校验，但会修改 `classes2.dex`。之后必须重新编译 smali，验证范围更大。

本次实际思路：不修改任何方法，把 Manifest 的 Application 入口从包装类恢复为它的父类。Android 不再创建 PairIP 包装类，所以上面的 `attachBaseContext()` 永远不会执行。

原始 Manifest：

```xml
<application
    android:name="com.pairip.application.Application"
    ... >
```

修改后：

```xml
<application
    android:name="gol.zli.mcc.FeiApplication"
    ... >
```

这是比修改方法体更小、更容易证明的修改。

### 7A.5 解码并修改

构建用目录必须保留原始 DEX：

```powershell
java -jar $apktool d -f -s `
  'E:\lab\auraclean\original\com.auraclean.clean.apk' `
  -o 'E:\lab\auraclean\decoded-base'
```

打开：

```text
E:\lab\auraclean\decoded-base\AndroidManifest.xml
```

只替换 `<application>` 的 `android:name`：

```text
com.pairip.application.Application
    ->
gol.zli.mcc.FeiApplication
```

不要删除 `FeiApplication`，不要改 MainActivity，也不要编辑 smali-readonly 目录。

### 7A.6 重建、签名和安装

后面的第 8 至第 13 节是两个样本共用的流程。AuraClean 调用构建脚本时使用：

```powershell
.\scripts\02-Build-And-Sign.ps1 `
  -DecodedDirectory 'E:\lab\auraclean\decoded-base' `
  -OriginalSplitDirectory 'E:\lab\auraclean\original' `
  -OutputDirectory 'E:\lab\auraclean\patched' `
  -ApktoolJar 'C:\tools\apktool_3.0.2.jar' `
  -BuildToolsDirectory "$env:LOCALAPPDATA\Android\Sdk\build-tools\37.0.0" `
  -KeystorePath 'E:\lab\keys\android-lab.jks' `
  -KeyAlias 'android-lab' `
  -StorePassword 'android' `
  -BaseApkName 'com.auraclean.clean.apk' `
  -SplitNames @(
    'config.armeabi_v7a.apk',
    'config.hdpi.apk',
    'config.en.apk',
    'config.zh.apk'
  )
```

安装验证：

```powershell
.\scripts\03-Install-And-Verify.ps1 `
  -ApkDirectory 'E:\lab\auraclean\patched' `
  -PackageName 'com.auraclean.clean' `
  -MainActivity 'gol.zli.mcc.activitys.MainActivity' `
  -ApkNames @(
    'com.auraclean.clean.apk',
    'config.armeabi_v7a.apk',
    'config.hdpi.apk',
    'config.en.apk',
    'config.zh.apk'
  ) `
  -GrantCleanerPermissions
```

### 7A.7 证明“没有修改方法”

本次原包和实验包 DEX 哈希：

```text
classes.dex  7D63A8ED62BDF5DA6280E0FED374A5002EF106AC46A5FC905EAC776323D45179
classes2.dex C8840541CF64B9233642D1EA78AD931CA5CFC196224A29C2C5C9537BB4C1F14E
classes3.dex AFED18D16804D51FB3A0D97C5660C644B99EC9CFF10A4AB1F75F21A3B45D888E
classes4.dex F276C04F6A08714BAA2F1C74818DD262D10889436F76044E35DEAC66C5198DB0
```

四项前后完全一致。这就是“分析了方法，但最终没有修改方法”的直接证据。

修改后可正常进入 AuraClean 的 Cache Remove 页面：[实验版功能截图](evidence/auraclean-patched-cache-page.png)。

更完整的第一份样本记录见 [CASE_STUDY_AURACLEAN.md](CASE_STUDY_AURACLEAN.md)。

## 7B. 样本二：Flare Cleaner 的 Provider 型修改

Flare Cleaner 原始片段：

```xml
<activity
    android:exported="false"
    android:name="com.pairip.licensecheck.LicenseActivity" />
<provider
    android:authorities="com.flare.cleaner.storage.com.pairip.licensecheck.LicenseContentProvider"
    android:exported="false"
    android:name="com.pairip.licensecheck.LicenseContentProvider" />
<meta-data
    android:name="com.android.vending.splits.required"
    android:value="true" />
```

修改后：

```xml
<activity
    android:exported="false"
    android:name="com.pairip.licensecheck.LicenseActivity" />
<meta-data
    android:name="com.android.vending.splits.required"
    android:value="true" />
```

只删 `LicenseContentProvider` 的 `<provider .../>` 注册。保留 `LicenseActivity` 类和 DEX 内容不会触发检查，因为没有 Provider 自动调用 `LicenseClient`。

为什么不做更大修改：

- 不删 PairIP 整个包，减少误伤引用关系。
- 不伪造许可证响应，不需要理解加密协议。
- 不修改 MainActivity 和业务逻辑。
- 修改面越小，重建后越容易判断问题来自哪里。

## 8. 重建主 APK

```powershell
New-Item -ItemType Directory -Force -Path 'E:\lab\flare\patched'

java -jar $apktool b `
  'E:\lab\flare\decoded-base' `
  -o 'E:\lab\flare\patched\base-unsigned.apk'
```

正常输出应包含：

```text
Copying raw classes.dex...
Copying raw classes2.dex...
Building resources with aapt2...
Built apk into: ...base-unsigned.apk
```

Apktool 的 unresolved resource warning 不一定代表失败。以最后是否成功生成 APK、`aapt2 dump badging` 是否能读取、以及实机是否能安装为准。

## 9. 验证业务 DEX 没有变化

如果目标是“只改 Manifest”，必须验证所有 DEX 哈希相同。配套构建脚本会自动做这一步。

手工思路：分别从原 APK 和重建 APK 提取 `classes.dex`、`classes2.dex` 等，再计算 SHA-256：

```powershell
Get-FileHash -Algorithm SHA256 'original-dex\classes.dex'
Get-FileHash -Algorithm SHA256 'patched-dex\classes.dex'
```

本次四个结果均为 `unchanged=True`。如果哈希不同，先检查是否误用了反汇编后重新编译的 smali 目录。

## 10. 创建实验签名

重建 APK 后，Google/开发者原签名已经无效，需要自己的实验签名：

```powershell
keytool -genkeypair `
  -keystore 'E:\lab\keys\android-lab.jks' `
  -storepass android `
  -keypass android `
  -alias android-lab `
  -keyalg RSA `
  -keysize 2048 `
  -validity 3650 `
  -dname 'CN=Android Lab, OU=Research, O=Local, C=CN'
```

实验密码只适合本地学习。正式项目不要把密码写进脚本或仓库。

## 11. 对齐并统一签名所有 split

先确定 Build Tools 路径：

```powershell
$buildTools = 'C:\Users\你的用户名\AppData\Local\Android\Sdk\build-tools\37.0.0'
```

主 APK 先 zipalign：

```powershell
& "$buildTools\zipalign.exe" -f -p 4 `
  'E:\lab\flare\patched\base-unsigned.apk' `
  'E:\lab\flare\patched\com.flare.cleaner.storage.apk'
```

复制设备需要的原始 split：

```powershell
$original = 'E:\lab\flare\original'
$patched = 'E:\lab\flare\patched'

Copy-Item "$original\config.arm64_v8a.apk" $patched
Copy-Item "$original\config.xxhdpi.apk" $patched
Copy-Item "$original\config.en.apk" $patched
Copy-Item "$original\config.zh.apk" $patched
```

主 APK 和所有 split 必须使用同一证书重签：

```powershell
$apks = @(
  'com.flare.cleaner.storage.apk',
  'config.arm64_v8a.apk',
  'config.xxhdpi.apk',
  'config.en.apk',
  'config.zh.apk'
)

foreach ($apk in $apks) {
    & "$buildTools\apksigner.bat" sign `
      --ks 'E:\lab\keys\android-lab.jks' `
      --ks-key-alias android-lab `
      --ks-pass pass:android `
      --key-pass pass:android `
      --v1-signing-enabled true `
      --v2-signing-enabled true `
      --v3-signing-enabled true `
      --v4-signing-enabled false `
      "$patched\$apk"

    & "$buildTools\apksigner.bat" verify --verbose "$patched\$apk"
}
```

也可以直接使用配套脚本：

```powershell
.\scripts\02-Build-And-Sign.ps1 `
  -DecodedDirectory 'E:\lab\flare\decoded-base' `
  -OriginalSplitDirectory 'E:\lab\flare\original' `
  -OutputDirectory 'E:\lab\flare\patched' `
  -ApktoolJar 'C:\tools\apktool_3.0.2.jar' `
  -BuildToolsDirectory "$env:LOCALAPPDATA\Android\Sdk\build-tools\37.0.0" `
  -KeystorePath 'E:\lab\keys\android-lab.jks' `
  -KeyAlias 'android-lab' `
  -StorePassword 'android' `
  -BaseApkName 'com.flare.cleaner.storage.apk' `
  -SplitNames @(
    'config.arm64_v8a.apk',
    'config.xxhdpi.apk',
    'config.en.apk',
    'config.zh.apk'
  )
```

## 12. 安装实验版

如果设备上已经装有官方签名版本，直接覆盖会出现：

```text
INSTALL_FAILED_UPDATE_INCOMPATIBLE
```

只有在确认不需要保留该应用数据后，才执行：

```powershell
adb uninstall com.flare.cleaner.storage
```

卸载会清除应用私有数据，不能恢复。随后安装：

```powershell
$patched = 'E:\lab\flare\patched'

adb install-multiple -r `
  "$patched\com.flare.cleaner.storage.apk" `
  "$patched\config.arm64_v8a.apk" `
  "$patched\config.xxhdpi.apk" `
  "$patched\config.en.apk" `
  "$patched\config.zh.apk"
```

配套安装脚本不会自动卸载旧版本：

```powershell
.\scripts\03-Install-And-Verify.ps1 `
  -ApkDirectory 'E:\lab\flare\patched' `
  -PackageName 'com.flare.cleaner.storage' `
  -MainActivity 'com.liam.garbagecleaner.MainActivity' `
  -ApkNames @(
    'com.flare.cleaner.storage.apk',
    'config.arm64_v8a.apk',
    'config.xxhdpi.apk',
    'config.en.apk',
    'config.zh.apk'
  ) `
  -GrantCleanerPermissions
```

## 13. 配置清理应用需要的特殊权限

Android 的“所有文件访问”和“使用情况访问”不是普通运行时权限，实验机可以用 AppOps 配置：

```powershell
adb shell appops set com.flare.cleaner.storage MANAGE_EXTERNAL_STORAGE allow
adb shell appops set com.flare.cleaner.storage GET_USAGE_STATS allow
adb shell pm grant com.flare.cleaner.storage android.permission.POST_NOTIFICATIONS
```

也可以在系统设置中手工开启，这更接近普通用户流程。

注意：`MANAGE_EXTERNAL_STORAGE` 只允许访问共享存储，并不授予 `/data/app` 或其他应用私有目录的系统权限。

## 14. 验证标准

不要只看 `am start` 返回 `Status: ok`。至少验证以下项目：

### 14.1 冷启动

```powershell
adb logcat -c
adb shell am force-stop com.flare.cleaner.storage
adb shell am start -W -n `
  com.flare.cleaner.storage/com.liam.garbagecleaner.MainActivity

Start-Sleep -Seconds 5
adb shell dumpsys window | Select-String 'mCurrentFocus|mFocusedApp'
adb shell pidof com.flare.cleaner.storage
```

期望：

- 当前窗口是 Flare Cleaner 的 MainActivity；
- `pidof` 返回 PID；
- 不再出现 Google Play 页面。

### 14.2 日志

```powershell
adb logcat -d -v threadtime |
  Select-String 'pairip|LicenseActivity|FATAL EXCEPTION|AndroidRuntime'
```

期望：没有 PairIP 许可证 Activity 启动，没有 `FATAL EXCEPTION`。

### 14.3 页面功能

至少检查：

- 首页能显示存储占用。
- 清理入口能进入扫描页。
- 扫描能完成并显示分类。
- 不执行导师未要求的最终删除操作。

本次实机结果：冷启动约 390 ms，首页正常，缓存页扫描出 461.58 MB，其中 Cache 为 140.07 MB（11 项）。

## 15. 常见故障排查

### 15.1 仍然跳 Google Play

依次检查：

1. `dumpsys package` 中 Provider 是否仍注册。
2. Manifest 的 Application 是否是 `com.pairip.application.Application`。
3. 业务 Application 或 MainActivity 中是否直接调用 `LicenseClient`。
4. 是否实际安装了旧 APK，而不是刚构建的 APK。
5. 是否只有 base 重签、split 仍是旧签名，导致安装没有成功。

### 15.2 `INSTALL_FAILED_UPDATE_INCOMPATIBLE`

设备上存在相同包名、不同签名的版本。确认数据可丢弃后卸载旧版本，再安装完整 split 集合。

### 15.3 `Incremental installation not allowed`

某些三星/Android 13 设备不允许增量安装。新版 `adb` 通常会自动回退到普通安装；以命令末尾是否出现 `Success` 为准。必要时使用：

```powershell
adb install-multiple --no-incremental -r <apk列表>
```

### 15.4 Apktool 构建失败

- 确认 Apktool 和 aapt2 版本较新。
- 只改 Manifest 时优先用 `apktool d -s`，避免重编业务 smali。
- 不要混用“阅读用 smali 目录”和“构建用 decoded 目录”。
- 查看第一条真正的 `error:`，不要被大量 warning 淹没。

### 15.5 安装成功但崩溃

检查：

```powershell
adb logcat -d -v threadtime |
  Select-String 'FATAL EXCEPTION|SecurityException|UnsatisfiedLinkError|Resources.NotFoundException'
```

常见原因是缺 ABI split、资源 split 不匹配、应用自身校验重签证书，或者误改业务 DEX。

## 16. 每次任务的最小检查清单

1. 保留原始 XAPK 和 SHA-256。
2. 解包并阅读 `manifest.json`。
3. 根据设备 ABI、密度和语言选择 split。
4. 原包安装并记录失败基线。
5. 用窗口、PID 和 logcat 定位触发组件。
6. 判断 PairIP 是 Application 型还是 Provider 型。
7. 只做一个最小 Manifest 修改。
8. 重建并验证所有 DEX 哈希不变。
9. 用同一证书重签 base 和全部选中 split。
10. 安装、授权、冷启动、日志和功能页复验。
11. 保留截图、UI XML、日志和最终 APK。

两份导师样本的完整记录：

- [CASE_STUDY_AURACLEAN.md](CASE_STUDY_AURACLEAN.md)：Application 包装型。
- [CASE_STUDY_FLARE.md](CASE_STUDY_FLARE.md)：Provider 自动初始化型。
