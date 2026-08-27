# Todo — version 2

- [ ] Ajouter à chaque article un bouton « Ajouter à Zotero ».
- [ ] Ajouter, pour chaque auteur, un lien vers sa recherche Google Scholar.

## Livré en version 0.7.1

- [x] Relayer aux catalogues ouverts le DOI qu’Elsevier fournit en vue `META`.

## Livré en version 0.7.0

- [x] Enrichir les résumés par OpenAlex quand Crossref n’en fournit pas.
- [x] Compléter par Europe PMC les résumés qu’OpenAlex n’a pas.
- [x] Poursuivre l’enrichissement malgré la panne d’un catalogue ouvert.

## Livré en version 0.6.5

- [x] Distinguer un refus de vue Elsevier d’une panne de service.
- [x] Rétrograder l’enrichissement Elsevier vers `META` quand `META_ABS` n’est pas couvert.

## En suspens

- [ ] Accès Elsevier aux résumés (vue `META_ABS`) : mis de côté, suppose une
      démarche auprès d’Elsevier. Voir VALIDATION.md pour les droits mesurés.

## Livré en version 0.6.4

- [x] Préserver exactement la casse de l’en-tête d’authentification Elsevier.
- [x] Lire les auteurs dans la structure JSON réellement renvoyée par l’API.

## Livré en version 0.6.3

- [x] Tester l’enrichissement des liens ScienceDirect par PII via l’API Elsevier.
- [x] Reprendre par lots les anciens `not_found` Elsevier sans appel IA.
- [x] Stocker la clé Elsevier hors de l’INI avec une saisie masquée.

## Livré en version 0.6.2

- [x] Réduire les faux positifs structurels du préfiltre sans durcir le profil standard.

## Livré en version 0.6

- [x] Préparer un rattrapage sans appel IA et en estimer les tokens et le coût.
- [x] Exiger un budget cumulé avant tout appel IA du rattrapage.
- [x] Produire des digests de rattrapage limités à 15 articles par défaut.
- [x] Limiter l’enrichissement aux candidats et exporter un échantillon CSV.
- [x] Comparer les profils strict, standard et large dans un seul plan.
