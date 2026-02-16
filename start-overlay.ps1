# ==========================================
# Terraria Overlay Starter (API server + Sync deaths)
# - Ask Terraria character name
# - Mirror tModLoader Death Counter file -> ./deaths.txt (1/sec)
# - Start server.py on a safe port
# - Open control + overlay
# ==========================================

$ErrorActionPreference = "Stop"

function Info($msg){ Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Warn($msg){ Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Err ($msg){ Write-Host "[ERR ] $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "=== Terraria Overlay Starter ===" -ForegroundColor Green
Write-Host ""

# Folder served = folder of this script
$OverlayDir = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($OverlayDir)) { $OverlayDir = (Get-Location).Path }

# Ask player name
$playerName = Read-Host "Nom EXACT du personnage Terraria (ex: Elias)"
if ([string]::IsNullOrWhiteSpace($playerName)) { Err "Nom du personnage vide."; exit 1 }

$deathSource = "C:\Users\Admin\Documents\My Games\Terraria\tModLoader\Death Counter\$playerName.txt"
$deathDest   = Join-Path $OverlayDir "deaths.txt"

# Required files
$serverPy    = Join-Path $OverlayDir "server.py"
$overlayHtml = Join-Path $OverlayDir "overlay.html"
$controlHtml = Join-Path $OverlayDir "control.html"

if (!(Test-Path $serverPy))    { Err "server.py introuvable dans $OverlayDir"; exit 1 }
if (!(Test-Path $overlayHtml)) { Err "overlay.html introuvable dans $OverlayDir"; exit 1 }
if (!(Test-Path $controlHtml)) { Err "control.html introuvable dans $OverlayDir"; exit 1 }

# Python check
$python = $null
try {
  $python = (Get-Command python -ErrorAction SilentlyContinue)
  if (-not $python) { $python = (Get-Command py -ErrorAction SilentlyContinue) }
} catch {}
if (-not $python) { Err "Python introuvable. Installe Python 3 (Add to PATH)."; exit 1 }

Info "OverlayDir  : $OverlayDir"
Info "DeathSource : $deathSource"
Info "DeathDest   : $deathDest"
Write-Host ""

# Choose a safe port (8080 was blocked on your PC)
$portsToTry = @(8787, 18080, 5500, 3000, 8888, 9000)

$serverProc = $null
$portUsed   = $null

foreach ($p in $portsToTry) {
  try {
    Info "Tentative démarrage server.py sur port $p..."
    $env:OVERLAY_PORT = "$p"

    $serverProc = Start-Process -PassThru `
      -FilePath $python.Source `
      -ArgumentList @($serverPy) `
      -WorkingDirectory $OverlayDir

    Start-Sleep -Milliseconds 900

    $ok = $false
    try {
      $tnc = Test-NetConnection -ComputerName "127.0.0.1" -Port $p -WarningAction SilentlyContinue
      $ok = $tnc.TcpTestSucceeded
    } catch {}

    if ($ok) { $portUsed = $p; break }

    # Not ok -> stop and try next port
    try { Stop-Process -Id $serverProc.Id -Force } catch {}
    $serverProc = $null
  } catch {
    Warn "Port $p impossible: $($_.Exception.Message)"
    if ($serverProc) { try { Stop-Process -Id $serverProc.Id -Force } catch {} }
    $serverProc = $null
  }
}

if (-not $portUsed) {
  Err "Impossible de démarrer server.py. Un antivirus/politique Windows bloque les ports."
  Err "Essaie PowerShell en admin ou autorise python dans le pare-feu."
  exit 1
}

$controlUrl = "http://127.0.0.1:$portUsed/control.html"
$overlayUrl = "http://127.0.0.1:$portUsed/overlay.html"

Write-Host ""
Info "Serveur OK sur port $portUsed"
Info "Control: $controlUrl"
Info "Overlay : $overlayUrl"
Write-Host ""

Start-Process $controlUrl | Out-Null
Start-Process $overlayUrl | Out-Null

Info "Sync du Death Counter -> deaths.txt (1/sec). CTRL+C pour arrêter."
Write-Host ""

# Mirror loop
$lastContent = $null

try {
  while ($true) {
    try {
      if (Test-Path -Path $deathSource) {
        $content = Get-Content -Path $deathSource -Raw -ErrorAction Stop
        if ($content -ne $lastContent) {
          # Keep it simple: write as ASCII
          Set-Content -Path $deathDest -Value $content -NoNewline -Encoding ASCII
          $lastContent = $content
        }
      } else {
        Warn "Death Counter introuvable: $deathSource"
      }
    } catch {
      Warn "Erreur sync: $($_.Exception.Message)"
    }

    Start-Sleep -Seconds 1
  }
}
finally {
  if ($serverProc -and !$serverProc.HasExited) {
    Info "Arrêt serveur..."
    try { Stop-Process -Id $serverProc.Id -Force } catch {}
  }
}
