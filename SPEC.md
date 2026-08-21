# MVP — Veille scientifique Bellegarde sur DS218

## Problem Statement

Bellegarde reçoit des newsletters d’éditeurs scientifiques contenant plusieurs centaines de références par semaine. Leur dépouillement manuel est répétitif, les mêmes publications peuvent être signalées plusieurs fois et le futur service doit fonctionner de façon autonome sur un Synology DS218 aux ressources limitées.

## Solution

Le premier incrément est un programme Python sans dépendance externe qui traite des messages `.eml`, identifie les DOI, conserve un historique SQLite, déduplique les publications et génère un digest HTML des références découvertes pendant l’exécution.

Cet incrément valide le cœur idempotent du système avant d’ajouter l’accès IMAP, l’enrichissement Crossref, le classement par IA et l’envoi SMTP.

## User Stories

1. En tant que consultant Bellegarde, je veux déposer des newsletters au format `.eml`, afin de tester le traitement sans connecter immédiatement une boîte réelle.
2. En tant que consultant Bellegarde, je veux que les DOI soient extraits du texte et des liens HTML, afin d’identifier les publications indépendamment de la mise en page de la newsletter.
3. En tant que consultant Bellegarde, je veux que les DOI soient normalisés, afin que leurs variantes d’écriture représentent la même publication.
4. En tant que consultant Bellegarde, je veux que deux newsletters signalant le même DOI ne créent qu’une publication, afin d’éviter les doublons.
5. En tant qu’exploitant du NAS, je veux pouvoir relancer le programme sans recréer les messages ou publications, afin qu’une reprise après incident soit sûre.
6. En tant que consultant Bellegarde, je veux recevoir un digest lisible dans un navigateur ou un client mail, afin de contrôler les références détectées.
7. En tant qu’exploitant du NAS, je veux connaître le nombre de messages traités, ignorés et de publications nouvelles, afin de vérifier le succès d’une exécution.
8. En tant qu’exploitant du NAS, je veux un programme compatible Python 3.8 et sans service permanent, afin de l’exécuter sur le DS218 avec le Planificateur de tâches DSM.

## Implementation Decisions

- Python 3.8+ et bibliothèque standard uniquement.
- Une commande `run` traite tous les fichiers `.eml` d’un dossier, sans les modifier.
- SQLite constitue la source persistante pour les messages, publications et relations entre eux.
- Le `Message-ID` est l’identité préférée d’un courriel ; son empreinte SHA-256 sert de repli.
- Le DOI normalisé en minuscules constitue l’identité canonique d’une publication.
- L’extraction accepte les DOI visibles et ceux contenus dans les attributs `href` du HTML.
- Le digest d’une exécution contient uniquement les publications jamais vues auparavant.
- Une publication reste en attente tant qu’un digest complet n’a pas été écrit ; une relance reprend ces publications après une interruption.
- Le digest est remplacé atomiquement afin de ne jamais exposer un fichier partiellement écrit.
- L’interface testée au niveau le plus élevé est l’exécution du pipeline sur un dossier de messages et l’observation de son rapport, de sa base et de son HTML.

## Testing Decisions

- Les tests portent sur les comportements externes : extraction, déduplication entre messages, idempotence entre exécutions et contenu du digest.
- Les messages de test sont construits avec la bibliothèque standard et écrits dans un dossier temporaire.
- Aucun réseau, secret ou service externe n’est requis par la suite de tests.

## Out of Scope

- Connexion IMAP ou OAuth.
- Récupération des métadonnées Crossref ou des abstracts.
- Filtrage thématique et résumé par IA.
- Téléchargement ou lecture de PDF.
- Envoi du digest par SMTP.
- Interface web d’administration.

## Further Notes

- Les titres déduits depuis une newsletter restent indicatifs ; Crossref deviendra la source canonique lors de l’incrément suivant.
- Un article sans DOI n’est pas encore conservé.
- Le traitement doit rester compatible avec une exécution quotidienne planifiée et interrompue entre deux runs.
