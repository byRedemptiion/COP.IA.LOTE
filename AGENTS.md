# Développer Alicia

Alicia est un copilote IA pour jeux vidéo sous Windows. Elle observe une fenêtre et conseille le joueur, sans jamais jouer à sa place. Le cahier des charges de référence est `docs/cahier-des-charges.md` ; l'architecture est décrite dans `docs/architecture.md`.

## Règles non négociables

- Aucune entrée envoyée au jeu (clic, touche), aucune injection, aucune lecture mémoire : uniquement des pixels, via les API publiques de Windows.
- Aucune clé API dans le code, dans Git ou dans les logs. Les secrets viennent de l'environnement ou du `.env` (exclu de Git) et sont encapsulés dans `Secret`.
- Le cœur (`src/alicia/core`) n'importe ni Qt ni SDK de fournisseur ; les fournisseurs d'IA passent par `httpx` derrière `VisionModel`.
- Pas de travail bloquant sur le thread Qt. Les résultats périmés (après Arrêter ou Annuler) sont ignorés.
- Pas de repli silencieux : chaque repli de capture ou nouvel essai d'IA est journalisé et visible.
- Aucune analyse IA permanente des images : les appels sont déclenchés par le joueur (V0.1), puis par la détection d'événements avec seuil et délai entre interventions (V0.6).

## Vérifier avant de livrer

```text
uv sync --python 3.12 --frozen --extra dev
uv run --frozen ruff check src tests
uv run --frozen pytest -q
uv run --frozen alicia --smoke-test
```

Les tests utilisent des doubles (capture démo, `FakeModel`, `httpx.MockTransport`). Ils ne valident ni une vraie capture Windows ni un vrai appel d'API : ces points se vérifient sur le PC cible, avec `alicia-diag` et le log.
