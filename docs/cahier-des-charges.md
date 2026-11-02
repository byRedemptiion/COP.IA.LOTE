> Historique : premier cahier des charges, quand le projet s'appelait « Alice ». Le projet
> s'appelle aujourd'hui **COP'IA'LOTE**, avec les profils **ALICIA** et **VERIS**.

**ALICE**

**Cahier des charges pour Claude**

Copilote IA temps réel pour jeux vidéo — Windows

*Objectif : construire progressivement une application capable
d'observer une partie, comprendre ce qui se passe, discuter avec le
joueur et lui donner des conseils pertinents, sans jamais jouer à sa
place.*

# 1. Mission

Je veux que tu développes le projet Alice comme un véritable produit
logiciel. Tu dois prendre en charge l'architecture, l'implémentation,
les tests, le diagnostic et les évolutions, tout en avançant par
versions courtes et testables.

Alice est une IA copilote pour jeux vidéo. Elle doit donner l'impression
qu'une personne compétente est assise à côté du joueur : elle regarde
l'écran, comprend le contexte, répond aux questions, compare des choix
et peut, plus tard, intervenir spontanément lorsqu'elle détecte quelque
chose d'important.

Principe non négociable : Alice observe et conseille. Elle ne contrôle
pas le jeu, ne clique pas, n'envoie pas de touches et ne joue jamais à
la place du joueur.

# 2. Expérience utilisateur visée

- Le joueur lance Alice puis sélectionne la fenêtre du jeu à observer.

- Alice capture uniquement la fenêtre sélectionnée, sans exiger une
  capture vidéo permanente envoyée au cloud.

- Le joueur peut demander oralement ou par texte : « Lequel de ces
  objets est meilleur pour mon personnage ? ».

- Alice analyse l'écran actuel, le contexte connu du personnage et les
  informations déjà observées avant de répondre.

- Si nécessaire, Alice pourra plus tard rechercher des informations
  externes à jour sur le jeu.

- Alice doit conserver un contexte de session afin d'éviter de repartir
  de zéro à chaque question.

- En mode copilote, Alice pourra signaler spontanément un objet, un
  danger, une erreur ou une opportunité importante.

- Elle doit savoir rester silencieuse : pas de commentaire permanent ni
  d'interruptions inutiles.

# 3. Architecture fonctionnelle

Flux principal souhaité :

JEU → CAPTURE ÉCRAN → DÉTECTION LOCALE DES CHANGEMENTS → IA MULTIMODALE
→ CONTEXTE / MÉMOIRE → RAISONNEMENT → DÉCISION DE PARLER → RÉPONSE

Flux conversationnel :

MICROPHONE → COMPRÉHENSION VOCALE → QUESTION DU JOUEUR → ÉCRAN ACTUEL +
CONTEXTE → IA → RÉPONSE VOCALE

L'architecture doit être modulaire. Les composants de capture, IA,
audio, mémoire, recherche externe, interface et logique de décision
doivent être séparés afin de pouvoir être remplacés ou améliorés
indépendamment.

# 4. Plateforme et contraintes

- Cible principale : Windows.

- Priorité à la stabilité et à une faible latence.

- Consommation CPU/GPU raisonnable lorsque le jeu tourne.

- Limiter les appels API et les captures inutiles.

- Aucune clé API codée en dur dans le dépôt.

- Utiliser des variables d'environnement ou un fichier .env exclu de
  Git.

- Prévoir dès le départ des logs horodatés exploitables.

- Le projet devra pouvoir être packagé ultérieurement en .exe propre et
  partageable.

- Éviter les dépendances inutiles et documenter clairement les
  prérequis.

# 5. Capture et compréhension de l'écran

Alice doit pouvoir lister les fenêtres ouvertes, permettre à
l'utilisateur d'en sélectionner une, puis capturer correctement son
contenu. La capture doit rester isolée derrière un service dédié.

Ne pas concevoir le système comme un envoi permanent de 60
images/seconde vers une IA. La capture locale peut être fréquente, mais
une couche locale doit déterminer si l'image mérite une analyse
distante.

- Comparer des captures successives.

- Détecter un changement suffisamment important.

- Pouvoir définir des zones d'intérêt à terme : inventaire, HUD,
  statistiques, minimap, etc.

- Conserver les dernières captures pertinentes.

- N'envoyer à l'IA que ce qui est utile.

- Permettre une analyse manuelle immédiate même si aucun changement
  automatique n'a été détecté.

# 6. Intelligence d'Alice

Le cerveau d'Alice doit être accessible via une couche d'abstraction. Je
ne veux pas que toute l'application dépende directement d'un fournisseur
ou d'un modèle précis. Il doit être possible de changer de modèle plus
tard.

- Analyse multimodale : texte + image au minimum.

- Compréhension d'une question en utilisant l'écran actuel.

- Utilisation de l'historique court de conversation.

