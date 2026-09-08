# Améliorations du digest — pistes priorisées

Recherche et recommandations au 1er septembre 2026. Les trois boutons restent
le mécanisme central : l’objectif est d’obtenir un signal humain plus utile
sans transformer chaque digest en questionnaire.

## À faire en premier

### 1. Ajouter une raison facultative au feedback

Après le choix Pépite/Éventuellement/Écarté, proposer dans le courriel préparé
un code non obligatoire : `hors-sujet`, `peu-actionnable`, `preuve-faible`,
`déjà-connu`, `autre`. La catégorie dit *où* déplacer l’article ; la raison dit
*quoi* corriger dans la grille. Conserver le texte libre seulement pour
`autre` afin que la réponse reste rapide.

### 2. Montrer « Pourquoi retenu ? »

Afficher une ligne compacte avec la qualité des preuves, la raison de
classement et deux critères dominants. Ces données existent déjà. Cette
transparence rend les corrections plus précises et permet de repérer un résumé
convaincant appuyé sur une preuve faible.

### 3. Introduire un petit échantillon de contrôle

Une fois par semaine, présenter 3 à 5 articles proches de la frontière mais
écartés, dans une section « À vérifier ». L’apprentissage actif consiste à
faire étiqueter les cas les plus informatifs ou incertains, ce qui peut réduire
l’effort d’annotation par rapport à un échantillonnage indifférencié. Ici, ce
lot mesure surtout les faux négatifs, invisibles dans un digest composé
uniquement d’articles retenus.

### 4. Mesurer avant de réécrire la consigne

Tableau mensuel : accord global, taux de remontée, taux d’abaissement, taux de
sauvetage de l’échantillon exclu, désaccord par revue/thème/version de prompt,
et délai avant feedback. Utiliser seulement la dernière décision par article,
avec au moins trois remontées et trois abaissements avant toute interprétation.

## Deuxième vague

- Regrouper les articles par thème et signaler les doublons conceptuels pour
  rendre le digest plus court sans perdre de couverture.
- Ajouter un temps de lecture estimé et plafonner la longueur des résumés.
- Permettre des préférences simples par thème : davantage, normal, moins.
- Conserver le bouton Zotero indépendant du feedback : il ouvre la page de
  l’article pour que le connecteur l’enregistre uniquement à la demande.
- Ajouter des indicateurs de provenance : canal de découverte, présence de
  l’abstract, date de mise à jour et lien DOI canonique.
- Ne pas utiliser le pixel d’ouverture comme mesure d’usage : les protections
  de confidentialité des clients mail rendent ce signal moins interprétable.
  Privilégier les clics explicites et les feedbacks.

## Qualité du courriel

- Vérifier WCAG 2.2 AA : contraste texte 4,5:1, information non portée par la
  seule couleur, texte redimensionnable et cibles suffisamment espacées.
- Garder l’alternative texte et tester VoiceOver ainsi que le mode sombre.
- Vérifier SPF, DKIM et DMARC du domaine. Les recommandations Gmail imposent au
  minimum SPF ou DKIM, TLS et un format RFC 5322 ; les exigences de désabonnement
  en un clic concernent surtout les envois de masse, pas ce digest individuel.
- Garder le RIS facultatif : le poids du message ne doit pas pénaliser la
  délivrabilité lorsque l’import de lot n’est pas utilisé.

## Ordre recommandé

1. Raisons de feedback et ligne « Pourquoi retenu ? ».
2. Échantillon hebdomadaire d’exclus et métriques mensuelles.
3. Regroupement thématique et préférences.
4. Audit d’accessibilité et de délivrabilité à chaque changement de gabarit.

## Sources

- [W3C — WCAG 2.2](https://www.w3.org/TR/WCAG22/)
- [W3C — taille minimale des cibles](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum)
- [Google — règles applicables aux expéditeurs Gmail](https://support.google.com/mail/answer/81126)
- [RFC 8058 — désabonnement en un clic](https://www.rfc-editor.org/info/rfc8058/)
- [Apple — protection de la confidentialité dans Mail](https://support.apple.com/guide/mail/protect-email-privacy-mlhlp1205/mac)
- [Xue et Hauskrecht — Active Learning of Classification Models with Likert-Scale Feedback](https://pmc.ncbi.nlm.nih.gov/articles/PMC5624557/)
