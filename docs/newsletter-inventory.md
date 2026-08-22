# Inventaire des newsletters scientifiques

Inventaire établi le 22 août 2026 à partir des 1 358 messages du dossier IMAP
`Articles` et de l’archive MBOX locale. Il recense 8 canaux d’envoi et 67 titres
de revues ou newsletters identifiables. Les nombres entre parenthèses sont les
messages observés sur environ un an ; ils servent à prioriser la migration et ne
constituent pas une mesure de pertinence.

## Comptes éditeurs à migrer

| Plateforme | Expéditeur observé | Messages | Action nécessaire |
|---|---|---:|---|
| Elsevier / ScienceDirect | `sciencedirect@notification.elsevier.com` | 685 | [Compte ScienceDirect et recréation des alertes](https://www.elsevier.support/sciencedirect/answer/how-do-i-set-up-and-manage-my-alerts) |
| APA PsycNet / PsycAlert | `psycalerts@info.apa.org` | 178 | [Connexion au Preference Center APA](https://preferences.apa.org/) et activation des alertes |
| AAAS / Science | `alerts@aaas.sciencepubs.org`, `announcements@aaas.sciencepubs.org` | 176 | Compte Science et alertes Science, Science Advances et In Other Journals |
| Taylor & Francis Online | `alerts@tandfonline.com` | 106 | [Compte Taylor & Francis](https://www.tandfonline.com/) et alertes New Content |
| Nature Portfolio | `ealert@nature.com`, `alerts@nature.com`, `nature@e-alert.nature.com` | 149 | [Compte Springer Nature et alertes par revue](https://support.nature.com/en/support/solutions/articles/6000243009-subscribe-to-journal-email-alerts) |
| Wiley Online Library | `wileyonlinelibrary@wiley.com` | 41 | [Formulaire e-mail ou compte Wiley](https://onlinelibrary.wiley.com/researchers/read/find-research) |
| MDPI | `noreply@mdpi.com` | 23 | Formulaire sur Sustainability puis double confirmation e-mail |

Le total par plateforme dépasse parfois le nombre d’alertes de revues, car une
même plateforme envoie aussi des sélections transversales ou plusieurs formats
d’alerte. Aucune inscription automatique n’est effectuée tant qu’un compte,
un mot de passe, un CAPTCHA ou une validation humaine est demandé.

### État de l’automatisation

La session navigateur disponible n’est connectée à aucun compte éditeur et la
session Chrome personnelle n’est pas accessible. ScienceDirect, APA, Taylor &
Francis et Nature exigent une connexion ; créer des comptes nécessiterait de choisir
et conserver de nouveaux mots de passe. Wiley et MDPI proposent un formulaire direct,
mais l’envoi de `science-digest@bellegarde.co` et l’abonnement sont des actions externes
qui doivent être confirmées au moment de la soumission. MDPI utilise en plus un
double opt-in envoyé dans la boîte dédiée.

## Elsevier / ScienceDirect

- Journal of Environmental Psychology (286)
- Social Science & Medicine (40)
- Computers in Human Behavior (38)
- Journal of Environmental Management (29)
- Cleaner and Responsible Consumption (25)
- Sustainable Production and Consumption (24)
- Addictive Behaviors (23)
- Cleaner Waste Systems (21)
- Waste Management (21)
- One Earth (17)
- Information & Management (14)
- Electronic Commerce Research and Applications (12)
- Environmental Science & Policy (12)
- Journal of Research in Personality (12)
- Environmental Development (11)
- International Journal of Research in Marketing (11)
- Climate Risk Management (10)
- Journal of Experimental Social Psychology (10)
- Environmental and Sustainability Indicators (9)
- Journal of Economic Psychology (9)
- Social Science Research (9)
- Organizational Behavior and Human Decision Processes (7)
- Circular Economy (6)
- Personality and Individual Differences (5)
- Waste Management Bulletin (5)
- Journal of Contextual Behavioral Science (4)
- Current Research in Environmental Sustainability (3)
- Resources, Conservation and Recycling (3)
- Technological Forecasting and Social Change (2)
- Advances in Climate Change Research (1)
- Current Opinion in Environmental Sustainability (1)
- Evolution and Human Behavior (1)
- Green Energy and Resources (1)
- Intelligence (1)
- International Journal of Climate Change Strategies and Management (1)
- Science of The Total Environment (1)

## APA PsycAlert

- Journal of Experimental Psychology: General (64)
- Journal of Personality and Social Psychology (58)
- Journal of Applied Psychology (15)
- History of Psychology (6)
- Motivation Science (6)
- Psychology, Public Policy, and Law (6)
- Journal of Experimental Psychology: Applied (5)
- Journal of Neuroscience, Psychology, and Economics (5)
- Canadian Journal of Behavioural Science (4)
- Group Dynamics: Theory, Research, and Practice (4)
- Decision (3)
- American Psychologist (1)
- Peace and Conflict: Journal of Peace Psychology (1)

## Taylor & Francis Online

- Journal of Human Behavior in the Social Environment (24)
- Ethics & Behavior (23)
- Behavioral Sciences of Terrorism and Political Aggression (18)
- Thinking & Reasoning (17)
- Social Influence (13)
- European Review of Social Psychology (11)

## Nature Portfolio

- Nature (59)
- Nature Human Behaviour (16)
- npj Climate Action (16)
- Communications Psychology (15)
- Nature Reviews Psychology (15)
- Nature Sustainability (13)
- Nature Climate Change (14)
- npj Urban Sustainability (1)

## AAAS / Science

- Science, Table of Contents (62)
- Science Advances (58)
- In Other Journals (55)

## Wiley Online Library

- Journal of Consumer Psychology (41)

## MDPI

- Sustainability (23)

## Ordre de migration recommandé

1. ScienceDirect, qui représente la moitié du trafic et contient le plus grand
   nombre de revues distinctes.
2. APA PsycAlert, Nature Portfolio, AAAS et Taylor & Francis.
3. Wiley et MDPI.
4. Après deux semaines de double réception, comparer automatiquement les
   expéditeurs dans `Articles`, puis désactiver les alertes de l’ancienne adresse.

La double réception temporaire évite une rupture silencieuse. La déduplication de
l’application absorbe les doublons pendant cette période.