- Utilisation du contexte du personnage et de la session.

- Possibilité future d'utiliser plusieurs captures pour comprendre une
  évolution.

- Possibilité future d'utiliser une recherche web ou une base de
  connaissances spécifique au jeu.

- Ne jamais inventer une statistique illisible : signaler explicitement
  une incertitude.

- La réponse doit privilégier l'information utile au joueur plutôt
  qu'une longue description de l'écran.

# 7. Mémoire et contexte

## 7.1 Contexte immédiat

- Dernières captures importantes.

- Dernière question et dernière réponse.

- Événements détectés récemment.

- État actuel connu de l'interface ou du combat.

## 7.2 Mémoire de session

- Personnage ou classe si connus.

- Build ou style de jeu connu.

- Équipement et objets observés.

- Statistiques importantes.

- Choix et recommandations précédentes.

- Objectifs indiqués par le joueur.

- Informations explicitement fournies par le joueur.

La mémoire persistante entre plusieurs sessions n'est pas prioritaire
pour la V0.1, mais l'architecture ne doit pas empêcher son ajout
ultérieur.

# 8. Audio et conversation

- Ajouter ultérieurement la sélection du microphone.

- Détecter ou transmettre la parole du joueur avec une latence faible.

- Permettre au joueur d'interrompre Alice si elle parle.

- Prévoir la sélection du périphérique de sortie.

- Réponse vocale naturelle et rapide.

- Conserver une transcription texte dans l'interface pour faciliter le
  diagnostic.

- Prévoir un push-to-talk et/ou un mode d'écoute selon les tests.

# 9. Intervention spontanée

Alice devra à terme décider elle-même si un événement mérite une
intervention. Je veux éviter une IA qui commente chaque mouvement.

Prévoir un mécanisme de score conceptuel, par exemple importance_score,
basé sur :

- nouveauté de l'événement ;

- danger potentiel ;

- impact sur le personnage ou la partie ;

- pertinence par rapport à l'objectif actuel ;

- confiance de l'analyse ;

- temps écoulé depuis la dernière intervention.

Ajouter un seuil d'intervention et un cooldown. Une intervention
spontanée doit pouvoir être désactivée complètement.

# 10. Modes prévus

| Mode    | Comportement                                                                     |
|---------|----------------------------------------------------------------------------------|
| Silent  | Alice observe mais ne répond que lorsqu'on lui pose une question.                |
| Copilot | Alice répond et intervient uniquement lorsqu'un événement important est détecté. |
| Coach   | Alice est plus proactive et signale davantage les erreurs et optimisations.      |
| Analyst | Alice collecte la session et produit ensuite une analyse structurée.             |

# 11. Support de plusieurs jeux

Le premier prototype pourra être testé sur Warcraft III ou un autre jeu
pratique pour afficher des objets, statistiques et interfaces.
Cependant, le cœur d'Alice ne doit jamais être codé uniquement pour un
jeu.

Organisation conceptuelle souhaitée :

core/ : fonctions génériques d'Alice

games/ : profils ou modules spécifiques à certains jeux

Un module de jeu pourra plus tard fournir des zones d'écran connues, des
règles spécifiques, des connaissances ou des prompts spécialisés sans
modifier le moteur principal.

# 12. Interface utilisateur

La première interface doit être sobre et fonctionnelle. Elle doit au
minimum proposer :

- liste des fenêtres détectées ;

- sélection de la fenêtre à observer ;

- bouton Start / Stop ;

- état d'Alice ;

- aperçu de la dernière capture ;

- champ de question texte ;

- bouton Analyze ;

- zone affichant la réponse ;

- zone ou écran de logs.

Plus tard : overlay en jeu, niveau d'intervention, profils de jeux,
microphone, sortie audio, choix des modèles, personnalité, fréquence de
capture et paramètres avancés.

# 13. Logs et diagnostic

Le diagnostic est une priorité dès la première version. Les logs doivent
inclure au minimum :

- démarrage et arrêt de l'application ;

- fenêtre sélectionnée ;

- succès/échec de capture ;

- changement d'écran détecté ;

- décision d'envoyer ou non une capture ;

- début/fin d'un appel IA ;

- durée de l'appel ;

- erreur API et message exploitable ;

- entrée microphone et transcription lorsque l'audio sera ajouté ;

- réponse générée ;

- lecture audio ;

- exceptions non gérées.

Prévoir un niveau normal et un niveau debug détaillé.

# 14. V0.1 — priorité absolue

Ne construis PAS Alice complète immédiatement. La première livraison
doit être petite, fiable et testable.

1.  Lancer Alice sous Windows.

2.  Lister les fenêtres actuellement ouvertes.

3.  Sélectionner la fenêtre d'un jeu.

4.  Capturer correctement cette fenêtre.

5.  Afficher un aperçu de la dernière capture.

