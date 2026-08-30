# Validation sur le corpus local

Validation effectuée le 21 août 2026 sur les 22 newsletters `.eml` fournies dans le
dossier local `inbox`.

## Résultats

- 22 messages traités sur 22, sans erreur ;
- 1 080 signaux de publication détectés ;
- 565 signaux avec DOI ;
- 515 signaux provisoires identifiés par titre et lien ;
- 1 051 références uniques après déduplication ;
- 29 occurrences répétées entre les messages ;
- au moins 2 références détectées dans chaque message.

Cette validation porte sur l’ingestion, l’extraction et la déduplication. Elle ne
mesure pas la précision scientifique du filtre.

## Préfiltrage et enrichissement

- le préfiltrage hors ligne retient 35 références sur les 1 051 références uniques ;
- une validation intégrée limitée à 5 DOI a résolu 5 métadonnées Crossref sur 5 ;
- ces 5 réponses contenaient un titre, une revue et des auteurs ;
- aucune des 5 réponses testées ne contenait d’abstract ;
- les 560 autres DOI sont restés en attente, conformément au plafond de validation ;
- aucune erreur n’a été rencontrée pendant la validation intégrée.

Ce petit échantillon confirme le fonctionnement technique, mais pas un taux de
couverture général. Un repli vers les pages éditeurs reste nécessaire pour les
abstracts absents de Crossref. Le filtre devra également être évalué manuellement
sur ses faux positifs et faux négatifs avant l’envoi automatique.

Les courriels réels, leurs adresses et leur contenu ne sont pas versionnés. Les
tests automatisés emploient des messages synthétiques reproduisant seulement les
structures techniques utiles.

## Import de l’historique MBOX

Validation effectuée le 22 août 2026 sur l’archive locale d’environ un an :

- 1 358 messages traités sur 1 358, sans erreur ;
- 8 domaines expéditeurs couverts ;
- 38 712 signaux de publication détectés ;
- 35 357 références uniques après déduplication bidirectionnelle titre ↔ DOI ;
- 0 message sans publication détectée après ajout des anciens relais Nature ;
- 106 messages Taylor & Francis et 41 messages Wiley couverts ;
- l’archive ZIP source est restée inchangée ;
- une seconde exécution ignore les 1 358 messages déjà connus et conserve les mêmes statistiques de couverture.
- les 35 357 références historiques restent cataloguées mais sont exclues de la file
  livrable ; un test `daily` sur une base MBOX préremplie confirme zéro livraison.

Cette passe ne contacte ni Crossref ni un modèle d’IA. Elle valide l’ingestion,
l’extraction structurelle et l’idempotence, mais pas encore la pertinence métier des
35 357 références. Le prochain jalon consiste à mesurer le préfiltre sur un
échantillon annoté avant de lancer l’enrichissement et les résumés à grande échelle.

## Connectivité de la boîte dédiée

Validation réelle effectuée le 22 août 2026 avec la configuration privée de
`science-digest@bellegarde.co` :

- authentification IMAP TLS réussie sur `mail.infomaniak.com:993` ;
- ouverture initiale de `INBOX` en lecture seule réussie ;
- authentification SMTP avec STARTTLS réussie sur `mail.infomaniak.com:587` ;
- un courriel de contrôle envoyé par la boîte vers elle-même ;
- `INBOX` est passée de 1 à 2 messages après l’envoi, confirmant la livraison ;
- aucun mot de passe n’apparaît dans les rapports JSON ou les tests automatisés.

Le dossier `Articles`, identifié ensuite, contient exactement 1 358 messages. Une
validation réelle de la synchronisation incrémentale a découvert les 1 358 UID,
lu `UIDVALIDITY=1787350414` et téléchargé un message dans un répertoire temporaire,
sans erreur et sans modifier les drapeaux IMAP.

## Parcours quotidien complet

Validation automatisée effectuée le 22 août 2026 avec des services synthétiques aux
seules frontières réseau :

- synchronisation IMAP par UID et reprise sans double téléchargement ;
- initialisation sûre au dernier UID pour ne pas envoyer l’historique ;
- enrichissement Crossref et repli vers les métadonnées de page éditeur ;
- enrichissement des références avec et sans DOI ;
- analyse IA structurée, cache, compteur de tokens et rendu dans le digest ;
- message multipart texte/HTML envoyé par SMTP STARTTLS ;
- absence d’envoi lorsque le digest est vide ;
- conservation des publications en attente après un échec SMTP ;
- commande `daily` validée de bout en bout.
- arrêt explicite lors d’un changement de `UIDVALIDITY`, reprise d’une panne
  transitoire du repli éditeur et séparation des destinataires test/réel.

