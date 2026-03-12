# Terraria Overlay

Overlay OBS avec 2 pages:
- `control.html`: page settings
- `overlay.html`: page a mettre en Browser Source dans OBS

Le backend est `server.py` (API + fichiers statiques).

## Demarrage rapide (dev)

```powershell
python server.py
```

Puis ouvrir:
- `http://127.0.0.1:8787/control.html`
- `http://127.0.0.1:8787/overlay.html`

## Executable unique

Un lanceur dedie est fourni: `overlay_launcher.py`.

Il:
- demarre le serveur
- ouvre `settings + overlay`
- choisit automatiquement un port libre
- persiste `state.json` et `deaths.txt`

### Build de l'exe

```powershell
.\build-overlay-exe.ps1
```

Sortie:
- `dist/terraria_overlay.exe`

### Lancer l'exe

Double-cliquer `dist/terraria_overlay.exe`.

## Fonctionnalites principales

- Activation/desactivation de tous les ilots
- Carrousel boss/NPC avec mode anti-spoil (affiche seulement les coches)
- Deplacement live des ilots (drag dans l'overlay) + offsets X/Y dans settings
- Synchronisation du run timer avec le temps de jeu du joueur Terraria
- Validation stricte des patches API + garde-fous sur les ranges
- Logs structures dans `server.log` (dossier data)
