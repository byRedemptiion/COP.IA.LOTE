<p align="center">
  <img src="docs/assets/logo.png" alt="Logo COP'IA'LOTE" width="220">
</p>

<h1 align="center">COP'IA'LOTE</h1>

<p align="center">
  <b>Ton copilote IA de jeu vidéo, sous Windows.</b><br>
  Il regarde ton écran, t'écoute, te répond à voix haute… et ne joue jamais à ta place.
</p>

<p align="center">
  <a href="https://github.com/byRedemptiion/COP.IA.LOTE/releases/download/installer-latest/COPIALOTE-Setup.exe"><b>⬇ Télécharger COPIALOTE-Setup.exe</b></a>
</p>

---

## Deux entités, une application

**COP'IA'LOTE** est l'application. Elle est incarnée par une entité, au choix dans Réglages → Profil :

| | Entité | Caractère |
| --- | --- | --- |
| 🤖 | **VIIRUS** | petit robot espiègle, voix de robot |
| 💠 | **ALICIA** | sa coéquipière, voix féminine |

![Interface de COP'IA'LOTE](docs/assets/interface.png)

## Ce qu'il sait faire

- 🎙 **Tu lui parles** : « VIIRUS, quel objet je prends ? ». Il voit ton écran au moment où tu parles et répond en quelques secondes, à voix haute.
- 💡 **Mode Copilote** : il surveille ta partie et n'intervient que quand ça compte (danger, erreur, opportunité, moment marquant).
- 📺 **Mode Stream** : il lit le chat Twitch et/ou TikTok et répond aux spectateurs à voix haute, avec un overlay OBS animé et sa propre piste audio.
- 🤝 **Duo** : VIIRUS et ALICIA, sur deux PC, se parlent et se transmettent vos questions.
- 📖 **Guides** : il trouve le bon guide, l'ouvre ou t'affiche la carte utile.
- 🔊 **Voix** : Edge (gratuit), Gemini, ChatGPT, voix sur mesure ou voix robot locales, avec effets.
- 🖥 **Actions sur le PC** : volume, lancer une appli, rappels… Jamais rien dans le jeu.
- 📒 **Carnet de partie** : « retiens que je joue Ashe en support » — il s'en souvient, jeu par jeu.
- 📝 **Débrief** : « fais-moi le débrief » — bilan de ta partie et conseils pour la suivante.
- 🎬 **Clips** : « clip ça ! » — il garde les dernières secondes dans OBS ou Streamlabs.
- 💾 **Sauvegarde** : tout en un fichier (sans tes clés), plus une sauvegarde automatique chaque jour.

## Installer

