[CmdletBinding()]
param(
    [string]$PostgresUser = "postgres",
    [string]$PostgresHost = "127.0.0.1",
    [int]$PostgresPort = 5432,
    [string]$TestTarget = "backend/tests/integration"
)

$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$loader = Join-Path $repositoryRoot "backend\scripts\load_dev_environment.ps1"
if (Test-Path -LiteralPath (Join-Path $repositoryRoot ".env") -PathType Leaf) {
    . $loader
}
$testDatabaseUrl = $env:BEAUTYHUB_TEST_DATABASE_URL
$securePassword = $null
$credential = $null
$plainPassword = $null
$encodedUser = $null
$encodedPassword = $null
if (-not $testDatabaseUrl) {
    $securePassword = Read-Host "Local PostgreSQL password" -AsSecureString
    $credential = [System.Management.Automation.PSCredential]::new(
        $PostgresUser,
        $securePassword
    )
    $plainPassword = $credential.GetNetworkCredential().Password
    $encodedUser = [Uri]::EscapeDataString($PostgresUser)
    $encodedPassword = [Uri]::EscapeDataString($plainPassword)
    $testDatabaseUrl = "postgresql+psycopg://{0}:{1}@{2}:{3}/beautyhub_test" -f $encodedUser, $encodedPassword, $PostgresHost, $PostgresPort
}
$python = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$resolvedTarget = (Resolve-Path -LiteralPath (Join-Path $repositoryRoot $TestTarget)).Path
$integrationRoot = (Resolve-Path (Join-Path $repositoryRoot "backend\tests\integration")).Path
if (
    $resolvedTarget -ne $integrationRoot -and
    -not $resolvedTarget.StartsWith("$integrationRoot\", [System.StringComparison]::OrdinalIgnoreCase)
) {
    throw "TestTarget must be inside backend/tests/integration."
}

try {
    $env:BEAUTYHUB_TEST_DATABASE_URL = $testDatabaseUrl
    & $python -m pytest $resolvedTarget
    exit $LASTEXITCODE
}
finally {
    Remove-Item Env:BEAUTYHUB_TEST_DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Variable securePassword, credential, plainPassword, encodedUser, encodedPassword, testDatabaseUrl -ErrorAction SilentlyContinue
}
