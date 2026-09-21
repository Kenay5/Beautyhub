[CmdletBinding()]
param(
    [string]$PostgresUser = "postgres",
    [string]$PostgresHost = "127.0.0.1",
    [int]$PostgresPort = 5432,
    [string]$DevelopmentDatabase = "beautyhub_dev",
    [string]$TestDatabase = "beautyhub_test"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$envPath = Join-Path $repositoryRoot ".env"

$securePassword = Read-Host "Local PostgreSQL password (leave empty if not required)" -AsSecureString
$credential = [System.Management.Automation.PSCredential]::new(
    $PostgresUser,
    $securePassword
)
$plainPassword = $credential.GetNetworkCredential().Password
$encodedUser = [Uri]::EscapeDataString($PostgresUser)
$credentials = $encodedUser
if ($plainPassword.Length -gt 0) {
    $credentials = "{0}:{1}" -f $encodedUser, ([Uri]::EscapeDataString($plainPassword))
}

$keyBytes = [byte[]]::new(32)
$randomNumberGenerator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try {
    # GetBytes is available on the Windows PowerShell/.NET versions supported by BeautyHub.
    $randomNumberGenerator.GetBytes($keyBytes)
}
finally {
    $randomNumberGenerator.Dispose()
}
$masterKey = [Convert]::ToBase64String($keyBytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
$runtimeUrl = "postgresql+psycopg://{0}@{1}:{2}/{3}" -f $credentials, $PostgresHost, $PostgresPort, $DevelopmentDatabase
$testUrl = "postgresql+psycopg://{0}@{1}:{2}/{3}" -f $credentials, $PostgresHost, $PostgresPort, $TestDatabase

$lines = @(
    "# Local-only BeautyHub development configuration. Never commit this file.",
    "BEAUTYHUB_DATABASE_URL=$runtimeUrl",
    "BEAUTYHUB_TEST_DATABASE_URL=$testUrl",
    "BEAUTYHUB_PRIVATE_CODE_MASTER_KEY=$masterKey",
    "BEAUTYHUB_CRYPTOGRAPHY_KEY_VERSION=v1",
    "BEAUTYHUB_TRUSTED_PROXY_CIDRS="
)
[System.IO.File]::WriteAllLines($envPath, $lines, [System.Text.UTF8Encoding]::new($false))

Remove-Variable securePassword, credential, plainPassword, encodedUser, credentials, keyBytes, randomNumberGenerator, masterKey, runtimeUrl, testUrl -ErrorAction SilentlyContinue
Write-Output "Created local configuration at .env (secrets were not displayed)."
Write-Output "Load it in each new PowerShell session with: . .\backend\scripts\load_dev_environment.ps1"
