# Architecture d'Alicia (V0.1)

## Flux d'une analyse

```
UI (PySide6) ──question──▶ AnalysisService ──capture()──▶ CaptureService ──▶ backends (WGC fenêtre → WGC écran → PrintWindow)
                                 │                                                     ▲ pixels seulement
                                 ├──▶ SessionContext (historique court) + GameProfile (games/)
                                 └──▶ VisionModel ──HTTPS (streaming)──▶ Gemini | Ollama | Fake
```

1. L'UI envoie `(fenêtre, question)` à `AnalysisService` dans un thread de travail (`QThreadPool`) : l'interface ne fige jamais.
2. `CaptureService` rafraîchit la géométrie de la fenêtre, puis essaie les backends dans l'ordre. Une image noire ou une erreur déclenche le backend suivant ; chaque repli est journalisé et affiché sous l'aperçu.
3. `image_prep` réduit l'image (1568 px maximum sur le grand côté) et l'encode en JPEG.
4. Le profil de jeu (`games/profiles.py`) ajoute son contexte au prompt système ; `SessionContext` fournit les 3 derniers échanges.
5. `VisionModel.analyze()` diffuse la réponse morceau par morceau (`on_delta`). L'UI les affiche à mesure.
6. Chaque étape est journalisée avec le même identifiant d'opération (`[a3f9c2]`), la durée, le backend et les jetons.

## Règles de conception

- Le cœur (`alicia/core`) n'importe ni Qt ni SDK de fournisseur. Win32 reste confiné à `capture/win32.py` et `capture/backends.py`.
- Les fournisseurs d'IA passent par l'API REST avec `httpx`, sans SDK. Ajouter un fournisseur revient à écrire une sous-classe de `HttpVisionModel` (`_request`, `_parse_lines`, `_http_error`) et une ligne dans `factory.py`.
- Les erreurs prévues sont des `AliciaError` qui portent un message lisible pour l'UI (`user_message`) et un détail pour les logs (`detail`). Les erreurs de fournisseur sont normalisées : `auth`, `rate_limit`, `timeout`, `unavailable`, `bad_request`, `cancelled`.
- Aucun repli silencieux : un seul nouvel essai automatique, uniquement sur `timeout`/`unavailable` et avant le premier mot. Il est journalisé.
- Les secrets ne viennent que de l'environnement ou du `.env`, et sont encapsulés dans `Secret`, qui ne s'affiche jamais.
- Les résultats périmés sont ignorés : chaque tâche porte un numéro de génération, et Arrêter/Annuler l'invalide.

## Capture

| Backend | Usage | Limites |
| --- | --- | --- |
| `wgc-window` | Défaut : Windows Graphics Capture sur le `HWND`, accéléré GPU, bordure jaune et curseur désactivés | Fenêtre réduite impossible |
| `wgc-monitor` | Jeu en plein écran dont la capture de fenêtre sort noire : capture de l'écran du jeu | Capture tout ce qui est affiché sur cet écran |
| `printwindow` | Applications classiques, dernier recours | Souvent noir pour les jeux 3D |

En V0.1, la capture est faite à la demande : environ 50 à 150 ms pour démarrer une session WGC. La V0.2 gardera une session ouverte pour la capture continue et la détection de changements.

## Arborescence

```
src/alicia/
  __main__.py          point d'entrée (alicia), --demo, --debug, --smoke-test
  app.py               composition des services
  diag.py              alicia-diag : list-windows, capture, ask, models
  default.toml         réglages par défaut
  core/
    config.py          Settings (TOML + .env + environnement)
    errors.py          erreurs normalisées
    logging_setup.py   logs fichier/console/UI, identifiant d'opération, hooks d'exception
    capture/           models, win32, backends, service
    ai/                base (contrat), image_prep, prompts, factory, providers/
    session/           contexte de session
    analysis/          AnalysisService
  games/profiles.py    profils de jeu (générique, Overwatch)
  ui/                  main_window, workers
```

## Feuille de route

| Version | Objectif |
| --- | --- |
| V0.1 | Capture de fenêtre et question texte, analyse multimodale en streaming, logs ✅ validée sur Overwatch |
| V0.2 | Session de capture permanente, détection locale des changements, zones d'intérêt |
| V0.3 | Questions orales : F10 maintenu, audio + capture envoyés ensemble à Gemini (pas de transcription locale), recherche web Google |
| V0.4 | Réponses vocales phrase par phrase, coupées par F10 ou un bouton (livrées avec la V0.3) |
| V0.5 | Mémoire de session structurée (héros, objets, objectifs) |
| V0.6 | Score d'importance, interventions spontanées, modes Silent/Copilot/Coach/Analyst |
| V0.7 | Recherche externe et connaissances par jeu |
| V0.8 | Overlay en jeu |
| V1.0 | Packaging `.exe` (PyInstaller), configuration dans l'interface |

## Voix (V0.3) et projets dont elle s'inspire

| Brique | Choix | Inspiration (licence MIT) |
| --- | --- | --- |
| Micro | `sounddevice`, ouvert seulement pendant que F10 est maintenu ; refus clair si trop court ou muet | [huburton/jarvis](https://github.com/huburton/jarvis) (raccourci plutôt que micro ouvert) |
| Compréhension | L'audio part **avec la capture** à Gemini, qui transcrit et répond en un seul appel : pas de Whisper local, pas de PyTorch, pas de GPU pris au jeu | [dnhkng/GLaDOS](https://github.com/dnhkng/GLaDOS) (« direct audio » vers le modèle) |
| Voix | `edge-tts` (voix neuronales Microsoft) décodé par `miniaudio`, lu par `sounddevice` ; la phrase suivante est synthétisée pendant la lecture de la précédente ; arrêt en moins de 50 ms | [KoljaB/RealtimeTTS](https://github.com/KoljaB/RealtimeTTS) (EdgeEngine, découpage en phrases), [huburton/jarvis](https://github.com/huburton/jarvis) (lecture interruptible) |

RealtimeTTS n'est pas utilisé directement : sa voix Edge passe par le lecteur externe `mpv` sous Windows. RealtimeSTT impose PyTorch (plusieurs Go) pour la détection de voix, inutile en push-to-talk.

### Mise à jour : audio séparé du cerveau

Depuis la demande d'une voix personnalisable, l'audio ne dépend plus du fournisseur d'IA :
- **Compréhension** : faster-whisper en local (`large-v3-turbo`, int8, processeur), réglages et filtre d'hallucinations repris de huburton/jarvis. La question part ensuite **en texte** avec la capture, vers n'importe quel cerveau. L'ancien mode « audio direct à Gemini » reste disponible (`[voice] stt = "gemini"`).
- **Voix** : Edge (en ligne) ou Kokoro-82M (`kokoro-onnx`, modèle Apache 2.0, voix `ff_siwis`), calculée en local sur le processeur. Une voix ElevenLabs pourra s'ajouter derrière la même interface `Synthesizer`.
