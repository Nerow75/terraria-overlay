# Contribution

## Prerequis

- Python 3.10+ recommande.
- Lancement local via `.\scripts\start-overlay.ps1` ou `python .\src\server.py`.

## Workflow

1. Creer une branche de travail.
2. Appliquer les modifications minimales necessaires.
3. Verifier le code Python (`python -m py_compile .\src\server.py .\src\terraria_parser.py .\src\overlay_launcher.py`).
4. Verifier le rendu `web/control.html` et `web/overlay.html`.
5. Commit avec prefixe (`feat:`, `fix:`, `refactor:`, `chore:`).
6. Ouvrir une Pull Request.

## Regles de revue

- Priorite aux regressions fonctionnelles et aux risques live.
- Refuser les changements sans validation d'entree sur l'API.
- Refuser les commentaires non conformes (francais, impersonnels, utiles).
- Refuser les changements visuels sans verification sur `web/overlay.html`.

## Checklist avant merge

- Serveur compilable.
- Aucun crash si `deaths.txt` est absent.
- Polling stable et aucune surcharge API evidente.
- Config persistante apres redemarrage.
- Aucun fichier runtime local committe (`state.json`, `deaths.txt`, logs).