La suite automatisée compte 112 tests, tous réussis sous Python 3.14 ; le code cible
Python 3.8+ et n’utilise que la bibliothèque standard.

La couche OpenAI n’a pas été appelée avec un compte réel, faute de clé API fournie.
La validation garantit le contrat HTTP et le schéma de réponse, mais la qualité du
classement doit encore être évaluée sur un échantillon annoté avant activation.

## Préfiltrage du rattrapage

Audit statique effectué le 26 août 2026 sur un échantillon réparti de 100 candidats
du profil standard, sans enrichissement ni appel IA. Huit faux positifs structurels
ont pu être écartés avec des règles prudentes : corrections et corrigenda, sommaires
de revue, comportement de matériaux ou de machines, travail biomédical moléculaire
et choix de voies biologiques.

Appliquées en lecture seule aux 35 453 références encore disponibles, ces règles
font passer le profil standard de 2 192 à 2 122 candidats, le profil strict de 210 à
202 et le profil large de 2 614 à 2 540. Les tests de conservation couvrent les
interventions, la décision humaine, les contextes humains présents seulement dans
l’abstract et les articles pertinents à faible score. Cette mesure ne remplace pas
l’examen des abstracts ni la décision IA.

## Pilote Elsevier pour les abstracts

Mesure en lecture seule effectuée le 27 août 2026 sur la base montée du NAS, avant
tout appel à l’API Elsevier :

- 35 453 références de rattrapage encore disponibles ;
- 2 121 candidates avec le profil standard courant ;
- 1 269 candidates ont un lien ScienceDirect avec PII et un ancien statut
  `not_found` ;
- ces liens représentent 1 262 PII uniques.

La version 0.6.3 reprend ces références par lots via l’API Elsevier officielle,
avant tout appel IA. Cette mesure donne le plafond du pilote, pas son taux de
réussite : la couverture réelle des abstracts sera calculée sur le rapport produit
par le NAS après configuration de la clé.

Le correctif 0.6.4 reproduit le refus observé par un faux endpoint sensible à la
casse, préserve exactement l’en-tête `X-ELS-APIKey` documenté et valide la structure
réelle des auteurs `coredata.dc:creator.author` sans inscrire la clé dans l’URL.

## Droits de la clé Elsevier (27 août 2026)

Vérification directe de l’API `content/abstract/pii` avec la clé du NAS :

| Requête | Résultat |
| --- | --- |
| en-tête `X-ELS-APIKey`, vue par défaut | `HTTP 200`, sans résumé |
| en-tête `X-ELS-APIKey`, `view=META` | `HTTP 200`, sans résumé |
| en-tête `X-ELS-APIKey`, `view=META_ABS` | `HTTP 401 AUTHORIZATION_ERROR` |
| en-tête `X-ELS-APIKey`, `view=FULL` | `HTTP 401 AUTHORIZATION_ERROR` |
| `apiKey` en paramètre, `view=META_ABS` | `HTTP 401 AUTHORIZATION_ERROR` |
| `content/article/pii`, `view=META_ABS` | `HTTP 403 AUTHENTICATION_ERROR` |
| `search/scopus`, champ `dc:description` | `HTTP 200`, champ retiré de la réponse |

Conclusions :

- la clé est valide et l’authentification par en-tête fonctionne ;
- le `401` portait sur la vue demandée, non sur la clé ;
- aucun résumé n’est accessible sans abonnement institutionnel ;
- les résumés ScienceDirect doivent donc venir de la page éditeur ou d’une
  source tierce.

## Couverture des résumés par source (27 août 2026)

Mesure sur trois corpus, en interrogeant chaque API par DOI.

Corpus local (565 DOI issus des 22 newsletters de `inbox` : MDPI, Nature) :

| Source | Couverture |
| --- | --- |
| OpenAlex | 94 % |
| Crossref | 93 % |
| Europe PMC | 2 % |
| Union | **96 %** |

