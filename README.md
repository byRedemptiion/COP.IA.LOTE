# COP.IA.LOTE IA pour jeux vidéo (Windows)

VIIRUS ou ALICIA regarde la fenêtre de ton jeu, et quand tu lui poses une question, elle analyse la capture et te répond en quelques secondes. **Elle observe et conseille seulement** : aucun clic, aucune touche, aucune injection dans le jeu, aucune lecture de sa mémoire.

**Version 0.1** : capture d'une fenêtre (même en plein écran), question texte, réponse de l'IA affichée mot par mot, logs détaillés. La voix, la capture automatique et les interventions spontanées arrivent dans les versions suivantes ([feuille de route](docs/architecture.md#feuille-de-route)).

## Installer (une seule fois)

1. Récupérer le projet : `git clone https://github.com/byRedemptiion/ALICIA_COPILOTE` (ou **Code → Download ZIP** sur GitHub, puis décompresser).
2. Créer une **clé Gemini gratuite** : <https://aistudio.google.com> → **Get API key** → **Create API key**. Aucune carte bancaire n'est demandée.
3. Double-cliquer sur **`Installer_Alice.bat`**. Le script :
   - installe uv (gestionnaire Python), Python 3.12 et les dépendances ;
   - te demande la clé et l'enregistre dans `.env` (fichier exclu de Git) ;
   - vérifie la clé et teste l'interface.

## Lancer

Double-cliquer sur **`Lancer_Alice.bat`**.

1. Dans **Fenêtre du jeu**, choisir le jeu (ex. `Overwatch — Overwatch.exe [plein écran]`), puis **Démarrer**.
2. Taper une question, puis **Entrée** ou **Analyser** : Alice capture l'écran et répond. **Capturer** permet de vérifier l'aperçu sans appeler l'IA.
3. Le **Journal** en bas affiche chaque étape : backend de capture, durée, temps avant le premier mot, erreurs.

Pour essayer sans jeu : `Lancer_Alice.bat --demo` (inventaire fictif, clairement signalé).

### Jouer en plein écran : le raccourci F9

En plein écran, un jeu se réduit souvent dès que tu cliques sur une autre fenêtre : Alice ne peut alors plus le capturer. Reste dans le jeu et **appuie sur F9** : Alice capture la fenêtre active et lance l'analyse, avec la question tapée dans Alice ou, à défaut, une question générale. Quand la réponse est prête, Alice clignote dans la barre des tâches. Le raccourci se change dans `alice.toml` (`[hotkeys] analyze = "ctrl+F9"`) ; tant qu'Alice est ouverte, le jeu ne reçoit plus cette touche.

### Overwatch et jeux en plein écran

- Alice utilise la capture Windows Graphics Capture : elle fonctionne en fenêtré, en plein écran fenêtré et, sous Windows 11, en général aussi en plein écran.
- Si la fenêtre sort noire en plein écran, Alice capture **l'écran entier où se trouve le jeu** et l'indique sous l'aperçu (« Repli après : … »).
- Alice n'utilise que des API publiques de Windows, comme OBS ou Discord. Blizzard peut cependant considérer des conseils en direct en partie classée comme une aide extérieure : teste plutôt en **Stadium** (choix d'objets), en entraînement ou en partie personnalisée.

## Fournisseur d'IA

| Fournisseur | Réglage | Coût | Avantage | Limite |
| --- | --- | --- | --- | --- |
| **Gemini** (défaut) | `GEMINI_API_KEY` dans `.env` | offre gratuite (quota par minute et par jour) | rapide, ne prend pas de GPU au jeu | nécessite Internet |
| Ollama (local) | `ALICE_AI_PROVIDER=ollama` + [Ollama](https://ollama.com) + `ollama pull qwen2.5vl:7b` | gratuit | hors ligne | partage le GPU avec le jeu, plus lent |
| Factice | `ALICE_AI_PROVIDER=fake` | — | tests sans réseau | ne regarde pas l'image |

Pour aller plus vite : créer un fichier `alice.toml` à la racine avec, par exemple :

```toml
[ai.gemini]
model = "gemini-flash-lite-latest"   # plus rapide, un peu moins précis
```

`alice-diag models` liste les modèles accessibles avec ta clé. Tous les réglages et leur valeur par défaut sont dans [`src/alice/default.toml`](src/alice/default.toml).

## Diagnostic

Les logs sont dans `%LOCALAPPDATA%\Alice\logs\alice.log` (bouton **Ouvrir le dossier des logs**). Coche **Logs détaillés** ou lance `Lancer_Alice.bat --debug` pour plus de détails. Les clés ne sont jamais écrites dans les logs ; les questions et réponses ne le sont qu'en mode détaillé.

Outils en ligne de commande (dans le dossier du projet) :

```powershell
uv run alice-diag list-windows                      # fenêtres vues par Alice
uv run alice-diag capture overwatch --out ow.png    # capture seule, sans IA
uv run alice-diag capture overwatch --backend printwindow
uv run alice-diag ask ow.png "Quel objet est le meilleur ?"
uv run alice-diag models                            # modèles Gemini disponibles
```

| Problème | Que faire |
| --- | --- |
| « Clé Gemini manquante / refusée » | Vérifier la ligne `GEMINI_API_KEY=` dans `.env`, puis relancer. |
| « Quota Gemini atteint » | Attendre une minute (limite de l'offre gratuite). |
| Capture noire ou refusée | Essayer le mode plein écran fenêtré du jeu ; envoyer `alice-diag capture … --debug` et le log. |
| « Modèle introuvable » | `alice-diag models`, puis indiquer un modèle de la liste dans `alice.toml`. |

## Développer

```powershell
uv sync --python 3.12 --extra dev
uv run pytest -q
uv run ruff check src tests
uv run alice --smoke-test     # parcours complet hors écran, IA factice
```

Architecture et choix techniques : [docs/architecture.md](docs/architecture.md). Cahier des charges : [docs/cahier-des-charges.md](docs/cahier-des-charges.md).
