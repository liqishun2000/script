[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$XapkPath,

    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$resolvedXapk = (Resolve-Path -LiteralPath $XapkPath).Path

if (Test-Path -LiteralPath $OutputDirectory) {
    $existing = @(Get-ChildItem -LiteralPath $OutputDirectory -Force)
    if ($existing.Count -gt 0) {
        throw "OutputDirectory is not empty: $OutputDirectory"
    }
} else {
    New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
}

tar -xf $resolvedXapk -C $OutputDirectory
if ($LASTEXITCODE -ne 0) {
    throw "Failed to extract XAPK: $resolvedXapk"
}

$manifestPath = Join-Path $OutputDirectory 'manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath)) {
    throw "manifest.json was not found. The input may not be a standard XAPK."
}

$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json

Write-Host "Package : $($manifest.package_name)"
Write-Host "Name    : $($manifest.name)"
Write-Host "Version : $($manifest.version_name) ($($manifest.version_code))"
Write-Host "Min SDK : $($manifest.min_sdk_version)"
Write-Host 'Splits  :'
$manifest.split_apks | ForEach-Object {
    Write-Host "  $($_.id) -> $($_.file)"
}

Write-Host "`nExtracted to: $OutputDirectory"

