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

$documentsDir = [Environment]::GetFolderPath("MyDocuments")
$deathSource = Join-Path $documentsDir "My Games\Terraria\tModLoader\Death Counter\$playerName.txt"
$deathDest   = Join-Path $OverlayDir "deaths.txt"
$deathSyncEnabled = $true

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

$pythonExe = $python.Source
$pythonArgsPrefix = @()
if (((Split-Path $pythonExe -Leaf).ToLower()) -eq "py.exe") {
  $pythonArgsPrefix = @("-3")
}

try {
  $verOut = & $pythonExe @pythonArgsPrefix --version 2>&1
  if ($LASTEXITCODE -ne 0) { throw "Version Python non lisible." }
  if ($verOut -notmatch "Python\s+(\d+)\.(\d+)") { throw "Version Python invalide: $verOut" }
  $pyMajor = [int]$matches[1]
  $pyMinor = [int]$matches[2]
  if (($pyMajor -lt 3) -or ($pyMajor -eq 3 -and $pyMinor -lt 10)) {
    Err "Python 3.10+ requis. Version detectee: $verOut"
    exit 1
  }
  Info "Python OK: $verOut"
} catch {
  Err "Verification Python impossible: $($_.Exception.Message)"
  exit 1
}

Info "OverlayDir  : $OverlayDir"
Info "DeathSource : $deathSource"
Info "DeathDest   : $deathDest"
Write-Host ""

if (!(Test-Path -Path $deathSource)) {
  Warn "Death Counter introuvable au dÃ©marrage. Sync dÃ©sactivÃ©e, overlay utilisable sans ce mode."
  $deathSyncEnabled = $false
  try {
    Set-Content -Path $deathDest -Value "-" -NoNewline -Encoding UTF8
  } catch {
    Warn "Impossible d'initialiser deaths.txt: $($_.Exception.Message)"
  }
}

# Choose a safe port (8080 was blocked on your PC)
$portsToTry = @(8787, 18080, 5500, 3000, 8888, 9000)

$serverProc = $null
$portUsed   = $null
$serverOutLog = Join-Path $OverlayDir "server.stdout.log"
$serverErrLog = Join-Path $OverlayDir "server.stderr.log"

try { if (Test-Path $serverOutLog) { Remove-Item $serverOutLog -Force } } catch {}
try { if (Test-Path $serverErrLog) { Remove-Item $serverErrLog -Force } } catch {}

foreach ($p in $portsToTry) {
  try {
    Info "Tentative demarrage server.py sur port $p..."
    $env:OVERLAY_PORT = "$p"

    $pythonArgs = @()
    $pythonArgs += $pythonArgsPrefix
    $pythonArgs += @($serverPy)

    $serverProc = Start-Process -PassThru `
      -FilePath $pythonExe `
      -ArgumentList $pythonArgs `
      -WorkingDirectory $OverlayDir `
      -RedirectStandardOutput $serverOutLog `
      -RedirectStandardError $serverErrLog

    $ok = $false
    for ($try = 0; $try -lt 8; $try++) {
      Start-Sleep -Milliseconds 350

      if ($serverProc.HasExited) { break }

      try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$p/api/state" -UseBasicParsing -TimeoutSec 1
        if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
          $ok = $true
          break
        }
      } catch {
        # wait
      }
    }

    if ($ok) { $portUsed = $p; break }

    if ($serverProc -and $serverProc.HasExited) {
      $errTail = ""
      try { if (Test-Path $serverErrLog) { $errTail = (Get-Content $serverErrLog -Tail 8 -ErrorAction SilentlyContinue) -join " | " } } catch {}
      if (-not [string]::IsNullOrWhiteSpace($errTail)) {
        Warn "server.py a quitte juste apres demarrage: $errTail"
      } else {
        Warn "server.py a quitte juste apres demarrage sans log stderr."
      }
    }

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
  Err "Impossible de demarrer server.py sur tous les ports testes."
  if (Test-Path $serverErrLog) {
    Warn "Voir details dans: $serverErrLog"
    try {
      $tail = Get-Content $serverErrLog -Tail 20 -ErrorAction SilentlyContinue
      if ($tail) { Warn ("Dernieres lignes stderr: " + ($tail -join " | ")) }
    } catch {}
  } else {
    Warn "Aucun log stderr genere."
  }
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

if ($deathSyncEnabled) {
  Info "Sync du Death Counter -> deaths.txt (1/sec). CTRL+C pour arrêter."
} else {
  Info "Mode sans Death Counter actif. CTRL+C pour arrêter."
}
Write-Host ""

# Mirror loop
$lastContent = $null

try {
  while ($true) {
    if ($deathSyncEnabled) {
      try {
        if (Test-Path -Path $deathSource) {
          $content = Get-Content -Path $deathSource -Raw -ErrorAction Stop
          if ($content -ne $lastContent) {
            # Ecriture UTF-8 pour conserver les caracteres eventuels.
            Set-Content -Path $deathDest -Value $content -NoNewline -Encoding UTF8
            $lastContent = $content
          }
        } else {
          Warn "Death Counter introuvable pendant le run. Sync désactivée."
          $deathSyncEnabled = $false
          Set-Content -Path $deathDest -Value "-" -NoNewline -Encoding UTF8
        }
      } catch {
        Warn "Erreur sync: $($_.Exception.Message)"
      }
    }

    Start-Sleep -Seconds 1
  }
}
finally {
  if ($serverProc -and !$serverProc.HasExited) {
    Info "ArrÃªt serveur..."
    try { Stop-Process -Id $serverProc.Id -Force } catch {}
  }
}

