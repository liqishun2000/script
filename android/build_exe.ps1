param(
    [string]$Python = "python",
    [string]$PlatformTools = "$env:LOCALAPPDATA\Android\Sdk\platform-tools"
)

$ErrorActionPreference = "Stop"
$projectDir = $PSScriptRoot
$buildDir = Join-Path $projectDir "build"
$requiredFiles = @(
    "adb.exe",
    "AdbWinApi.dll",
    "AdbWinUsbApi.dll",
    "libwinpthread-1.dll"
)

foreach ($file in $requiredFiles) {
    $path = Join-Path $PlatformTools $file
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Missing Android platform-tools file: $path"
    }
}

& $Python -c "import PyInstaller, tkinterdnd2"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller and tkinterdnd2 must be installed in the selected Python environment."
}

New-Item -ItemType Directory -Path $buildDir -Force | Out-Null

$arguments = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--name", "XAPKInstaller",
    "--distpath", (Join-Path $projectDir "dist"),
    "--workpath", $buildDir,
    "--specpath", $buildDir,
    "--collect-all", "tkinterdnd2"
)

foreach ($file in $requiredFiles) {
    $source = Join-Path $PlatformTools $file
    $arguments += @("--add-binary", "$source;platform-tools")
}

$notice = Join-Path $PlatformTools "NOTICE.txt"
if (Test-Path -LiteralPath $notice -PathType Leaf) {
    $arguments += @("--add-data", "$notice;platform-tools")
}

$arguments += (Join-Path $projectDir "install_xapk.py")
& $Python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

$output = Join-Path $projectDir "dist\XAPKInstaller.exe"
Write-Output "Built: $output"
