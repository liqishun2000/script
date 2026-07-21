[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ApkDirectory,

    [Parameter(Mandatory = $true)]
    [string]$PackageName,

    [Parameter(Mandatory = $true)]
    [string]$MainActivity,

    [Parameter(Mandatory = $true)]
    [string[]]$ApkNames,

    [switch]$GrantCleanerPermissions
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$devices = @(adb devices | Select-String '\sdevice$')
if ($devices.Count -ne 1) {
    throw "Expected exactly one authorized adb device, found $($devices.Count)."
}

$apkPaths = @()
foreach ($apkName in $ApkNames) {
    $apkPath = Join-Path $ApkDirectory $apkName
    if (-not (Test-Path -LiteralPath $apkPath -PathType Leaf)) {
        throw "APK not found: $apkPath"
    }
    $apkPaths += $apkPath
}

Write-Host 'Installing APK set...'
& adb install-multiple --no-incremental -r @apkPaths
if ($LASTEXITCODE -ne 0) {
    Write-Warning 'Installation failed. If the error is UPDATE_INCOMPATIBLE, the installed app uses another certificate.'
    Write-Warning "After confirming its data can be deleted, uninstall manually: adb uninstall $PackageName"
    throw 'adb install-multiple failed.'
}

if ($GrantCleanerPermissions) {
    adb shell appops set $PackageName MANAGE_EXTERNAL_STORAGE allow
    adb shell appops set $PackageName GET_USAGE_STATS allow

    $requestedPermissions = adb shell dumpsys package $PackageName
    if ($requestedPermissions -match 'android.permission.POST_NOTIFICATIONS') {
        adb shell pm grant $PackageName android.permission.POST_NOTIFICATIONS
    }
}

adb logcat -c
adb shell am force-stop $PackageName

$component = "$PackageName/$MainActivity"
adb shell am start -W -n $component
if ($LASTEXITCODE -ne 0) {
    throw "Failed to start: $component"
}

Start-Sleep -Seconds 6

Write-Host "`nForeground window:"
adb shell dumpsys window | Select-String 'mCurrentFocus|mFocusedApp'

Write-Host "`nProcess ID:"
adb shell pidof $PackageName

Write-Host "`nRelevant log lines:"
$suspiciousLines = @(
    adb logcat -d -v threadtime |
        Select-String 'pairip|LicenseActivity|FATAL EXCEPTION|AndroidRuntime' |
        Select-Object -Last 80
)

if ($suspiciousLines.Count -eq 0) {
    Write-Host 'No PairIP activity or fatal exception was found.'
} else {
    $suspiciousLines
}

Write-Host "`nVerification finished. Confirm that the foreground window and PID belong to $PackageName."
