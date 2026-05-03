# Conventions de Code

## Objectif
Uniformiser le style du projet pour réduire les regressions et accelerer les revues.

## Nommage
- JavaScript: `camelCase` pour fonctions et variables.
- Python: `snake_case` pour fonctions et variables.
- Constantes: `UPPER_SNAKE_CASE`.
- Fichiers: `kebab-case` pour HTML/JS/CSS, `snake_case` pour Python si necessaire.

## Structure
- Une fonction = une responsabilite principale.
- Eviter les fonctions trop longues: extraction de helpers des qu'une logique devient repetitive.
- Eviter les nombres magiques: definir des constantes nommees.
- Traiter les erreurs explicitement et retourner des messages exploitables.

## API et validation
- Sequence obligatoire: `parse -> validate -> apply -> persist -> respond`.
- Aucune ecriture disque sans validation prealable.
- Valeurs numeriques bornees (min/max) avant application.
- Champs texte limites en longueur et nettoyes (`trim`).

## Commentaires (francais, impersonnel)
- Utiliser les commentaires uniquement si la logique n'est pas triviale.
- Expliquer la decision ou le risque, pas la syntaxe.
- Style court, sans ton conversationnel.
- Forme recommandee:
  - `Regle: ...`
  - `Risque: ...`
  - `Decision: ...`

Exemple:
```js
// Regle: Priorite au ETag; If-Modified-Since sert de repli.
```

## Commits
- Prefixes recommandes:
  - `feat:`
  - `fix:`
  - `refactor:`
  - `chore:`
- Message court, factuel, axe resultat.
