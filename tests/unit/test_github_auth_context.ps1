[CmdletBinding()]
param()

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)

$script:assertions = 0
function Assert-True([bool]$Condition, [string]$Message) {
    $script:assertions++
    if (-not $Condition) { throw "ASSERT: $Message" }
}

function Invoke-ClassificationCase(
    [string]$Doctor,
    [string]$Identity,
    [int]$ExpectedExit,
    [string]$ExpectedContext,
    [string]$ExpectedStatus,
    [bool]$EnvironmentTokenPresent = $false
) {
    $pwsh = Join-Path $PSHOME 'pwsh.exe'
    $psi = [Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $pwsh
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    if ($EnvironmentTokenPresent) { $psi.Environment['GH_TOKEN'] = 'test-token-placeholder' }
    foreach ($argument in @(
        '-NoLogo', '-NoProfile', '-NonInteractive', '-File', $Doctor,
        '-Json', '-ClassificationOnly', '-IdentityOverride', $Identity
    )) { [void]$psi.ArgumentList.Add($argument) }
    $process = [Diagnostics.Process]::Start($psi)
    try {
        $stdout = $process.StandardOutput.ReadToEnd()
        $stderr = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        Assert-True ($process.ExitCode -eq $ExpectedExit) "Unexpected exit for $Identity. stderr=$stderr"
        Assert-True (-not [string]::IsNullOrWhiteSpace($stdout)) "No JSON for $Identity"
        Assert-True ($stdout -notmatch 'gh[oprsu]_[A-Za-z0-9]') "Output exposed a GitHub token for $Identity"
        $result = $stdout.Trim() | ConvertFrom-Json -AsHashtable -Depth 16
        Assert-True ([string]$result.context -ceq $ExpectedContext) "Unexpected context for $Identity"
        Assert-True ([string]$result.status -ceq $ExpectedStatus) "Unexpected status for $Identity"
        Assert-True (-not [bool]$result.token_value_exposed) "Doctor claims it exposed a token for $Identity"
    }
    finally { $process.Dispose() }
}

function Invoke-FakeGhCase(
    [string]$Doctor,
    [int]$AuthExit,
    [int]$ApiExit,
    [int]$ExpectedExit,
    [string]$ExpectedStatus
) {
    $systemTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    $tempRoot = Join-Path $systemTemp ("github-auth-doctor-test-" + [guid]::NewGuid().ToString('N'))
    [void](New-Item -ItemType Directory -Path $tempRoot)
    try {
        $fakeGh = Join-Path $tempRoot 'gh.cmd'
        @(
            '@echo off'
            ('if "%1"=="auth" exit /b {0}' -f $AuthExit)
            'if "%1"=="api" ('
            $(if ($ApiExit -eq 0) { '  echo westwhile' } else { '  rem simulated API failure' })
            ('  exit /b {0}' -f $ApiExit)
            ')'
            'exit /b 1'
        ) | Set-Content -LiteralPath $fakeGh -Encoding Ascii

        $pwsh = Join-Path $PSHOME 'pwsh.exe'
        $psi = [Diagnostics.ProcessStartInfo]::new()
        $psi.FileName = $pwsh
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.Environment['PATH'] = "$tempRoot$([IO.Path]::PathSeparator)$($psi.Environment['PATH'])"
        foreach ($argument in @(
            '-NoLogo', '-NoProfile', '-NonInteractive', '-File', $Doctor,
            '-Json', '-IdentityOverride', 'I\ResearchUser'
        )) { [void]$psi.ArgumentList.Add($argument) }
        $process = [Diagnostics.Process]::Start($psi)
        try {
            $stdout = $process.StandardOutput.ReadToEnd()
            $stderr = $process.StandardError.ReadToEnd()
            $process.WaitForExit()
            Assert-True ($process.ExitCode -eq $ExpectedExit) "Unexpected fake-gh exit. stderr=$stderr"
            Assert-True (-not [string]::IsNullOrWhiteSpace($stdout)) 'Fake-gh case returned no JSON'
            Assert-True ($stdout -notmatch 'gh[oprsu]_[A-Za-z0-9]') 'Fake-gh case exposed a GitHub token'
            $result = $stdout.Trim() | ConvertFrom-Json -AsHashtable -Depth 16
            Assert-True ([string]$result.status -ceq $ExpectedStatus) 'Unexpected fake-gh status'
            Assert-True (-not [bool]$result.token_value_exposed) 'Fake-gh result claims it exposed a token'
        }
        finally { $process.Dispose() }
    }
    finally {
        $resolvedTemp = [IO.Path]::GetFullPath($tempRoot)
        if (-not $resolvedTemp.StartsWith($systemTemp, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clean an unexpected path: $resolvedTemp"
        }
        if (Test-Path -LiteralPath $resolvedTemp) { Remove-Item -LiteralPath $resolvedTemp -Recurse -Force }
    }
}

$doctor = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'scripts\check_github_auth_context.ps1'
if (-not (Test-Path -LiteralPath $doctor -PathType Leaf)) { throw "GitHub auth context doctor is missing: $doctor" }

Invoke-ClassificationCase $doctor 'i\CodexSandboxOnline' 3 'codex_sandbox' 'requires_windows_user_context'
Invoke-ClassificationCase $doctor 'I\ResearchUser' 0 'windows_user' 'user_context_detected'
Invoke-ClassificationCase $doctor 'i\CodexSandboxOnline' 4 'codex_sandbox' 'environment_token_refused' $true
Invoke-FakeGhCase $doctor 1 1 1 'authentication_failed_in_user_context'
Invoke-FakeGhCase $doctor 0 1 6 'github_api_verification_failed'
Invoke-FakeGhCase $doctor 0 0 0 'authenticated'

[pscustomobject]@{
    ok = $true
    assertions = $script:assertions
    cases = 6
} | ConvertTo-Json