1. Télécharge **[COPIALOTE-Setup.exe](https://github.com/byRedemptiion/COP.IA.LOTE/releases/download/installer-latest/COPIALOTE-Setup.exe)** et double-clique dessus.
2. Choisis ton IA : **Gemini** (recommandé), **ChatGPT** (API OpenAI, payante à l'usage) ou **Ollama** (locale). Pour Gemini, un bouton ouvre la page Google pour créer ta clé.
3. L'installateur télécharge le reste (environ 2 Go la première fois) et crée l'icône sur le Bureau.

> Windows affiche « Windows a protégé votre ordinateur » ? Clique sur **Informations complémentaires → Exécuter quand même** (l'installateur n'est pas signé).

Aucun droit administrateur n'est nécessaire. Les mises à jour se font avec le bouton **⟳ MAJ**, sans rien réinstaller ; tes clés et tes réglages sont toujours gardés.

## Utilisation

| Pour… | Fais… |
| --- | --- |
| Lui parler | Dis **« VIIRUS… »** (ou « Alicia… ») en début de phrase, ou maintiens **F10** |
| Analyser l'écran tout de suite | **F9** |
| Le faire taire | « VIIRUS, stop » |
| Le Copilote | bouton **💡 Copilote**, ou « active le copilote » |
| Le Mode Stream | bouton **📺 Stream**, ou « active le mode stream » |
| Seulement le rond à l'écran | bouton **◉ Mode bulle** (double-clic sur le rond pour revenir) |
| Ouvrir / fermer un guide | « ouvre le guide », « montre-moi la carte », « ferme l'image » |

Le rond indique ce qu'il fait : **EN VEILLE**, **OBSERVE** (le Copilote regarde), **À L'ÉCOUTE**, **RÉFLÉCHIT**, **PARLE**.

<details>
<summary><b>💡 Mode Copilote</b></summary>

Il jette un coup d'œil à ta partie à intervalle régulier (8 s à 2 min) et ne parle que si ça vaut le coup. Dans Réglages → Copilote : la spontanéité (discret, normal, bavard), les types d'interventions (conseils, alertes, réactions, humour, trash-talk bienveillant, remarques pour le duo) et le délai de silence. Une vraie urgence passe toujours. Il se tait quand tu parles et ne dépense aucun appel à l'IA hors jeu (bureau, Discord, navigateur, OBS…).
</details>

<details>
<summary><b>📺 Mode Stream et OBS</b></summary>

- Indique ta chaîne Twitch et/ou ton @ TikTok dans Réglages → Stream. Il lit le chat en lecture seule, sans compte, et n'y écrit jamais.
- TikTok n'a pas d'API officielle pour les lives : la lecture passe par la bibliothèque non officielle [TikTokLive](https://github.com/isaackogan/TikTokLive) (licence AGPL modifiée, qui autorise ce genre d'outil). Si TikTok change quelque chose, elle peut s'arrêter le temps d'une mise à jour.
- Il répond quand on le nomme (« @VIIRUS », « !viirus »), aux questions, ou à tout de temps en temps ; une réponse toutes les 20 s au plus (réglable).
- Les messages du chat ne déclenchent jamais d'action sur ton PC. Bots, liens, insultes et tentatives de lui faire dire quelque chose sont ignorés.
- **Overlay OBS** : ajoute l'adresse indiquée dans Réglages → Stream comme source « Navigateur ». Le robot y flotte, s'anime et ses réponses s'affichent en sous-titres.
- **🔊 Sa voix dans OBS** : coche l'option, puis « Contrôler l'audio via OBS » dans la source : il a sa propre piste dans le mélangeur.
</details>

<details>
<summary><b>🔊 Voix</b></summary>

Réglages → Profil → **Catalogue des voix** (▶ Écouter, puis Choisir).

| Moteur | Coût | Note |
| --- | --- | --- |
| Edge (Microsoft) | gratuit | 13 voix françaises, sans quota |
| Gemini (Google) | ta clé Gemini | 30 voix expressives |
| ChatGPT (OpenAI) | ta clé OpenAI | 13 voix très naturelles |
| ✨ Voix sur mesure (Gemini 3.8) | ta clé Gemini | tu décris la voix, Google la crée |
| VIIRUS / ALICIA | gratuit | voix robot locales, hors ligne |

- **Effets** : Masculin, Féminin, Jeune, Robot, Petite robote, Petit robot (VIIRUS), Gros robot, avec des réglages fins.
- **Clé voix** (Réglages → IA → Avancé) : une clé à part, par exemple pour réfléchir avec ChatGPT et parler avec Gemini.
- Si une voix en ligne ne répond pas (quota, coupure), sa voix locale prend le relais et un message te le dit. Les voix Gemini sont limitées par Google (au niveau 1 : 10 demandes par minute, 100 par jour).
</details>

<details>
<summary><b>🤝 Duo</b></summary>

Deux joueurs, deux PC, deux entités qui se parlent : Réglages → Social → Duo, avec le même code des deux côtés. Le panneau DUO montre si l'autre est là. « VIIRUS, demande à Alicia ce qu'elle pense de mon build » : la question part, la réponse revient à voix haute. Les messages sont chiffrés et ne déclenchent jamais d'action sur le PC.
</details>

<details>
<summary><b>🎮 Jeux et sites de référence</b></summary>

Onglet **Jeux** : un profil par jeu, reconnu tout seul à sa fenêtre ou à son .exe, avec tes sites de référence à consulter en premier quand il cherche sur le web. Profils fournis (Overwatch, World of Warcraft…) modifiables ; « ＋ Ajouter un jeu » pour les autres.
</details>

<details>
<summary><b>🖥 Actions sur le PC</b></summary>

| Exemple | Action | Sécurité |
| --- | --- | --- |
| « Monte le son », « volume à 30 » | Volume | immédiat |
| « Lance Discord », « ouvre YouTube » | Applis de la liste | immédiat |
| « Rappelle-moi dans 20 minutes de manger » | Rappel à voix haute | immédiat |
| « Verrouille le PC », « ferme Discord » | Session, fermeture | confirmation |
| « Éteins le PC », « redémarre le PC » | Extinction | confirmation + 20 s, « annule » l'arrête |

Seules ces actions existent : il ne peut jamais lancer une commande libre, ni agir dans le jeu.
</details>

<details>
<summary><b>👁 Vision et mémoire de partie</b></summary>

- **Ce qu'il regarde** : le jeu au premier plan, la zone autour de ta souris (« c'est quoi ça ? ») ou l'écran entier.
- **Mémoire de partie** : une petite image datée toutes les 30 s, sur ton PC, pour « il y a une heure, c'était quoi mon objet ? ». Durée et place réglables, nettoyage automatique.
- Pour voir le rond par-dessus le jeu, mets le jeu en **plein écran fenêtré**.
</details>

## IA

| IA | Coût | Point fort |
| --- | --- | --- |
| **Gemini** (recommandé) | offre gratuite, puis à l'usage | rapide, ne prend pas le GPU du jeu |
| **ChatGPT** (API OpenAI) | à l'usage (crédit prépayé) | très bonnes réponses |
| **Ollama** | gratuit | hors ligne (mais partage le GPU avec le jeu) |

Deux cerveaux : un rapide pour les réponses courantes, un réfléchi pour les questions complexes. Les clés se gèrent dans Réglages → IA → Avancé → **Gérer mes clés**.

## Confidentialité

- **Aucune action dans le jeu**, aucune lecture de sa mémoire : seulement des images de l'écran, via les API publiques de Windows (comme OBS ou Discord).
- Ton écran et ta voix ne partent à l'IA que lorsque tu lui parles, ou si tu actives le Copilote.
- Le micro attend son nom sur ton PC : rien n'est envoyé avant.
- Tes clés restent sur ton PC (`%APPDATA%\Alicia\.env`) et n'apparaissent jamais dans les journaux.

## Problèmes fréquents

| Problème | Solution |
| --- | --- |
| « Clé refusée » | Réglages → IA → Avancé → Gérer mes clés, puis « Tester » |
| « Quota atteint » | Attendre (une minute, ou le lendemain pour un quota par jour) |
| Il ne m'entend pas | Réglages → Perception → micro et « Tester le micro » |
| Capture noire | Mettre le jeu en plein écran fenêtré |
| La mise à jour échoue | Fermer COP'IA'LOTE, puis lancer `Lancer_COPIALOTE.bat` dans `%LOCALAPPDATA%\Programs\ALICIA` |

Le journal se trouve dans `%LOCALAPPDATA%\Alicia\logs\alicia.log` (bouton **Journal** en bas du panneau).

## Développer

```powershell
uv sync --python 3.12 --frozen --extra dev
uv run --frozen ruff check src tests
uv run --frozen pytest -q
uv run --frozen alicia --smoke-test
```

Branche stable : `alice-v0.3` (suivie par le bouton MAJ). Le code garde le nom technique `alicia` (paquet Python, dossiers de données) pour que les installations existantes continuent de fonctionner.

[Architecture](docs/architecture.md) · [Cahier des charges](docs/cahier-des-charges.md) · [Règles du projet](AGENTS.md)

<p align="center"><sub>COP'IA'LOTE · par byRedemptiion</sub></p>