Échantillon Elsevier tiré des revues suivies (428 DOI, *J. Environmental
Psychology*, *J. Environmental Management*, *Global Environmental Change*,
*Ecological Economics*, *Energy Policy*, *Cognition*, *Appetite*, etc.) :

| Source | Couverture |
| --- | --- |
| Crossref | 0 % |
| OpenAlex | 41 % |
| Europe PMC | 24 % |
| Union | **54 %** |

Échantillon Elsevier aléatoire (400 DOI, toutes disciplines) : union 46 %.

Conclusions :

- Crossref ne contient aucun résumé Elsevier : l’éditeur n’en dépose pas ;
- les deux catalogues ouverts sont complémentaires et non redondants —
  ajouter Europe PMC à OpenAlex fait gagner 13 points sur le corpus Elsevier ;
- environ 46 % des articles Elsevier suivis n’ont de résumé dans aucune
  source ouverte ; seul un accès institutionnel les couvrirait.

## Gain mesuré sur l’arriéré du NAS (27 août 2026)

La base de production compte 1 848 publications enrichies sans résumé, dont
1 341 connues par leur seule URL ScienceDirect, sans DOI enregistré. Les
catalogues ouverts n’interrogeant que par DOI, ces publications leur étaient
inaccessibles : la vue `META` d’Elsevier sert désormais de relais, puisqu’elle
fournit le DOI sans le résumé.

Mesure sur un échantillon de 40 URL tirées de cet arriéré, cascade complète :

| Étape | Résultat |
| --- | --- |
| DOI résolus par Elsevier `META` | 38/40 (95 %) |
| Résumés récupérés | 25/40 (**62 %**) |
| Échecs de source | aucun |

Extrapolation : environ 840 résumés récupérables sur les 1 341 concernés.

Restent 28 entrées en cache disposant d’un DOI mais hors ScienceDirect, que la
politique de reprise actuelle ne réessaie pas.

## Reprise des métadonnées sans résumé (27 août 2026)

Les publications déjà pourvues d’une ligne de métadonnées sont exclues des
sélections automatiques (`pm.publication_identity IS NULL`). Une nouvelle
source de résumés ne leur profite donc jamais. La commande
`refresh-abstracts` les réinterroge explicitement, par lots bornés ; la
sélection automatique reste inchangée pour qu’un article définitivement sans
résumé n’épuise pas le quota au détriment des nouveautés.

Composition des 1 848 entrées concernées dans la base de production :

| Nature | Nombre |
| --- | --- |
| URL ScienceDirect (PII) | 1 341 |
| Redirection APA (`click.info.apa.org`) | 209 |
| Redirection AAAS | 124 |
| Redirection Taylor & Francis | 119 |
| DOI enregistré | 28 |
| Wiley, Springer | 27 |

Essai sur copie de la base, 40 entrées, ordre `checked_at` croissant :
8 résumés récupérés. Ce premier lot n’est pas représentatif — il contient
24 redirections de traçage pour seulement 9 URL ScienceDirect, alors que
ces dernières forment 73 % de la file et rendent 62 % de résumés.

## Lecture des pages ScienceDirect abandonnée (27 août 2026)

Les mesures du 27 août montrent que ScienceDirect refuse toute lecture
automatisée : `HTTP 403` et page de vérification, avec ou sans en-tête de
navigateur, y compris depuis un navigateur complet. En production, l’essai se
solde le plus souvent par une expiration du délai de 10 secondes.

Sur 500 reprises, trois avertissements d’expiration ont été remontés, dont
deux sur des URL passerelle ScienceDirect. Étendu aux 1 341 entrées
ScienceDirect de la file, l’essai représentait jusqu’à 3 h 40 d’attente pure,
et ces échecs alimentaient le compteur d’erreurs consécutives susceptible
d’interrompre un lot.

La cascade s’arrête donc après Elsevier et les catalogues ouverts pour les URL
ScienceDirect. Les autres éditeurs restent lus normalement.

## Avancement de la file de reprise (27 août 2026)

La file est ordonnée par `checked_at`. Jusqu’en 0.8.1, seule une reprise
réussie mettait cette date à jour : une entrée sans résumé conservait son
horodatage et restait en tête. Chaque exécution rejouait donc exactement le
même lot. Observé en production : 70 puis 175 résumés récupérés, puis 2, puis
0, sans que la file progresse.

