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

Cette passe ne contacte ni Crossref ni un modèle d’IA. Elle valide l’ingestion,
l’extraction structurelle et l’idempotence, mais pas encore la pertinence métier des
35 357 références. Le prochain jalon consiste à mesurer le préfiltre sur un
échantillon annoté avant de lancer l’enrichissement et les résumés à grande échelle.

## Connectivité de la boîte dédiée

Validation réelle effectuée le 22 août 2026 avec la configuration privée de
`science-digest@bellegarde.co` :

- authentification IMAP TLS réussie sur `mail.infomaniak.com:993` ;
- ouverture de `INBOX` en lecture seule réussie ;
- authentification SMTP avec STARTTLS réussie sur `mail.infomaniak.com:587` ;
- un courriel de contrôle envoyé par la boîte vers elle-même ;
- `INBOX` est passée de 1 à 2 messages après l’envoi, confirmant la livraison ;
- aucun mot de passe n’apparaît dans les rapports JSON ou les tests automatisés.

La boîte distante ne contenait que deux messages après ce contrôle, et non les
quelque 1 300 messages de l’archive historique. Il faudra donc localiser le dossier
IMAP de destination de ces transferts, ou confirmer qu’ils n’existent que dans
l’export MBOX, avant de développer la collecte quotidienne.

Un dernier diagnostic d’authentification, sans envoi, a encore validé IMAP et SMTP
mais a trouvé `INBOX` vide. Ces diagnostics n’altèrent pas les messages ; l’emplacement
actuel des newsletters historiques reste donc à identifier côté boîte mail.
