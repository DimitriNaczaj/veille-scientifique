# MVP — Veille scientifique Bellegarde sur DS218

## Problem Statement

Bellegarde reçoit des newsletters d’éditeurs scientifiques contenant plusieurs centaines de références par semaine. Leur dépouillement manuel est répétitif, les mêmes publications peuvent être signalées plusieurs fois et le futur service doit fonctionner de façon autonome sur un Synology DS218 aux ressources limitées.

## Solution

L’application est un programme Python sans dépendance externe qui traite des messages `.eml`, identifie les DOI ainsi que les titres liés par les éditeurs pris en charge, conserve un historique SQLite, déduplique les publications, enrichit les DOI via Crossref, applique un préfiltrage explicable et génère un digest HTML.

Les deux premiers incréments valident le cœur idempotent, l’enrichissement distant et la réduction de volume avant d’ajouter l’accès IMAP, le classement par IA et l’envoi SMTP.

## User Stories

1. En tant que consultant Bellegarde, je veux déposer des newsletters au format `.eml`, afin de tester le traitement sans connecter immédiatement une boîte réelle.
2. En tant que consultant Bellegarde, je veux que les DOI soient extraits du texte et des liens HTML, afin d’identifier les publications indépendamment de la mise en page de la newsletter.
3. En tant que consultant Bellegarde, je veux que les DOI soient normalisés, afin que leurs variantes d’écriture représentent la même publication.
4. En tant que consultant Bellegarde, je veux que les articles liés sans DOI visible soient conservés provisoirement, afin de ne pas perdre la majorité des références de certaines newsletters.
5. En tant que consultant Bellegarde, je veux que deux newsletters signalant la même référence ne créent qu’une publication, afin d’éviter les doublons.
6. En tant qu’exploitant du NAS, je veux pouvoir relancer le programme sans recréer les messages ou publications, afin qu’une reprise après incident soit sûre.
7. En tant que consultant Bellegarde, je veux recevoir un digest lisible dans un navigateur ou un client mail, afin de contrôler les références détectées.
8. En tant qu’exploitant du NAS, je veux connaître le nombre de messages traités, ignorés et de publications nouvelles, afin de vérifier le succès d’une exécution.
9. En tant qu’exploitant du NAS, je veux un programme compatible Python 3.8 et sans service permanent, afin de l’exécuter sur le DS218 avec le Planificateur de tâches DSM.
10. En tant que consultant Bellegarde, je veux récupérer le titre canonique, la revue, les auteurs, la date et l’abstract disponibles pour un DOI, afin d’évaluer la publication avec plus de contexte.
11. En tant qu’exploitant du NAS, je veux mettre les réponses Crossref en cache, afin de ne pas répéter les appels après une reprise ou une nouvelle exécution.
12. En tant que consultant Bellegarde, je veux un préfiltrage explicable en deux niveaux, afin de réduire le volume envoyé aux étapes coûteuses tout en comprenant chaque sélection.
13. En tant qu’exploitant du NAS, je veux limiter les appels et interrompre un lot après plusieurs erreurs réseau, afin qu’une indisponibilité externe ne bloque pas le NAS pendant une longue durée.

## Implementation Decisions

- Python 3.8+ et bibliothèque standard uniquement.
- Une commande `run` traite tous les fichiers `.eml` d’un dossier, sans les modifier.
- SQLite constitue la source persistante pour les messages, publications et relations entre eux.
- Le `Message-ID` est l’identité préférée d’un courriel ; son empreinte SHA-256 sert de repli.
- Le DOI normalisé en minuscules constitue l’identité canonique d’une publication lorsqu’il est disponible.
- Sans DOI visible, l’empreinte SHA-256 du titre normalisé constitue une identité provisoire.
- L’extraction accepte les DOI visibles et ceux contenus dans les attributs `href` du HTML.
- Les liens d’articles sans DOI sont reconnus uniquement sur une liste explicite de domaines d’éditeurs ; les liens de navigation, événements et numéros spéciaux connus sont ignorés.
- L’API REST Crossref `/works/{doi}` fournit les métadonnées canoniques disponibles ; les DOI sont encodés dans l’URL et une adresse de contact peut identifier l’application.
- Les réponses `success` et `not_found` sont mises en cache dans une table SQLite séparée. Les erreurs transitoires restent à reprendre.
- Un lot enrichit au plus 100 DOI par défaut et refuse les limites hors de l’intervalle 0–1 000. Les références au-delà du plafond restent non livrées jusqu’à un passage ultérieur.
- Trois erreurs d’enrichissement consécutives ouvrent un coupe-circuit pour l’exécution courante.
- Une exécution sans accès Crossref conserve les DOI non enrichis dans la file d’attente ; elle ne les marque pas comme livrés.
- Le préfiltre attribue des points à des concepts comportementaux explicites dans le titre et l’abstract. Un score d’au moins 5 donne la priorité élevée, de 2 à 4 place l’article « À surveiller », et un score inférieur à 2 l’écarte du digest.
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
- Récupération d’un abstract absent de Crossref depuis la page de l’éditeur.
- Second filtrage et résumé par IA.
- Téléchargement ou lecture de PDF.
- Envoi du digest par SMTP.
- Interface web d’administration.

## Further Notes

- Les titres déduits depuis une newsletter restent indicatifs ; Crossref est prioritaire lorsqu’une réponse est disponible.
- La disponibilité des abstracts dans Crossref dépend des dépôts effectués par les éditeurs.
- Une référence sans DOI reste provisoire jusqu’à son enrichissement par une source canonique.
- Le traitement doit rester compatible avec une exécution quotidienne planifiée et interrompue entre deux runs.
