# Flare Cleaner 1.0.2 实战记录

## 样本信息

```text
输入：E:\tem\auraclean_xapk\Flare+Cleaner_1.0.2_APKPure.xapk
应用名：Flare Cleaner
包名：com.flare.cleaner.storage
版本：1.0.2 (versionCode 3)
minSdk：24
targetSdk：36
启动 Activity：com.liam.garbagecleaner.MainActivity
设备：Samsung SM-A716U
系统：Android 13 / API 33
ABI：arm64-v8a
```

原始主 APK 证书 SHA-256：

```text
7822CC9C207363D79965E8185D75B50F725F0139EFCFBBEAA5FD215BED7C31EF
```

## 原包测试结果

原包 split 安装成功，`am start` 也返回 `Status: ok`，但几百毫秒后：

```text
mCurrentFocus = com.android.vending/...UnauthenticatedMainActivity
Flare Cleaner PID = 空
```

日志中出现：

```text
com.flare.cleaner.storage/com.pairip.licensecheck.LicenseActivity
com.android.vending/com.google.android.finsky.unauthenticated.activity.UnauthenticatedMainActivity
```

因此“安装成功”不等于“应用可用”，必须检查前台窗口和进程。

## 静态定位

Manifest 中的 Application 是业务类：

```xml
android:name="com.liam.garbagecleaner.MyApplication"
```

所以它不是 Application 包装型。继续检查 PairIP 组件，找到：

```xml
<activity
    android:exported="false"
    android:name="com.pairip.licensecheck.LicenseActivity" />

<provider
    android:authorities="com.flare.cleaner.storage.com.pairip.licensecheck.LicenseContentProvider"
    android:exported="false"
    android:name="com.pairip.licensecheck.LicenseContentProvider" />
```

Provider 的 smali 明确显示：

```smali
.method public onCreate()Z
    .locals 2

    new-instance v0, Lcom/pairip/licensecheck/LicenseClient;
    invoke-virtual {p0}, Lcom/pairip/licensecheck/LicenseContentProvider;->getContext()Landroid/content/Context;
    move-result-object v1
    invoke-direct {v0, v1}, Lcom/pairip/licensecheck/LicenseClient;-><init>(Landroid/content/Context;)V
    invoke-virtual {v0}, Lcom/pairip/licensecheck/LicenseClient;->initializeLicenseCheck()V

    const/4 v0, 0x1
    return v0
.end method
```

结论：Provider 是启动许可证检查的入口。

## 实际修改

只从 Manifest 删除：

```xml
<provider android:authorities="com.flare.cleaner.storage.com.pairip.licensecheck.LicenseContentProvider" android:exported="false" android:name="com.pairip.licensecheck.LicenseContentProvider"/>
```

没有修改：

- `MyApplication`
- `MainActivity`
- `LicenseActivity` 类
- `classes.dex`
- `classes2.dex`
- `classes3.dex`
- `classes4.dex`
- 清理业务逻辑

## DEX 完整性验证

```text
classes.dex
BB8616179E03B3ABC6322142128A284848822139CC647761F3F8CF84ED64EF7F

classes2.dex
69C8DFA576CA5DF6D9900939460C1F5CA0A57A6A90C43E482678E19EC8E4BA45

classes3.dex
F795C5DD2FEB55C6A9271CC9A07CFD3E401C314AA4A1CD058D870C1578522317

classes4.dex
9B892741ED0E5ADCB71D4D99A65B3EB4F637FFC9FB72D87D6E40B97914481F3B
```

原包和实验包四项均一致。

## 实验版安装集合

```text
C:\Users\a\flare_cleaner_analysis\patched\com.flare.cleaner.storage.apk
C:\Users\a\flare_cleaner_analysis\patched\config.arm64_v8a.apk
C:\Users\a\flare_cleaner_analysis\patched\config.xxhdpi.apk
C:\Users\a\flare_cleaner_analysis\patched\config.en.apk
C:\Users\a\flare_cleaner_analysis\patched\config.zh.apk
```

这些 APK 使用同一张本地实验签名。`.idsig` 是 v4 增量签名附属文件，普通 `adb install-multiple` 不需要显式传入。

## 动态验证结果

最终冷启动：

```text
Status: ok
LaunchState: COLD
Activity: com.flare.cleaner.storage/com.liam.garbagecleaner.MainActivity
TotalTime: 390 ms
mCurrentFocus: com.flare.cleaner.storage/com.liam.garbagecleaner.MainActivity
PID: 12316
```

权限：

```text
MANAGE_EXTERNAL_STORAGE: allow
GET_USAGE_STATS: allow
POST_NOTIFICATIONS: granted
```

功能验证：

```text
首页：正常
存储占用：27%，28.04 GB / 128 GB
Cache Clean 页面：正常
扫描结果：461.58 MB Removable
Cache：140.07 MB，共 11 项
Obsolete APK files：320.87 MB
最终删除：未执行
```

截图位于：

```text
C:\Users\a\flare_cleaner_analysis\verified.png
C:\Users\a\flare_cleaner_analysis\cache_verified.png
```

## 从本次实验应掌握的关键点

1. `am start` 成功不代表应用留在自己的页面。
2. ContentProvider 可以在 Application 和 Activity 之前执行。
3. 先找触发入口，再决定修改点。
4. 最小修改比大范围删除类更容易验证。
5. split APK 必须统一重签。
6. 用 DEX 哈希证明没有改业务代码。
7. 结论要同时有静态代码和动态实机证据。

