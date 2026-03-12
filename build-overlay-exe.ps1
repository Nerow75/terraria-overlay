$ErrorActionPreference = "Stop"

Write-Host "Build terraria_overlay.exe..." -ForegroundColor Cyan

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

& $selected.exe @($selected.args + @("--clean", "--noconfirm", "overlay_launcher.spec"))
exit $LASTEXITCODE
