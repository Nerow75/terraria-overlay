# Terraria Overlay

Overlay local pour stream Terraria avec une page de controle OBS et une page d'affichage a injecter en Browser Source.

Le projet est concu pour un usage solo en local, sans base de donnees ni service tiers.

## Structure

```text
.
|-- data/     # etat runtime local, logs
|-- docs/     # documentation projet
|-- scripts/  # lancement et build Windows
|-- src/      # backend Python
`-- web/      # pages OBS et assets statiques
```

## Ce que fait le projet

- `web/control.html` : interface de pilotage du run.
- `web/overlay.html` : page d'overlay a charger dans OBS.
- `src/server.py` : serveur HTTP local + API JSON + persistance.
- `src/overlay_launcher.py` : lanceur desktop qui choisit un port libre et ouvre les pages.

## Fonctionnalites

- Suivi boss et PNJ avec progression persistante.
- Mode anti-spoil pour le carrousel.
- Timer de run avec synchronisation sur le temps de jeu de la sauvegarde joueur.
- Deplacement live des ilots dans l'overlay.
- Selection automatique du joueur et du monde Terraria les plus recents.
- Synchronisation optionnelle de `data/deaths.txt` depuis le mod tModLoader Death Counter.

## Perimetre

- Cible principale : Windows + Terraria + OBS.
- Le serveur ecoute uniquement sur `127.0.0.1`.
- Le projet est pense pour un usage local. Il n'y a pas d'authentification et il ne doit pas etre expose sur le reseau.

## Demarrage rapide

### Option 1 - Script Windows

```powershell
.\scripts\start-overlay.ps1
```

Le script :

- demande le nom exact du personnage Terraria pour synchroniser les morts ;
- demarre `src/server.py` sur un port local libre ;
- ouvre automatiquement la page de controle et la page d'overlay.

### Option 2 - Python direct

```powershell
python .\src\overlay_launcher.py
```

Ou, si vous voulez seulement le serveur :

```powershell
python .\src\server.py
```

Pages utiles :

- `http://127.0.0.1:8787/` redirige vers `control.html`
- `http://127.0.0.1:8787/control.html`
- `http://127.0.0.1:8787/overlay.html`

## Integration OBS

Ajoutez `overlay.html` comme Browser Source dans OBS. La page `control.html` reste ouverte dans un navigateur classique pour piloter l'overlay en direct.

## Build de l'executable

Prerequis :

- Python 3.10+
- `PyInstaller` installe dans l'interprete utilise pour le build

Commande :

```powershell
.\scripts\build-overlay-exe.ps1
```

Sortie attendue :

- `dist/terraria_overlay.exe`

Le build embarque `web/`. En mode PyInstaller onefile, les fichiers de donnees (`state.json`, `deaths.txt`, `server.log`) sont persistes dans `data/` a cote de l'executable.

## Dependances

Le projet tourne en standard library Python.

Dependance optionnelle :

- `cryptography` pour ameliorer la lecture de certaines sauvegardes joueur `.plr`

Exemple :

```powershell
python -m pip install cryptography
```

## Variables d'environnement utiles

- `OVERLAY_PORT` : force le port HTTP local.
- `OVERLAY_DATA_DIR` : force le dossier de persistance de `state.json`, `deaths.txt` et `server.log`.
- `TERRARIA_PLAYERS_PATH` : surcharge le dossier des joueurs Terraria.
- `TERRARIA_WORLDS_PATH` : surcharge le dossier des mondes Terraria.

## Fichiers generes localement

Ces fichiers sont crees automatiquement dans `data/` et sont ignores par Git :

- `data/state.json`
- `data/deaths.txt`
- `data/server.log`
- `data/server.stdout.log`
- `data/server.stderr.log`

## Garde-fous deja en place

- Serveur local uniquement (`127.0.0.1`).
- Validation stricte des patches JSON avant ecriture disque.
- Limites sur les champs texte et numeriques.
- Rate limiting sur `POST /api/state`.
- Limite de taille sur le corps des requetes API.
- Desactivation du listing de repertoire HTTP.
- Logs structures dans `data/server.log`.

## Developpement

Verification minimale :

```powershell
python -m py_compile .\src\server.py .\src\terraria_parser.py .\src\overlay_launcher.py
```

Documentation annexe :

- [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)
- [docs/CODE_STYLE.md](docs/CODE_STYLE.md)
- [docs/SECURITY.md](docs/SECURITY.md)

## Publication

Le depot est maintenant pense pour etre public sans embarquer d'etat local ou de donnees de run a la racine. Si vous publiez le projet sur GitHub, il reste seulement a choisir la licence qui vous convient.
