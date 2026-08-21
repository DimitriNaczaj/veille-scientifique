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