Chaque tentative note désormais son passage, succès ou non. Vérifié sur copie
de la base de production : la tête de file est passée du 22 au 26 août après
deux lots de 60.

Rendement des 1 097 entrées ScienceDirect restantes, sur 25 tirées au hasard :
**16 résumés sur 25 (64 %)**. Le rendement nul des derniers lots venait de la
tête de file, occupée par des redirections APA et AAAS improductives.

## Recherche par titre (27 août 2026)

Après un parcours complet de la file, 904 entrées restaient sans résumé :
406 ScienceDirect, 474 redirections de lettres d’information et 20 DOI.

Les redirections mènent à des pages bloquées (`psycnet.apa.org` répond 403)
ou à des liens expirés (`redirect_error.html`). Le lien est donc inexploitable,
mais 900 de ces 904 entrées possèdent un titre.

Recherche OpenAlex par titre, sur 30 entrées tirées au hasard :

| Résultat | Nombre |
| --- | --- |
| Titre retrouvé (similarité ≥ 0,90) | 24/30 |
| Dont pourvu d’un résumé | **19/30** |

Reprise réelle sur copie de la base, 60 entrées qui ne rendaient plus rien :
**30 résumés récupérés**.

Deux limites relevées et corrigées :

- la ponctuation des titres (`?`, virgule, apostrophe courbe) provoquait des
  refus `HTTP 400` : seuls les mots sont désormais transmis ;
- des appels trop rapprochés provoquent un `HTTP 429` : le client patiente
  puis réessaie une fois.

Un titre trouvé dont la similarité est inférieure à 0,90 est rejeté :
rattacher le résumé d’un autre article serait pire que n’en rattacher aucun.

## Budget de recherche OpenAlex (27 août 2026)

OpenAlex facture désormais ses requêtes en crédits. Réponse observée :

```
HTTP 429
retry-after: 43204
x-ratelimit-limit: 1000
x-ratelimit-credits-required: 10
"Insufficient budget. […] Resets at midnight UTC."
```

Soit **1 000 crédits par jour et 10 crédits par recherche**, donc cent
recherches quotidiennes. Un lot de 200 entrées en demandait le double : sur
une exécution réelle, 98 appels sur 200 ont été refusés.

En revanche, une consultation par DOI a répondu `HTTP 200` alors qu’il ne
restait que 4 crédits, **sans en consommer**. La cascade principale n’est donc
pas concernée ; seules les recherches le sont.

Le dernier recours par titre passe désormais par Crossref, dont la recherche
est gratuite et sans plafond : elle retrouve le DOI dans 23 cas sur 25, et ce
DOI rouvre l’accès gratuit à OpenAlex et Europe PMC. La recherche OpenAlex par
titre n’intervient qu’ensuite et cesse dès le premier refus, au lieu
d’échouer à chaque entrée.

Reprise réelle sur copie de la base, 80 entrées :

| Version | Récupérés | Échecs OpenAlex |
| --- | --- | --- |
| 0.9.0 (200 entrées) | 37 (18 %) | 98 |
| 0.9.1 (80 entrées) | **30 (37 %)** | **0** |

## Révision de la consigne de tri IA (27 août 2026)

Comparaison à l’aveugle de `gpt-5.6-luna` et de Claude Opus 5 sur 34 articles
tirés du plan de rattrapage, jugés avec la consigne `bellegarde-v2`. Les
verdicts ont été appariés, étiquettes masquées, position tirée au sort à
17 contre 17, puis arbitrés par le consultant.

Résultat agrégé : 12 pour `gpt-5.6-luna`, 10 pour Opus 5, 12 égalités. En
séparant les cas où les modèles jugeaient différemment de ceux où ils
jugeaient pareil, deux signaux opposés apparaissent :

| Sous-ensemble | Opus 5 | gpt-5.6-luna |
| --- | --- | --- |
| Jugement (11 verdicts divergents) | **7** | 4 |
| Écriture (11 verdicts identiques) | 3 | **8** |

Aucune variable de surface mesurée — longueur, longueur de phrase, mentions
de réserves méthodologiques, densité de chiffres — ne prédit les choix
d’écriture : toutes ressortent autour de 6 sur 11.

Les 34 arbitrages ont servi de référence. Contre elle : Opus 5 obtient 30/34,
`bellegarde-v2` 27/34. La consigne a été révisée en deux itérations puis
atteint 31/34 — score surajusté, la révision ayant été réglée contre ce même
jeu.

