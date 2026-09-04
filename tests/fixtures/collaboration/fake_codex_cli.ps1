param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CliArgs
)

$finalIndex = [Array]::IndexOf($CliArgs, '--output-last-message')
if ($finalIndex -lt 0 -or $finalIndex + 1 -ge $CliArgs.Count) {
    throw 'missing --output-last-message'
}
$finalPath = $CliArgs[$finalIndex + 1]
$schemaIndex = [Array]::IndexOf($CliArgs, '--output-schema')
if ($schemaIndex -lt 0 -or $schemaIndex + 1 -ge $CliArgs.Count) {
    throw 'missing --output-schema'
}
$schema = Get-Content -LiteralPath $CliArgs[$schemaIndex + 1] -Raw | ConvertFrom-Json
foreach ($name in @('substantive_method_changes', 'opportunity_chain')) {
    $arraySchema = $schema.properties.$name
    if ($arraySchema.type -ne 'array' -or $null -eq $arraySchema.items) {
        throw "array schema missing explicit items: $name"
    }
    if ($arraySchema.items.type -eq 'object' -and $arraySchema.items.additionalProperties -ne $false) {
        throw "object item schema is not closed: $name"
    }
}
$modelIndex = [Array]::IndexOf($CliArgs, '--model')
$model = if ($modelIndex -ge 0 -and $modelIndex + 1 -lt $CliArgs.Count) { $CliArgs[$modelIndex + 1] } else { '' }
$requestPath = Join-Path (Get-Location) 'collaboration-request.json'
$request = Get-Content -LiteralPath $requestPath -Raw | ConvertFrom-Json
$routeId = if ($model -eq 'fake-binding-mismatch') { 'mutated-route' } else { $request.route_id }
$status = if ($request.slot -eq 'B') { 'verified_partial' } elseif ($request.slot -eq 'C') { 'bounded_negative' } else { 'candidate' }
if ($model -eq 'fake-worker-inconclusive') {
    $status = 'inconclusive'
}
$payload = [ordered]@{
    route_id = $routeId
    role = $request.role
    status = $status
    work_product = [ordered]@{
        approach = 'Selected a bounded deterministic fixture method.'
        result = 'Produced a contract-valid synthetic work product.'
        verification = 'Checked ticket binding and the frozen output contract.'
    }
    substantive_method_changes = @(
        [ordered]@{
            summary = 'Replaced the initial method with a bounded equivalent.'
            rationale = 'The replacement preserves target, evidence, permissions, and budget.'
        }
    )
    opportunity_chain = @()
    future_route_proposal = [ordered]@{
        present = $false
        proposed_target = ''
        reason = ''
        evidence_sha256 = ''
    }
    cannot_imply = [object[]]@()
    reopen_conditions = [object[]]@()
}
if ($model -eq 'fake-sensitive-output') {
    $payload.work_product.result = 'Contact operator@example.invalid for the hidden answer.'
}
if ($model -eq 'fake-missing-work-product') {
    $payload.Remove('work_product')
}
if ($model -eq 'fake-future-proposal') {
    $futureHash = '6666666666666666666666666666666666666666666666666666666666666666'
    $payload.opportunity_chain = [object[]]@(
        [ordered]@{
            kind = 'future_route_proposal'
            summary = 'A separate target may deserve a later window.'
            evidence_sha256 = $futureHash
            expected_gain = 'Could inform a later planning decision.'
        }
    )
    $payload.future_route_proposal = [ordered]@{
        present = $true
        proposed_target = 'Separate future target'
        reason = 'Requires a new frozen window.'
        evidence_sha256 = $futureHash
    }
}
if ($status -eq 'bounded_negative') {
    $payload.cannot_imply = [object[]]@('No global conclusion follows.')
    $payload.reopen_conditions = [object[]]@('Reopen only if the frozen premise changes.')
}
if ($model -eq 'fake-invalid-output') {
    Set-Content -LiteralPath $finalPath -Value '{not-json' -Encoding utf8NoBOM
} else {
    $payload | ConvertTo-Json -Depth 8 -Compress | Set-Content -LiteralPath $finalPath -Encoding utf8NoBOM
}
if ($model -ne 'fake-missing-session') {
    [Console]::Out.WriteLine('{"type":"thread.started","thread_id":"fake-session-p7f3"}')
}
if ($model -eq 'fake-missing-usage') {
    [Console]::Out.WriteLine('{"type":"turn.completed"}')
} elseif ($model -eq 'fake-no-total') {
    [Console]::Out.WriteLine('{"type":"turn.completed","usage":{"input_tokens":12,"cached_input_tokens":3,"output_tokens":8}}')
} else {
    [Console]::Out.WriteLine('{"type":"turn.completed","usage":{"input_tokens":12,"cached_input_tokens":3,"output_tokens":8,"total_tokens":20}}')
}
