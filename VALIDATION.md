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
