# MVP — Veille scientifique Bellegarde sur DS218

## Problem Statement

Bellegarde reçoit des newsletters d’éditeurs scientifiques contenant plusieurs centaines de références par semaine. Leur dépouillement manuel est répétitif, les mêmes publications peuvent être signalées plusieurs fois et le futur service doit fonctionner de façon autonome sur un Synology DS218 aux ressources limitées.

## Solution

L’application est un programme Python sans dépendance externe qui synchronise en lecture seule le dossier IMAP `Articles`, traite aussi les messages `.eml` et les historiques MBOX/MBOX.ZIP, identifie et déduplique les publications dans SQLite, enrichit leurs métadonnées via Crossref puis les pages éditeurs, applique un préfiltrage explicable, peut confier le second tri et le résumé à une IA structurée, génère un digest HTML et l’envoie par SMTP.

Une commande quotidienne unique orchestre ces étapes sur le DS218. Chaque frontière distante est limitée, mise en cache et reprise après échec. Sans clé d’IA, le service reste fonctionnel avec le préfiltre local et les abstracts disponibles ; sans destinataire SMTP configuré, un mode sans envoi permet une validation complète sur disque.

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
20. En tant qu’exploitant du NAS, je veux synchroniser les nouveaux messages du dossier `Articles` par UID sans modifier leurs drapeaux, afin d’automatiser la collecte sans perturber la boîte.
21. En tant qu’exploitant du NAS, je veux limiter chaque synchronisation et reprendre au passage suivant, afin qu’un historique important ne sature pas le DS218.
22. En tant que consultant Bellegarde, je veux récupérer un abstract depuis la page de l’éditeur lorsque Crossref n’en fournit pas, afin d’améliorer la pertinence du tri.
23. En tant qu’exploitant du NAS, je veux limiter et mémoriser les consultations de pages éditeurs, afin de respecter les services distants et d’éviter les requêtes répétées.
24. En tant que consultant Bellegarde, je veux qu’un second tri IA évalue seulement les références retenues par le préfiltre, afin de maîtriser le coût.
25. En tant que consultant Bellegarde, je veux pour chaque article retenu un résumé français, l’intérêt pour Bellegarde et des applications possibles, afin de décider rapidement s’il mérite une lecture complète.
26. En tant qu’exploitant du NAS, je veux une sortie IA validée par un schéma strict et mise en cache, afin qu’une réponse invalide ou une reprise ne produise pas de contenu incohérent ni de nouvel appel inutile.
27. En tant qu’exploitant du NAS, je veux plafonner le nombre d’analyses IA par exécution, afin de borner le coût et la durée.
28. En tant que consultant Bellegarde, je veux recevoir un courriel HTML avec une alternative texte et les liens DOI ou éditeur, afin de lire la veille dans n’importe quel client mail.
29. En tant qu’exploitant du NAS, je veux que les publications ne soient marquées comme livrées qu’après la réussite de l’envoi ou d’une exécution explicitement sans envoi, afin qu’un échec SMTP reste récupérable.
30. En tant qu’exploitant du NAS, je veux qu’une exécution quotidienne échouée retourne un code non nul et un rapport sans révéler de secret, en JSON par défaut ou dans un format humain explicitement demandé, afin de la superviser dans DSM et de la lire directement en SSH.
31. En tant qu’exploitant du NAS, je veux pouvoir tester tout le parcours avec de faux services aux seules frontières réseau, afin de déployer avec confiance sans dépendre du réseau dans les tests.
32. En tant que consultant Bellegarde, je veux inventorier les éditeurs et revues observés dans l’historique, afin de transférer progressivement les abonnements vers l’adresse dédiée.
33. En tant qu’exploitant du NAS, je veux produire un plan de rattrapage sans aucun appel IA, afin de connaître le volume candidat avant toute dépense.
34. En tant qu’exploitant du NAS, je veux voir une estimation attendue, prudente et maximale fondée sur des tarifs datés, afin de choisir un profil de filtrage en connaissance de cause.
35. En tant qu’exploitant du NAS, je veux imposer un budget cumulé à toute la campagne et le vérifier avant chaque appel, afin qu’une succession de digests ne puisse pas contourner le plafond.
36. En tant que consultant Bellegarde, je veux recevoir les résultats par digests de rattrapage limités et dédupliqués avec la veille quotidienne, afin de dépouiller le corpus progressivement.
37. En tant qu’exploitant du NAS, je veux enrichir uniquement les publications candidates du profil choisi, afin de ne pas solliciter inutilement Crossref et les éditeurs.
38. En tant que consultant Bellegarde, je veux comparer les profils et contrôler un échantillon CSV de leurs candidats sans IA, afin d’ajuster le niveau de bruit avant toute dépense.
39. En tant que consultant Bellegarde, je veux écarter localement les corrections, sommaires et emplois manifestement non humains des termes comportementaux, afin de ne pas enrichir ni analyser des faux positifs structurels.

