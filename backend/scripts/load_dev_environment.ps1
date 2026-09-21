[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$envPath = Join-Path $repositoryRoot ".env"
if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
    throw "Local .env was not found. Run .\backend\scripts\configure_dev_environment.ps1 once."
}

foreach ($line in [System.IO.File]::ReadAllLines($envPath)) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
    $separator = $trimmed.IndexOf("=")
    if ($separator -le 0) { throw "Invalid entry in local .env." }
    $name = $trimmed.Substring(0, $separator).Trim()
    $value = $trimmed.Substring($separator + 1).Trim()
    if ($name -notin @(
        "BEAUTYHUB_DATABASE_URL",
        "BEAUTYHUB_TEST_DATABASE_URL",
        "BEAUTYHUB_PRIVATE_CODE_MASTER_KEY",
        "BEAUTYHUB_CRYPTOGRAPHY_KEY_VERSION",
        "BEAUTYHUB_TRUSTED_PROXY_CIDRS"
    )) { continue }
    [Environment]::SetEnvironmentVariable($name, $value, "Process")
}

$required = @(
    "BEAUTYHUB_DATABASE_URL",
    "BEAUTYHUB_TEST_DATABASE_URL",
    "BEAUTYHUB_PRIVATE_CODE_MASTER_KEY",
    "BEAUTYHUB_CRYPTOGRAPHY_KEY_VERSION"
)
foreach ($name in $required) {
    if (-not [Environment]::GetEnvironmentVariable($name, "Process")) {
        throw "$name is empty in local .env. Run the configuration script again."
    }
}
Write-Output "Loaded local BeautyHub environment without displaying secrets."