Validation sur 30 articles tirés de la même population et jamais utilisés
pour le réglage :

| | Consigne actuelle | Consigne révisée |
| --- | --- | --- |
| Duels remportés (9 divergences) | 1 | **7** |

Un duel n’a été attribué à aucune des deux. Sur les 8 départagés, p unilatéral
= 0,035. Sur les 21 verdicts concordants servant de contrôle, 18 ont été jugés
justes, 3 trop généreux et aucun trop sévère.

La consigne révisée est adoptée sous le nom `bellegarde-v3`. Elle place un
test de périmètre avant toute considération de méthode, classe en watch
plutôt qu’en excluded le travail applicatif méthodologiquement faible, et
borne l’accès au niveau high par des critères négatifs plutôt que par une
liste d’exemples, celle-ci ayant été lue comme un ensemble de conditions
suffisantes.

Coût : 773 à 1 150 tokens d’entrée par article, soit environ 0,16 $US
supplémentaires sur l’ensemble du rattrapage.

## Séparation du classement et de la distribution (version 0.11.0)

La consigne `bellegarde-v4` conserve les règles de décision de la version 3 et
ajoute trois champs contrôlés : score d’intérêt, qualité des preuves et raison du
classement. Les plages de score sont validées par le programme : 80–100 pour
`high`, 40–79 pour `watch`, 0–39 pour `excluded`.

Un article sans abstract ne peut pas recevoir `high`. Sa qualité doit être
`unknown` et sa synthèse doit signaler que le classement repose sur le titre. Il
est conservé dans le CSV mais exclu de la file de distribution.

Tests automatisés sur Python 3.9 :

- interruption après un article puis reprise sans second appel pour cet article ;
- classement complet sans modification de `delivered_at` ;
- refus de distribuer tant qu’un candidat reste sans classement ;
- exclusion des articles sans abstract du digest quotidien ;
- marquage comme distribué uniquement après succès SMTP ;
- aperçu `--no-send` sans modification de la file.

## Complétude des auteurs (version 0.11.1)

Certaines réponses Elsevier ne fournissent que le premier auteur, même lorsque
Crossref en référence plusieurs. Pour une publication ScienceDirect connue par
son titre, l’enrichissement complète désormais la bibliographie avec Crossref et
conserve la liste la plus longue. Le digest affiche les trois premiers auteurs,
puis `et al.` à partir de quatre auteurs. Le plan de rattrapage reprend aussi,
par lots bornés, les métadonnées ScienceDirect déjà enregistrées avec zéro ou
un seul auteur ; les véritables publications à auteur unique ne sont vérifiées
qu’une fois. Cette reprise utilise Crossref et ne dépend pas de la clé Elsevier.
Une panne temporaire place l’entrée en fin de file pour une tentative ultérieure.

## Grille de classement auditée (version 0.12.0)

La consigne `bellegarde-v5` ne produit plus directement de catégorie ni de note
globale. Elle retourne cinq sous-notes discrètes : adéquation aux missions sur 25,
robustesse scientifique sur 25, actionnabilité sur 25, généralisation sur 15 et
nouveauté sur 10. Le programme additionne ces valeurs, applique les exclusions et
plafonds, puis détermine `high` à partir de 80, `watch` de 55 à 79 et `excluded`
en dessous de 55.

Une Pépite exige en plus un abstract, une robustesse d’au moins 20, une
actionnabilité d’au moins 15, une généralisation d’au moins 9 et une qualité des
preuves `strong`. Les études descriptives limitées à un contexte unique sont
plafonnées à 69 ; les expériences de laboratoire isolées et revues systématiques
sans tailles d’effet sont plafonnées à 79. Les expériences de moins de 25
participants par condition, revues non systématiques, éditoriaux et travaux hors
périmètre sont écartés indépendamment du total brut.

Les tests de calibration couvrent notamment l’étude sur le PTSD dans les décisions
d’asile suédoises : 15 + 15 + 10 + 3 + 6 = 49, donc `excluded`. Ils couvrent aussi
la frontière `watch` à 55, tous les plafonds, chaque condition obligatoire de
`high`, l’absence d’abstract, la migration SQLite et l’export des sous-notes dans
le CSV de contrôle. Aucun appel OpenAI réel n’est effectué par ces tests.