## Implementation Decisions

- Python 3.8+ et bibliothèque standard uniquement.
- Une commande `run` traite tous les fichiers `.eml` d’un dossier, sans les modifier.
- Une commande `import-mbox` lit un MBOX brut ou un ZIP contenant un MBOX, sans modifier la source ni appel réseau, et marque les références comme historiques non livrables tout en les conservant pour la déduplication.
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
- Les réponses enrichies, incomplètes et `not_found` sont mises en cache dans une table SQLite séparée. Un ancien cache Crossref sans abstract est repris une fois par le repli éditeur ; les erreurs transitoires ne remplacent pas ce cache et restent à reprendre.
- Un lot enrichit au plus 100 DOI par défaut et refuse les limites hors de l’intervalle 0–1 000. Les références au-delà du plafond restent non livrées jusqu’à un passage ultérieur.
- Trois erreurs d’enrichissement consécutives ouvrent un coupe-circuit pour l’exécution courante.
- Une exécution sans accès Crossref conserve les DOI non enrichis dans la file d’attente ; elle ne les marque pas comme livrés.
- Le préfiltre attribue des points à des concepts comportementaux explicites dans le titre et l’abstract. Un score d’au moins 5 donne la priorité élevée, de 2 à 4 place l’article « À surveiller », et un score inférieur à 2 l’écarte du digest.
- Avant d’appliquer les seuils, le préfiltre annule prudemment le score des corrections éditoriales, sommaires de revue et usages uniquement matériels, machiniques, biomédicaux ou moléculaires de `behavior`, `intervention` ou `choice`. Chaque exclusion ajoute une raison explicite et les contextes humains ou comportementaux restent candidats.
- Le digest d’une exécution contient uniquement les publications jamais vues auparavant.
- Une publication reste en attente tant qu’un digest complet n’a pas été écrit ; une relance reprend ces publications après une interruption.
- Le digest est remplacé atomiquement afin de ne jamais exposer un fichier partiellement écrit.
- L’interface testée au niveau le plus élevé est l’exécution du pipeline sur un dossier de messages et l’observation de son rapport, de sa base et de son HTML.
- L’import MBOX est testé à travers son point d’entrée public et sa commande, en observant le rapport, la base, le catalogue et l’intégrité de l’archive.
- Une commande `test-imap` se connecte avec TLS, s’authentifie et sélectionne le dossier configuré avec l’option lecture seule. Elle n’importe, ne déplace et ne marque aucun message.
- Une commande `test-smtp` utilise STARTTLS sur le port 587 par défaut. Elle n’envoie rien sans `--send-test` ; cette option expédie un unique message au destinataire de contrôle configuré.
- La section SMTP est facultative : à défaut, l’hôte et les identifiants IMAP sont réutilisés. La vérification des certificats TLS n’est jamais désactivée.
- Les diagnostics ont un délai réseau de 15 secondes et leurs erreurs masquent le mot de passe avant affichage.
- La synchronisation IMAP s’appuie sur `UIDVALIDITY` et les UID, télécharge le message RFC822 dans un fichier déterministe écrit atomiquement et sélectionne toujours le dossier en lecture seule.
- Un état de synchronisation SQLite sépare chaque compte, dossier et `UIDVALIDITY`. Un plafond borne le nombre de téléchargements ; seuls les UID supérieurs au curseur validé sont considérés lors des passages suivants. Si `UIDVALIDITY` change pour un compte et un dossier connus, la commande échoue explicitement avant tout téléchargement.
- Le premier passage peut télécharger tout le dossier ou positionner le curseur sur le dernier UID sans télécharger l’historique ; dans les deux cas, le curseur n’avance qu’après les écritures réussies.
- Crossref reste la source canonique des métadonnées DOI. Une page éditeur n’est consultée que lorsqu’un abstract manque et qu’une URL HTTP(S) exploitable existe.
- L’extracteur de page lit uniquement les métadonnées HTML standard (`citation_abstract`, Dublin Core, OpenGraph, description et JSON-LD), limite la taille téléchargée et n’essaie pas de contourner un paywall.
- Le préfiltre local reste le premier niveau. L’IA ne reçoit que le titre, l’abstract et les métadonnées bibliographiques des références candidates, jamais le courriel complet ni les identifiants de boîte.
- Le fournisseur IA par défaut utilise l’API Responses d’OpenAI, un modèle économique configurable, `store=false` et des Structured Outputs stricts. La clé vient uniquement d’une variable d’environnement.
- L’analyse IA produit une décision de pertinence, une priorité, un résumé français concis, l’intérêt pour Bellegarde, des applications et des thèmes. Elle est enregistrée par identité de publication et version de modèle/prompt.
- Sans clé ou lorsque l’IA est désactivée, le digest utilise la décision du préfiltre et l’abstract disponible ; cette dégradation est signalée dans le rapport.
- Le digest contient une partie texte et une partie HTML. L’adresse destinataire est obligatoire pour un envoi réel et distincte du destinataire de test.
- Une erreur d’enrichissement ou d’IA laisse la publication concernée en attente. Les exclusions évaluées et les articles envoyés sont marqués traités seulement après la réussite de la livraison globale.
- La commande `daily` enchaîne synchronisation, ingestion, enrichissement, analyse, génération et livraison. `--no-send`, `--no-ai` et les plafonds permettent une validation contrôlée. Sa sortie reste en JSON par défaut pour les appels automatisés ; `--format human` produit un rapport français multiligne, y compris en cas d’erreur, sans modifier le code de sortie.
- Le lanceur NAS `scripts/run-daily.sh` demande le format humain par défaut pour rendre l’appel SSH et les journaux DSM directement lisibles. La variable `VEILLE_REPORT_FORMAT=json` rétablit la sortie machine.
- Le Planificateur de tâches DSM lance `daily` une fois par jour avec des chemins absolus, un fichier INI en mode `600` et la clé IA dans l’environnement du compte dédié.
- Le wizard tente d’abord l’installation publique sans jeton. Si le dépôt est privé, il utilise un jeton finement limité au seul dépôt avec `Contents: read`, saisi masqué, jamais persisté et retiré avant les tests, diagnostics et exécutions quotidiennes.
- Le rattrapage s’appuie sur les publications non livrables importées par MBOX dans la base principale. `backfill-plan` peut enrichir leurs métadonnées mais ne construit jamais de client IA et écrit un plan JSON adressé par son empreinte SHA-256.
- Les profils `strict`, `standard` et `large` correspondent respectivement aux seuils locaux 5, 2 et 1. Un plan comportant encore des enrichissements en attente ne peut pas autoriser l’IA.
- Le plan compare en un passage les volumes des trois profils avant abstracts, enrichit uniquement les candidats du profil actif et calcule l’état prêt sur ces seuls candidats. Un échantillon CSV déterministe et réparti sur toute la liste permet leur contrôle humain.
- Les prix du modèle sont versionnés avec leur date. Le plafond budgétaire retient le tarif d’entrée le plus défavorable, y compris une éventuelle écriture de cache, et la sortie maximale configurée ; un changement de prix invalide le plan.
- `backfill-run` exige un plan intact et un budget en dollars strictement positif. Il additionne les tokens de toutes les analyses du rattrapage déjà mises en cache avant de réserver le coût maximal du prochain appel.
- Un digest de rattrapage contient au plus 15 articles retenus par défaut, utilise le préfixe d’objet `Rattrapage`, puis marque comme livrées les références analysées et les exclusions locales seulement après une livraison réussie ou un `--no-send` explicite.