6.  Permettre une capture/analyse manuelle.

7.  Saisir une question texte.

8.  Envoyer la question et la capture à une IA multimodale.

9.  Recevoir et afficher la réponse.

10. Journaliser les opérations importantes et les erreurs.

11. Fournir une procédure d'installation et de lancement claire.

Cas de test cible : le joueur ouvre un inventaire ou une interface,
clique sur Analyze et demande « Quel objet semble le plus intéressant
sur cet écran ? ». Alice doit utiliser réellement la capture pour
répondre.

# 15. Roadmap indicative

| Version | Objectif                                                                    |
|---------|-----------------------------------------------------------------------------|
| V0.1    | Capture de fenêtre + question texte + analyse multimodale + réponse + logs. |
| V0.2    | Capture automatique + détection locale des changements.                     |
| V0.3    | Microphone + questions vocales.                                             |
| V0.4    | Réponses vocales et gestion propre de l'audio.                              |
| V0.5    | Contexte structuré et mémoire de session.                                   |
| V0.6    | Détection d'événements + interventions spontanées contrôlées.               |
| V0.7    | Recherche externe / connaissances spécifiques aux jeux.                     |
| V0.8    | Overlay et expérience en jeu.                                               |
| V1.0    | Optimisation, interface finalisée, configuration et packaging Windows.      |

# 16. Méthode de travail demandée à Claude

Avant toute implémentation importante, tu dois :

12. Analyser le besoin et les contraintes.

13. Proposer l'architecture technique.

14. Justifier les technologies et bibliothèques retenues.

15. Présenter l'arborescence du projet.

16. Identifier les risques techniques et les points à tester rapidement.

17. Définir précisément les critères de réussite de la version en cours.

18. Puis seulement implémenter.

Pendant le développement :

- Travaille directement sur le projet de manière structurée.

- Évite les fichiers monolithiques et sépare les responsabilités.

- Ne réécris pas inutilement des composants déjà fonctionnels.

- Après une modification, vérifie les régressions probables.

- Ajoute des tests unitaires lorsque cela apporte une vraie valeur.

- Lance les tests et vérifications disponibles avant de considérer une
  tâche terminée.

- Si une décision technique est incertaine, privilégie un prototype
  mesurable plutôt qu'une hypothèse.

- Si un bug dépend de ma machine ou du jeu, ajoute les logs nécessaires
  et indique exactement ce que je dois tester.

- Ne masque pas une erreur par un fallback silencieux.

- Documente les commandes nécessaires pour installer, lancer, tester et
  packager le projet.

# 17. Ce que je ne veux pas

- Un bot qui joue automatiquement.

- Des clics, touches ou actions envoyés au jeu.

- Une architecture liée définitivement à un seul fournisseur d'IA.

- Des clés API dans le code ou dans Git.

- Une analyse cloud permanente de toutes les frames.

- Une IA qui parle constamment.

- Des réponses inventées lorsque l'écran n'est pas lisible.

- Une énorme V1 développée avant d'avoir validé la capture et l'analyse
  de base.

- Des modifications massives sans tests ni logs permettant de comprendre
  les régressions.

# 18. Critères de qualité

- Code lisible, modulaire et maintenable.

- Interfaces claires entre les composants.

- Erreurs utilisateur compréhensibles.

- Logs suffisamment précis pour déboguer à distance.

- Configuration centralisée.

- Faible couplage entre UI, capture, IA, audio et mémoire.

- Comportement sûr lorsque l'API est indisponible ou qu'une capture
  échoue.

- Documentation à jour avec l'état réel du projet.

# 19. Première mission à exécuter

Commence par étudier ce cahier des charges. Ne pars pas immédiatement
dans le développement de toutes les fonctions.

Ta première réponse/travail doit fournir :

19. Une proposition de stack technique pour Windows.

20. Une architecture détaillée de la V0.1.

21. L'arborescence initiale du dépôt.

22. Les bibliothèques nécessaires et leur rôle.

23. La stratégie de capture de fenêtre.

24. La stratégie d'abstraction du fournisseur IA.

25. La stratégie de configuration et de stockage des secrets.

26. La stratégie de logs.

27. Les principaux risques techniques.

28. Un plan d'implémentation par petites étapes testables.

Après validation de cette base, implémente la V0.1. À chaque étape,
privilégie un résultat exécutable et testable sur mon PC plutôt qu'une
accumulation de fonctionnalités non validées.

# 20. Vision finale

**Alice doit devenir « une IA assise virtuellement à côté du joueur,
capable de regarder sa partie, de comprendre ce qu'il fait et de
discuter avec lui de ce qui se passe ».**

Le projet doit rester évolutif : commencer par une V0.1 simple, prouver
que la boucle capture → compréhension → réponse fonctionne correctement,
puis ajouter progressivement temps réel, voix, mémoire, proactivité,
connaissances de jeu et overlay.
