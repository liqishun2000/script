[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DecodedDirectory,

    [Parameter(Mandatory = $true)]
    [string]$OriginalSplitDirectory,

    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,

    [Parameter(Mandatory = $true)]
    [string]$ApktoolJar,

    [Parameter(Mandatory = $true)]
    [string]$BuildToolsDirectory,

    [Parameter(Mandatory = $true)]
    [string]$KeystorePath,

    [Parameter(Mandatory = $true)]
    [string]$KeyAlias,

    [Parameter(Mandatory = $true)]
    [string]$StorePassword,

    [Parameter(Mandatory = $true)]
    [string]$BaseApkName,

    [string[]]$SplitNames = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-File([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
}

function Get-ZipEntrySha256([string]$ZipPath, [string]$EntryName) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        $entry = $archive.Entries | Where-Object { $_.FullName -eq $EntryName } | Select-Object -First 1
        if ($null -eq $entry) {
            throw "Entry not found in ${ZipPath}: $EntryName"
        }

        $stream = $entry.Open()
        $sha = [System.Security.Cryptography.SHA256]::Create()
        try {
            $bytes = $sha.ComputeHash($stream)
            return ([BitConverter]::ToString($bytes)).Replace('-', '')
        } finally {
            $sha.Dispose()
            $stream.Dispose()
        }
    } finally {
        $archive.Dispose()
    }
}

Assert-File $ApktoolJar 'Apktool JAR'
Assert-File $KeystorePath 'Keystore'

$zipalign = Join-Path $BuildToolsDirectory 'zipalign.exe'
$apksigner = Join-Path $BuildToolsDirectory 'apksigner.bat'
Assert-File $zipalign 'zipalign'
Assert-File $apksigner 'apksigner'

$originalBase = Join-Path $OriginalSplitDirectory $BaseApkName
Assert-File $originalBase 'Original base APK'

foreach ($splitName in $SplitNames) {
    Assert-File (Join-Path $OriginalSplitDirectory $splitName) "Split $splitName"
}

if (Test-Path -LiteralPath $OutputDirectory) {
    $existing = @(Get-ChildItem -LiteralPath $OutputDirectory -Force)
    if ($existing.Count -gt 0) {
        throw "OutputDirectory is not empty: $OutputDirectory"
    }
} else {
    New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
}

$unsignedBase = Join-Path $OutputDirectory 'base-unsigned.apk'
$signedBase = Join-Path $OutputDirectory $BaseApkName

& java -jar $ApktoolJar b $DecodedDirectory -o $unsignedBase
if ($LASTEXITCODE -ne 0) {
    throw 'Apktool build failed.'
}

& $zipalign -f -p 4 $unsignedBase $signedBase
if ($LASTEXITCODE -ne 0) {
    throw 'zipalign failed.'
}

foreach ($splitName in $SplitNames) {
    Copy-Item -LiteralPath (Join-Path $OriginalSplitDirectory $splitName) `
        -Destination (Join-Path $OutputDirectory $splitName)
}

$allApkNames = @($BaseApkName) + $SplitNames
foreach ($apkName in $allApkNames) {
    $apkPath = Join-Path $OutputDirectory $apkName

    & $apksigner sign `
        --ks $KeystorePath `
        --ks-key-alias $KeyAlias `
        --ks-pass "pass:$StorePassword" `
        --key-pass "pass:$StorePassword" `
        --v1-signing-enabled true `
        --v2-signing-enabled true `
        --v3-signing-enabled true `
        --v4-signing-enabled false `
        $apkPath

    if ($LASTEXITCODE -ne 0) {
        throw "Signing failed: $apkName"
    }

    & $apksigner verify --verbose $apkPath
    if ($LASTEXITCODE -ne 0) {
        throw "Signature verification failed: $apkName"
    }
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$originalArchive = [System.IO.Compression.ZipFile]::OpenRead($originalBase)
try {
    $dexNames = @(
        $originalArchive.Entries |
            Where-Object { $_.FullName -match '^classes([0-9]+)?\.dex$' } |
            ForEach-Object { $_.FullName }
    )
} finally {
    $originalArchive.Dispose()
}

Write-Host "`nDEX integrity check:"
foreach ($dexName in $dexNames) {
    $originalHash = Get-ZipEntrySha256 $originalBase $dexName
    $patchedHash = Get-ZipEntrySha256 $signedBase $dexName
    $unchanged = $originalHash -eq $patchedHash
    Write-Host "$dexName unchanged=$unchanged $originalHash"
    if (-not $unchanged) {
        throw "DEX changed unexpectedly: $dexName"
    }
}

Write-Host "`nSigned APK set: $OutputDirectory"

