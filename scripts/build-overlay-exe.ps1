$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$SpecPath = Join-Path $ScriptDir "overlay_launcher.spec"

Set-Location $ProjectRoot

Write-Host "Build terraria_overlay.exe..." -ForegroundColor Cyan

if (!(Test-Path -LiteralPath $SpecPath)) {
  Write-Host "overlay_launcher.spec introuvable." -ForegroundColor Red
  exit 1
}

$candidates = @(
    @{ exe = "python"; args = @("-m", "PyInstaller") },
    @{ exe = "py"; args = @("-3.12", "-m", "PyInstaller") },
    @{ exe = "py"; args = @("-3.11", "-m", "PyInstaller") },
    @{ exe = "py"; args = @("-3", "-m", "PyInstaller") }
)

$selected = $null
foreach ($candidate in $candidates) {
    $cmd = Get-Command $candidate.exe -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    try {
        & $cmd.Source @($candidate.args + @("--version")) *> $null
        if ($LASTEXITCODE -eq 0) {
            $selected = @{ exe = $cmd.Source; args = $candidate.args }
            break
        }
    } catch {
        # essaye le prochain candidat
    }
}

if (-not $selected) {
    Write-Host "PyInstaller introuvable (aucun interprete compatible detecte)." -ForegroundColor Red
    exit 1
}

& $selected.exe @($selected.args + @("--clean", "--noconfirm", $SpecPath))
exit $LASTEXITCODE
