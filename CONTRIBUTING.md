# Contribution

## Prerequis
- Python 3.10+ recommande.
- Lancement local via `start-overlay.ps1` ou `python server.py`.

## Workflow
1. Creer une branche de travail.
2. Appliquer les modifications minimales necessaires.
3. Verifier le serveur (`python -m py_compile server.py`).
4. Verifier le rendu `control.html` et `overlay.html`.
5. Commit avec prefixe (`feat:`, `fix:`, `refactor:`, `chore:`).
6. Ouvrir une Pull Request.

## Regles de revue
- Priorite aux regressions fonctionnelles et aux risques live.
- Refuser les changements sans validation d'entree sur l'API.
- Refuser les commentaires non conformes (francais, impersonnels, utiles).
- Refuser les changements visuels sans verification sur `overlay.html`.

## Checklist avant merge
- Serveur compilable.
- Aucun crash si `deaths.txt` est absent.
- Polling stable et aucune surcharge API evidente.
- Config persistante apres redemarrage.
