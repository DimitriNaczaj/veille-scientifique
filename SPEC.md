# MVP — Veille scientifique Bellegarde sur DS218

## Problem Statement

Bellegarde reçoit des newsletters d’éditeurs scientifiques contenant plusieurs centaines de références par semaine. Leur dépouillement manuel est répétitif, les mêmes publications peuvent être signalées plusieurs fois et le futur service doit fonctionner de façon autonome sur un Synology DS218 aux ressources limitées.

## Solution

L’application est un programme Python sans dépendance externe qui traite des messages `.eml` et importe des historiques MBOX/MBOX.ZIP, identifie les DOI ainsi que les titres liés par les éditeurs pris en charge, conserve un historique SQLite, déduplique les publications, enrichit les DOI via Crossref, applique un préfiltrage explicable et génère un digest HTML.

Les incréments réalisés valident le cœur idempotent, l’enrichissement distant, la réduction de volume et la connectivité IMAP/SMTP avant d’ajouter la collecte automatique, le classement par IA et l’envoi du digest.

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
14. En tant que consultant Bellegarde, je veux importer un historique MBOX sans appel externe, afin de constituer le catalogue initial sans coût d’IA.
15. En tant qu’exploitant du NAS, je veux obtenir un catalogue CSV et un rapport JSON par éditeur, afin de contrôler la couverture avant tout filtrage coûteux.
16. En tant qu’exploitant du NAS, je veux qu’une archive ZIP et ses messages restent inchangés, afin que l’import soit reproductible et réversible.
17. En tant qu’exploitant du NAS, je veux tester l’authentification IMAP et ouvrir le dossier en lecture seule, afin de valider la configuration sans modifier les messages.
18. En tant qu’exploitant du NAS, je veux tester l’authentification SMTP sans envoi puis déclencher explicitement un courriel de contrôle, afin de distinguer connexion et livraison.
19. En tant qu’exploitant du NAS, je veux que les diagnostics ne révèlent jamais le mot de passe, y compris en cas d’erreur distante.

## Implementation Decisions

- Python 3.8+ et bibliothèque standard uniquement.
- Une commande `run` traite tous les fichiers `.eml` d’un dossier, sans les modifier.
- Une commande `import-mbox` lit un MBOX brut ou un ZIP contenant un MBOX, sans modifier la source, sans appel réseau et sans marquer les références comme livrées.
- Les chemins de la source, de la base, du catalogue et du rapport doivent être distincts ; toute collision est refusée avant ouverture de la base.
- Les fichiers techniques AppleDouble placés dans `__MACOSX` sont ignorés lors de la sélection du MBOX dans un ZIP.
- SQLite constitue la source persistante pour les messages, publications et relations entre eux.
- Le `Message-ID` est l’identité préférée d’un courriel ; son empreinte SHA-256 sert de repli.
- Le DOI normalisé en minuscules constitue l’identité canonique d’une publication lorsqu’il est disponible.
- Sans DOI visible, l’empreinte SHA-256 du titre normalisé constitue une identité provisoire.
- Un index persistant titre normalisé → publication réconcilie l’identité provisoire et l’identité DOI quel que soit leur ordre d’arrivée, y compris lorsque le titre vient de Crossref. Une migration de schéma versionnée réconcilie une seule fois les doublons déjà présents.
- L’extraction accepte les DOI visibles et ceux contenus dans les attributs `href` du HTML.
- Les liens d’articles sans DOI sont reconnus uniquement sur une liste explicite de domaines d’éditeurs, incluant les relais Wiley et Taylor & Francis ; les liens de navigation, événements et numéros spéciaux connus sont ignorés.
- Les anciens relais AWS de Nature sont décodés uniquement lorsqu’ils révèlent une URL canonique `nature.com/articles/...`, afin de ne pas conserver un lien de suivi personnalisé.
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
- L’import MBOX est testé à travers son point d’entrée public et sa commande, en observant le rapport, la base, le catalogue et l’intégrité de l’archive.
- Une commande `test-imap` se connecte avec TLS, s’authentifie et sélectionne le dossier configuré avec l’option lecture seule. Elle n’importe, ne déplace et ne marque aucun message.
- Une commande `test-smtp` utilise STARTTLS sur le port 587 par défaut. Elle n’envoie rien sans `--send-test` ; cette option expédie un unique message au destinataire de contrôle configuré.
- La section SMTP est facultative : à défaut, l’hôte et les identifiants IMAP sont réutilisés. La vérification des certificats TLS n’est jamais désactivée.
- Les diagnostics ont un délai réseau de 15 secondes et leurs erreurs masquent le mot de passe avant affichage.

## Testing Decisions

- Les tests portent sur les comportements externes : extraction, déduplication entre messages, idempotence entre exécutions et contenu du digest.
- Les messages de test sont construits avec la bibliothèque standard et écrits dans un dossier temporaire.
- Les MBOX et ZIP de test sont synthétiques, y compris les métadonnées AppleDouble et les relais éditeurs.
- Aucun réseau, secret ou service externe n’est requis par la suite de tests.
- Les clients IMAP et SMTP sont remplacés à leur frontière système pour vérifier la lecture seule, STARTTLS, l’envoi explicite et l’absence de secret dans les sorties.

## Out of Scope

- Collecte IMAP automatisée par UID ou authentification OAuth.
- Récupération d’un abstract absent de Crossref depuis la page de l’éditeur.
- Second filtrage et résumé par IA.
- Téléchargement ou lecture de PDF.
- Envoi automatique du digest par SMTP.
- Interface web d’administration.

## Further Notes

- Les titres déduits depuis une newsletter restent indicatifs ; Crossref est prioritaire lorsqu’une réponse est disponible.
- La disponibilité des abstracts dans Crossref dépend des dépôts effectués par les éditeurs.
- Une référence sans DOI reste provisoire jusqu’à son enrichissement par une source canonique.
- Le traitement doit rester compatible avec une exécution quotidienne planifiée et interrompue entre deux runs.
