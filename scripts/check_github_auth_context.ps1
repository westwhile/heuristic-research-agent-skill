[CmdletBinding()]
param(
    [string]$ExpectedLogin = 'westwhile',
    [switch]$Json,
    [switch]$ClassificationOnly,
    [Parameter(DontShow = $true)][string]$IdentityOverride
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)

function Write-Result([System.Collections.IDictionary]$Result, [int]$ExitCode) {
    if ($Json) {
        $Result | ConvertTo-Json -Depth 16 -Compress
    }
    else {
        "status=$($Result.status)"
        "context=$($Result.context)"
        "authenticated=$($Result.authenticated)"
        if ($Result.login) { "login=$($Result.login)" }
        "guidance=$($Result.guidance)"
    }
    exit $ExitCode
}

$identity = if ([string]::IsNullOrWhiteSpace($IdentityOverride)) {
    [Security.Principal.WindowsIdentity]::GetCurrent().Name
}
else { $IdentityOverride }
$context = if ($identity -match '(?i)(^|\\)CodexSandbox') { 'codex_sandbox' } else { 'windows_user' }
$tokenVariables = @('GH_TOKEN', 'GITHUB_TOKEN', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN')
$environmentTokenPresent = @(
    $tokenVariables | Where-Object {
        -not [string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($_))
    }
).Count -gt 0

$result = [ordered]@{
    schema = 'github-auth-context-doctor/v1'
    status = 'unknown'
    context = $context
    authenticated = $false
    login = $null
    expected_login = $ExpectedLogin
    credential_source = 'windows_keyring_expected'
    environment_token_present = $environmentTokenPresent
    token_value_exposed = $false
    guidance = $null
}

if ($environmentTokenPresent) {
    $result.status = 'environment_token_refused'
    $result.credential_source = 'environment_override_detected'
    $result.guidance = 'Remove GH_TOKEN/GITHUB_TOKEN overrides and use the Windows keyring for this repository.'
    Write-Result $result 4
}

if ($context -eq 'codex_sandbox') {
    $result.status = 'requires_windows_user_context'
    $result.credential_source = 'windows_keyring_inaccessible_from_sandbox'
    $result.guidance = 'Run keyring-backed gh and authenticated git operations in the real Windows user context; do not copy a token into the sandbox.'
    Write-Result $result 3
}

if ($ClassificationOnly) {
    $result.status = 'user_context_detected'
    $result.guidance = 'Run without -ClassificationOnly to verify the keyring-backed GitHub account.'
    Write-Result $result 0
}

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    $result.status = 'gh_cli_missing'
    $result.guidance = 'Install GitHub CLI before running the release workflow.'
    Write-Result $result 5
}

$null = & gh auth status --active --hostname github.com 2>$null
$authStatusExit = $LASTEXITCODE
if ($authStatusExit -ne 0) {
    $result.status = 'authentication_failed_in_user_context'
    $result.guidance = 'Run gh auth login -h github.com in the real Windows user context, then rerun this doctor.'
    Write-Result $result 1
}

$loginOutput = & gh api user --jq .login 2>$null
$apiExit = $LASTEXITCODE
if ($apiExit -ne 0) {
    $result.status = 'github_api_verification_failed'
    $result.guidance = 'The keyring account is readable, but GitHub API verification failed. Check connectivity and retry; do not re-login based on this result alone.'
    Write-Result $result 6
}
$login = [string](@($loginOutput)[-1])
$result.login = $login.Trim()
if (-not [string]::IsNullOrWhiteSpace($ExpectedLogin) -and $result.login -cne $ExpectedLogin) {
    $result.status = 'unexpected_authenticated_account'
    $result.authenticated = $true
    $result.guidance = 'Switch the active GitHub CLI account before publishing this repository.'
    Write-Result $result 2
}

$result.status = 'authenticated'
$result.authenticated = $true
$result.guidance = 'Keyring-backed GitHub authentication is ready.'
Write-Result $result 0
