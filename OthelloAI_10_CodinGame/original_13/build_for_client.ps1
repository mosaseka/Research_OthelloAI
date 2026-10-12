[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$projectDirectory = $PSScriptRoot
$sourcePath = Join-Path $projectDirectory 'OthelloAI_13.java'
$defaultParameterPath = Join-Path $projectDirectory 'resources\value_param.txt'
$bookPath = Join-Path $projectDirectory 'resources\book.txt'
$bundlePath = Join-Path $projectDirectory 'resources\model.properties'
$expectedBookHash =
    '39EB45BBE3E776462E5E4D1D21A686EEFDB280F35DD4A2C0F8B68509B3135F78'
$expectedParameterCount = 142812
$invariant = [Globalization.CultureInfo]::InvariantCulture
$numberStyle = [Globalization.NumberStyles]::Float

function Assert-EvaluatorParameter {
    param(
        [Parameter(Mandatory)]
        [string] $Path,
        [string] $ExpectedHash
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw ('Evaluation parameter file not found: {0}' -f $Path)
    }
    $count = 0
    foreach ($line in [IO.File]::ReadLines($Path)) {
        $count++
        if ([string]::IsNullOrWhiteSpace($line)) {
            throw ('Blank evaluation parameter at {0}:{1}' -f $Path, $count)
        }
        $value = 0.0
        if (-not [double]::TryParse(
                $line, $numberStyle, $invariant, [ref] $value) -or
            [double]::IsNaN($value) -or [double]::IsInfinity($value)) {
            throw ('Invalid evaluation parameter at {0}:{1}' -f $Path, $count)
        }
    }
    if ($count -ne $expectedParameterCount) {
        throw (
            'Evaluation parameter count mismatch for {0}: expected {1}, got {2}' -f
            $Path, $expectedParameterCount, $count
        )
    }
    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash
    if ($ExpectedHash -and $actualHash -ne $ExpectedHash.ToUpperInvariant()) {
        throw ('Evaluation parameter SHA-256 mismatch for {0}' -f $Path)
    }
    return $actualHash
}

function Read-ModelProperties {
    param([Parameter(Mandatory)][string] $Path)
    $properties = @{}
    foreach ($raw in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $line = $raw.Trim()
        if (-not $line -or $line.StartsWith('#') -or $line.StartsWith('!')) {
            continue
        }
        $separator = $line.IndexOf('=')
        if ($separator -le 0) {
            throw ('Invalid model property line: {0}' -f $raw)
        }
        $key = $line.Substring(0, $separator).Trim()
        $value = $line.Substring($separator + 1).Trim()
        if ($properties.ContainsKey($key)) {
            throw ('Duplicate model property: {0}' -f $key)
        }
        $properties[$key] = $value
    }
    return $properties
}

function Resolve-BundleFile {
    param(
        [Parameter(Mandatory)]
        [string] $ManifestPath,
        [Parameter(Mandatory)]
        [string] $ConfiguredPath
    )

    if ([IO.Path]::IsPathRooted($ConfiguredPath)) {
        return [IO.Path]::GetFullPath($ConfiguredPath)
    }
    return Join-Path (Split-Path $ManifestPath -Parent) $ConfiguredPath
}

foreach ($requiredPath in @($sourcePath, $defaultParameterPath, $bookPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw ('Required file not found: {0}' -f $requiredPath)
    }
}

$actualBookHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $bookPath).Hash
if ($actualBookHash -ne $expectedBookHash) {
    throw (
        'resources\book.txt differs from the validated opening book. ' +
        ('Expected SHA-256 {0}, got {1}' -f
            $expectedBookHash, $actualBookHash)
    )
}

$valueHash = Assert-EvaluatorParameter -Path $defaultParameterPath
$policyHash = $null
if (Test-Path -LiteralPath $bundlePath -PathType Leaf) {
    $bundle = Read-ModelProperties -Path $bundlePath
    if ($bundle['format'] -ne 'othello-model-bundle-v2' -or
        $bundle['feature.schema'] -ne 'exact-mobility-v1' -or
        $bundle['value.architecture'] -ne 'pattern-mlp-48x48-add8x8-v1' -or
        $bundle['value.output'] -ne 'black-win-logit-v1' -or
        $bundle['value.runtime-transform'] -ne 'tanh-half-logit-v1') {
        throw 'model.properties has an unsupported format or feature.schema'
    }
    foreach ($key in @('value.file', 'value.sha256')) {
        if (-not $bundle[$key]) {
            throw ('model.properties requires {0}' -f $key)
        }
    }
    $valuePath = Resolve-BundleFile `
        -ManifestPath $bundlePath -ConfiguredPath $bundle['value.file']
    $valueHash = Assert-EvaluatorParameter `
        -Path $valuePath -ExpectedHash $bundle['value.sha256']

    $hasPolicyFile = [bool] $bundle['policy.file']
    $hasPolicyHash = [bool] $bundle['policy.sha256']
    if ($hasPolicyFile -ne $hasPolicyHash) {
        throw 'model.properties policy.file and policy.sha256 must appear together'
    }
    if ($hasPolicyFile) {
        $policyPath = Resolve-BundleFile `
            -ManifestPath $bundlePath -ConfiguredPath $bundle['policy.file']
        $policyHash = Assert-EvaluatorParameter `
            -Path $policyPath -ExpectedHash $bundle['policy.sha256']
    }
}

$javac = Get-Command javac.exe -All -CommandType Application -ErrorAction Stop |
    Select-Object -First 1
Write-Host 'Compiling OthelloAI_13 for the existing Client.java...'
& $javac.Path '--release' '11' '-encoding' 'UTF-8' '-Xlint:all' `
    '-classpath' $projectDirectory '-d' $projectDirectory $sourcePath
if ($LASTEXITCODE -ne 0) {
    throw ('javac failed with exit code {0}' -f $LASTEXITCODE)
}

$mainClass = Join-Path $projectDirectory 'OthelloAI_13.class'
if (-not (Test-Path -LiteralPath $mainClass -PathType Leaf)) {
    throw ('Compilation finished without producing {0}' -f $mainClass)
}

Write-Host 'Client-compatible AI build completed.'
Write-Host ('Value parameter SHA-256: {0}' -f $valueHash)
if ($policyHash) {
    Write-Host ('Policy parameter SHA-256: {0}' -f $policyHash)
}
Write-Host ('Book SHA-256:            {0}' -f $actualBookHash)
Write-Host ''
Write-Host 'Run this command from the parent assignment directory:'
Write-Host '  java Client --ai original_13\OthelloAI_13'