## Testing Decisions

- Les tests portent sur les comportements externes : extraction, déduplication entre messages, idempotence entre exécutions et contenu du digest.
- Les messages de test sont construits avec la bibliothèque standard et écrits dans un dossier temporaire.
- Les MBOX et ZIP de test sont synthétiques, y compris les métadonnées AppleDouble et les relais éditeurs.
- Aucun réseau, secret ou service externe n’est requis par la suite de tests.
- Les clients IMAP et SMTP sont remplacés à leur frontière système pour vérifier la lecture seule, STARTTLS, l’envoi explicite et l’absence de secret dans les sorties.
- Le parcours `daily` est testé par sa commande publique avec de vrais fichiers, une vraie base temporaire et de faux clients uniquement pour IMAP, HTTP/IA et SMTP.
- Les tests couvrent la reprise après échec, les plafonds, l’absence de double téléchargement et de double livraison, la dégradation sans IA et le masquage des secrets.

## Out of Scope

- Authentification IMAP OAuth ; le mot de passe applicatif reste le mécanisme du MVP.
- Téléchargement ou lecture de PDF.
- Interface web d’administration.
- Contournement de paywall, de CAPTCHA ou de consentement éditeur.
- Garantie mathématique d’envoi SMTP exactement une fois en cas de coupure au moment précis de l’acceptation distante ; l’application privilégie la reprise et documente cette fenêtre rare.
- Inscription automatisée lorsqu’un éditeur exige un compte nominatif, un CAPTCHA ou une confirmation humaine.

## Further Notes

- Les titres déduits depuis une newsletter restent indicatifs ; Crossref est prioritaire lorsqu’une réponse est disponible.
- La disponibilité des abstracts dans Crossref dépend des dépôts effectués par les éditeurs.
- Une référence sans DOI reste provisoire jusqu’à son enrichissement par une source canonique.
- Le traitement doit rester compatible avec une exécution quotidienne planifiée et interrompue entre deux runs.
- Le modèle IA et les limites restent des paramètres d’exploitation afin de pouvoir ajuster coût et qualité sans migration de base.
- Le corpus historique sert à l’inventaire et à la validation ; il ne doit pas provoquer automatiquement l’envoi d’un digest rétrospectif massif.
