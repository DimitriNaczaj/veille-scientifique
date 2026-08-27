# Veille scientifique Bellegarde

Application de veille scientifique autonome et légère pour Synology DS218.

## Fonctionnalités actuelles

- lecture de newsletters `.eml` ;
- import ponctuel d’historiques MBOX ou MBOX.ZIP ;
- synchronisation IMAP incrémentale du dossier `Articles` par UID, en lecture seule ;
- extraction des DOI depuis le texte et les liens HTML ;
- découverte des articles sans DOI depuis les titres et liens de suivi des éditeurs pris en charge ;
- enrichissement par Crossref, par l’API Elsevier pour les liens ScienceDirect,
  puis par les métadonnées HTML/JSON-LD des pages éditeurs ;
- cache d’enrichissement persistant et reprise après panne ;
- préfiltrage explicable en sciences comportementales, avec exclusions prudentes
  des corrections, sommaires et usages manifestement non humains des mots-clés ;
- classement en « Priorité élevée » et « À surveiller » ;
- second tri et résumés français structurés via l’API OpenAI, lorsque configurée ;
- déduplication persistante avec SQLite ;
- génération d’un digest HTML avec alternative texte et envoi SMTP ;
- diagnostic IMAP en lecture seule et diagnostic SMTP avec envoi test optionnel ;
- relance idempotente ;
- séparation stricte entre le catalogue historique et la file quotidienne livrable ;
- rattrapage contrôlé avec estimation sans IA, budget cumulé et digests limités ;
- aucune dépendance Python externe.

Une référence sans DOI est conservée provisoirement à partir de son titre normalisé.
Crossref ne contient pas un abstract pour chaque DOI. Pour Elsevier, l’application
utilise le PII présent dans les liens ScienceDirect et l’API officielle lorsqu’une
clé est configurée. Le digest affiche uniquement les métadonnées réellement
disponibles et signale les références encore provisoires.
L’application ne télécharge pas les PDF et ne contourne aucun paywall.

Les évolutions envisagées pour la version 2 sont suivies dans
[`TODO.md`](TODO.md).

## Exécution quotidienne

Après avoir adapté `veille-scientifique.ini.example` et chargé les secrets dans
l’environnement, une seule commande réalise le parcours complet :

```bash
SCIENCE_DIGEST_MAIL_PASSWORD=... OPENAI_API_KEY=... ELSEVIER_API_KEY=... python3 -m veille daily \
  --config veille-scientifique.ini
```

Elle synchronise IMAP, ingère et déduplique les articles, enrichit les métadonnées,
applique le préfiltre, analyse au plus 30 références par IA, écrit le digest puis
l’envoie. Tous les plafonds sont configurables dans le fichier INI. Le rapport JSON
indique notamment les nouveaux messages, les publications en attente, les tokens IA
consommés et le résultat SMTP.

Au tout premier lancement, `imap.initial_mode = latest` positionne le curseur sur le
dernier UID sans télécharger les 1 358 messages historiques. Les nouveaux messages
sont ensuite collectés normalement. Utiliser explicitement `sync-imap
--initial-mode all` dans une base séparée pour récupérer un historique.

Deux modes permettent une recette sans effet externe :

```bash
python3 -m veille daily --config veille-scientifique.ini --no-ai --no-send
python3 -m veille sync-imap --config veille-scientifique.ini \
  --inbox ./inbox --database ./data/veille.sqlite --limit 10
```

Sans `OPENAI_API_KEY`, la commande quotidienne continue avec le préfiltre local et
les abstracts disponibles. `--no-send` considère explicitement le digest généré
comme traité ; l’utiliser avec une base de recette, pas avec la base de production.

## Exécution locale

```bash
CROSSREF_EMAIL=veille@votre-domaine.fr python3 -m veille run \
  --inbox ./inbox \
  --database ./data/veille.sqlite \
  --output ./out/digest.html
```

L’adresse de contact, recommandée par Crossref pour accéder au « polite pool », peut
aussi être transmise avec `--crossref-email`. Elle n’est ni stockée dans SQLite ni
incluse dans le digest.

Le programme enrichit au maximum 100 DOI par exécution. Le reliquat reste en attente
pour le passage suivant. Ce plafond se règle avec `--enrichment-limit`, entre 0 et
1 000. Après trois erreurs réseau consécutives, les appels s’arrêtent sans perdre les
références.

Pour tester sans réseau, utiliser `--no-enrichment`. Les DOI non encore enrichis
restent alors en attente ; ils ne sont ni perdus ni marqués comme livrés. Pour
désactiver temporairement le préfiltrage, utiliser `--no-filter`.

Le programme affiche un rapport JSON exploitable par un script ou le Planificateur
de tâches DSM. `publications_new` compte les nouvelles identités insérées,
`publications_delivered` les références effectivement analysées pour le digest et
`publications_pending` le reliquat à reprendre.

## Importer un historique de newsletters

L’import d’un export MBOX est entièrement local : il ne contacte ni Crossref ni un
service d’IA, ne modifie pas l’archive source et classe les publications comme
historiques non livrables. Elles restent dans le catalogue et participent à la
déduplication, mais ne peuvent pas être envoyées par `daily`. Il accepte un fichier
MBOX brut ou un ZIP contenant un unique MBOX :

```bash
python3 -m veille import-mbox \
  --source /volume1/Bellegarde/import/Articles.mbox.zip \
  --database /volume1/Bellegarde/veille-scientifique/data/veille.sqlite \
  --catalog /volume1/Bellegarde/veille-scientifique/out/catalog.csv \
  --report /volume1/Bellegarde/veille-scientifique/out/import-report.json
```

Le catalogue CSV contient une ligne par référence unique avec son DOI éventuel,
son titre, son lien et la newsletter source. Le rapport JSON donne la couverture
globale et par domaine éditeur. Une relance sur la même base ignore les messages
déjà importés tout en régénérant le catalogue et les statistiques de couverture.
Les quatre chemins `source`, `database`, `catalog` et `report` doivent être
distincts ; la commande refuse une collision avant toute écriture.

Les exports MBOX, catalogues et rapports locaux sont exclus de Git. Ils peuvent
contenir des titres, des expéditeurs ou des liens personnalisés et doivent rester
dans un partage NAS à accès restreint.

## Rattrapage

Le rattrapage réutilise le catalogue MBOX dans la base principale : les DOI, titres,
métadonnées et analyses déjà connus restent dédupliqués avec la veille quotidienne.
Il se déroule obligatoirement en deux temps. La création du plan n’instancie jamais
l’analyseur OpenAI, même si la clé est chargée dans l’environnement.

Importer d’abord l’archive dans la base de production. Cette opération locale est
idempotente et ne rend encore aucune publication livrable :

```bash
python3 -m veille import-mbox \
  --source import/Articles.mbox.zip \
  --database data/veille.sqlite \
  --catalog out/catalog.csv \
  --report out/import-report.json
```

Créer ensuite un premier plan lisible, sans enrichissement et sans IA :

```bash
python3 -m veille backfill-plan \
  --database data/veille.sqlite \
  --output out/rattrapage-plan.json \
  --sample-output out/rattrapage-sample.csv \
  --sample-size 100 \
  --profile standard \
  --format human
```

Pour une estimation fondée sur les abstracts, enrichir sans IA par lots. Seuls
les candidats du profil choisi sont contactés. La commande peut être relancée : le
cache évite les appels déjà réussis et aucun appel OpenAI n’est effectué. Le CSV
répartit l’échantillon sur toute la liste pour permettre un contrôle humain du
bruit. Attendre que le rapport affiche `Prêt pour l’IA  oui` :

```bash
python3 -m veille backfill-plan \
  --config veille-scientifique.ini \
  --database data/veille.sqlite \
  --output out/rattrapage-plan.json \
  --sample-output out/rattrapage-sample.csv \
  --sample-size 100 \
  --profile standard \
  --enrichment-limit 100 \
  --format human
```

Lors de la première exécution après ajout d’une clé Elsevier, les anciens liens
ScienceDirect restés en cache avec le statut `not_found` sont repris par PII. Le
plafond `--enrichment-limit` s’applique aussi à cette reprise ; régénérer le plan
jusqu’à ce que `Enrichissements en attente` atteigne zéro. Un PII confirmé absent
de l’API est mémorisé et ne sera pas sollicité à chaque passage.

Sur le NAS, `scripts/run-backfill.sh` charge automatiquement `secrets.env`. Pour
lancer directement `python3 -m veille backfill-plan` dans un terminal, exporter au
préalable les variables de ce fichier dans la session ; ne jamais coller une clé
dans la ligne de commande ou dans l’INI.

Le plan compare une consommation attendue, prudente et maximale. Les tarifs figés
pour `gpt-5.6-luna` sont datés dans le plan : 0,20 $ par million de tokens d’entrée,
0,25 $ comme plafond d’entrée incluant une éventuelle écriture de cache, et 1,20 $
par million de tokens de sortie. Si la table de prix du programme change, un ancien
plan est refusé.

Une fois le plan contrôlé, autoriser explicitement un budget total pour toute la
campagne. Ce plafond est cumulatif entre les digests ; la consommation enregistrée
dans SQLite est déduite avant chaque nouvel appel :

```bash
python3 -m veille backfill-run \
  --config veille-scientifique.ini \
  --database data/veille.sqlite \
  --plan out/rattrapage-plan.json \
  --output out/rattrapage.html \
  --budget-usd 1.00 \
  --article-limit 15
```

Le mail porte le préfixe `Rattrapage`. Après chaque digest, régénérer le plan pour
le lot restant. `--no-send` est réservé à une base de recette : comme pour `daily`,
les références traitées y sont marquées livrées.

### Automatiser le rattrapage sur le NAS

Le wizard installe aussi `scripts/run-backfill.sh` et prépare
`DSM_BACKFILL_TASK_COMMAND.txt`. Cette tâche doit rester distincte de la veille
quotidienne. Avec la configuration installée par défaut, elle enrichit jusqu’à 100
publications par passage et actualise le plan, sans IA et sans envoi :

```ini
[backfill]
enabled = false
plan = /volume1/Bellegarde/veille-scientifique/out/rattrapage-plan.json
output = /volume1/Bellegarde/veille-scientifique/out/rattrapage.html
sample = /volume1/Bellegarde/veille-scientifique/out/rattrapage-sample.csv
sample_size = 100
profile = standard
enrichment_limit = 100
article_limit = 15
budget_usd = 0
```

Après lecture du plan, renseigner le plafond total dans `budget_usd`, puis passer
`enabled` à `true`. Le commutateur global `[ai] enabled` doit lui aussi rester à
`true` ; mettre l’un des deux à `false` suspend les appels. Chaque déclenchement
produit au plus `article_limit` analyses ;
la tâche s’arrête avant tout appel qui pourrait dépasser le budget cumulé. La
remettre à `false` suspend immédiatement les appels IA suivants sans perdre l’état.

Avant chaque requête, l’application réserve dans SQLite son coût maximal. Une
réponse interrompue conserve cette réservation par prudence, mais les autres
articles continuent à être traités. Si le tableau d’usage OpenAI confirme que
l’appel interrompu n’a pas été facturé, la réservation peut être libérée de façon
explicite puis l’article repris :

```bash
python3 -m veille backfill-release-reservation \
  --database data/veille.sqlite \
  --reservation-id 123 \
  --confirm-unbilled
```

Ne lancer cette commande qu’après vérification de l’usage côté OpenAI : elle rend
le montant réservé au budget de campagne et autorise une nouvelle tentative.

L’inventaire des 1 358 newsletters, des plateformes et des 68 titres observés est
disponible dans [`docs/newsletter-inventory.md`](docs/newsletter-inventory.md).

## Tester la boîte mail

Copier `veille-scientifique.ini.example` vers `veille-scientifique.ini`, renseigner
les identifiants non secrets, définir le mot de passe dans l’environnement puis
limiter la lecture de l’INI au propriétaire :

```bash
chmod 600 veille-scientifique.ini
export SCIENCE_DIGEST_MAIL_PASSWORD='...'
python3 -m veille test-imap --config veille-scientifique.ini
python3 -m veille test-smtp --config veille-scientifique.ini
python3 -m veille test-smtp --config veille-scientifique.ini --send-test
```

`test-imap` ouvre le dossier configuré en lecture seule et renvoie son nombre de
messages. `test-smtp` vérifie l’authentification sans envoyer de courriel ; l’option
`--send-test` envoie un unique message au destinataire de contrôle. Les résultats
sont affichés en JSON sans identifiant secret.

Le destinataire réel `[digest].recipient` doit être différent de
`[smtp].test_recipient`. Si le serveur change la valeur `UIDVALIDITY` du dossier,
la synchronisation s’arrête explicitement au lieu de traiter la situation comme une
première installation ; l’exploitant peut alors contrôler et reconstruire le
curseur sans perte silencieuse.

Si la section `[smtp]` est absente, l’application réutilise l’hôte et les
identifiants IMAP avec le port 587 et STARTTLS. La vérification TLS reste toujours
active. Sur un système dont Python ne trouve pas les certificats racine, définir
`SSL_CERT_FILE` vers le bundle CA valide installé sur la machine.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Les tests automatisés utilisent uniquement des messages synthétiques. Les résultats
agrégés de la validation sur les newsletters réelles sont consignés dans
[`VALIDATION.md`](VALIDATION.md) ; les courriels eux-mêmes restent locaux et sont
exclus de Git.

## Installation sur un DS218

### Assistant interactif recommandé

Lorsque le dépôt est public, télécharger et lancer directement l’assistant depuis
la session SSH du NAS :

```bash
curl -fsSL \
  https://raw.githubusercontent.com/DimitriNaczaj/veille-scientifique/main/scripts/install-nas.sh \
  -o /tmp/install-veille-nas.sh

bash /tmp/install-veille-nas.sh
```

L’assistant essaie toujours le téléchargement public en premier et ne demande donc
aucun jeton dans ce cas. Si le dépôt redevient privé, créer un jeton GitHub
*fine-grained* limité au dépôt `veille-scientifique`, avec la seule permission de
dépôt **Contents: Read-only**, puis utiliser le démarrage authentifié :

```bash
umask 077
read -rsp "Jeton GitHub : " GITHUB_TOKEN
echo

if printf 'header = "Authorization: Bearer %s"\n' "$GITHUB_TOKEN" | \
  curl --config - \
      --fail --location --silent --show-error \
      --header "Accept: application/vnd.github.raw+json" \
      --header "X-GitHub-Api-Version: 2022-11-28" \
      "https://api.github.com/repos/DimitriNaczaj/veille-scientifique/contents/scripts/install-nas.sh?ref=main" \
      --output /tmp/install-veille-nas.sh; then
  GITHUB_TOKEN="$GITHUB_TOKEN" bash /tmp/install-veille-nas.sh
  INSTALL_STATUS=$?
else
  INSTALL_STATUS=$?
fi
unset GITHUB_TOKEN
test "$INSTALL_STATUS" -eq 0
```

L’assistant détecte Python 3.9, télécharge le projet, crée les dossiers, demande le
mot de passe sans l’afficher, l’isole dans `secrets.env` en mode `600`, exécute les
tests, vérifie IMAP/SMTP et lance une recette `--no-ai --no-send` dans une base
séparée. L’INI ne contient alors que le nom de la variable d’environnement. Il ne
crée et n’active aucune tâche planifiée. Une relance réutilise le dossier et peut
conserver la configuration privée existante. En mode privé, le jeton GitHub n’est
écrit dans aucun fichier et est supprimé de l’environnement du wizard dès la fin
du téléchargement. Le même jeton peut servir aux mises à jour suivantes jusqu’à
son expiration ; il suffit ensuite d’en créer un nouveau avec les mêmes droits.

### Installation manuelle

1. Installer le paquet Python 3 depuis le Centre de paquets Synology.
2. Copier ce dossier dans un partage, par exemple `/volume1/Bellegarde/veille-scientifique`.
3. Créer les dossiers `inbox`, `data`, `out` et éventuellement `import` s’ils n’existent pas.
4. Copier l’exemple vers `veille-scientifique.ini`, renseigner les adresses et passer le fichier en mode `600`.
5. Créer `secrets.env` avec la procédure de saisie masquée ci-dessous, puis le passer en mode `600` ; il est exclu de Git.
6. Dans **Panneau de configuration → Planificateur de tâches**, créer une tâche quotidienne exécutée par un utilisateur dédié.
7. Utiliser le lanceur fourni avec des chemins absolus :

```bash
VEILLE_ROOT=/volume1/Bellegarde/veille-scientifique \
/volume1/Bellegarde/veille-scientifique/scripts/run-daily.sh
```

Le lanceur détecte `python3.9` ou `python3` dans le `PATH`, puis les emplacements
usuels des paquets Synology. Si nécessaire, définir explicitement `PYTHON_BIN`
avec le chemin absolu indiqué par le Centre de paquets.
Il affiche par défaut un rapport synthétique en français, adapté à une lecture
SSH ou au journal du Planificateur DSM. Le rapport JSON brut reste disponible :

```bash
VEILLE_REPORT_FORMAT=json bash scripts/run-daily.sh
```

Si Python ne trouve pas les certificats système, définir `SSL_CERT_FILE` avec le
chemin du bundle CA installé sur le NAS ; ne jamais désactiver la vérification TLS.
Aucune tâche DSM ne doit être activée avant un passage réussi avec `--no-send`, puis
un envoi test SMTP. La base de production doit être sauvegardée avec le partage.

### Protection des secrets sur le NAS

Les mots de passe et clés API ne peuvent pas être stockés sous forme de hash :
contrairement à une application qui vérifie un mot de passe utilisateur, le client
IMAP/SMTP et l’API OpenAI doivent retrouver la valeur originale pour
s’authentifier. Le compromis autonome retenu consiste à les sortir de l’INI et de
Git, à les placer dans `secrets.env` lisible uniquement par le compte d’exécution
(`chmod 600`) et à les injecter au processus au lancement. Un chiffrement
nécessiterait une clé de déchiffrement disponible automatiquement sur le NAS et
déplacerait donc le secret sans supprimer ce point de confiance.

Pour migrer atomiquement une ancienne installation dont les mots de passe IMAP et,
le cas échéant, SMTP figurent encore dans l’INI :

```bash
python3 -m veille migrate-secrets \
  --config veille-scientifique.ini \
  --secrets secrets.env
```

Pour créer le fichier manuellement sans inscrire les secrets dans l’historique du
terminal, utiliser Bash et des saisies masquées ; `%q` protège les caractères
spéciaux avant que le lanceur ne source le fichier :

```bash
umask 077
read -rsp "Mot de passe mail : " MAIL_PASSWORD; printf '\n'
printf 'SCIENCE_DIGEST_MAIL_PASSWORD=%q\n' "$MAIL_PASSWORD" > secrets.env
unset MAIL_PASSWORD
chmod 600 secrets.env
```

Les clés OpenAI et Elsevier doivent être enregistrées avec leurs commandes dédiées.
Elles remplacent toute ancienne valeur, refusent les collages multilignes et ne
s’affichent jamais :

```bash
python3 -m veille set-openai-key --secrets secrets.env
python3 -m veille set-elsevier-key --secrets secrets.env
```

La clé Elsevier est distincte de la clé OpenAI et sert uniquement à récupérer les
métadonnées et abstracts des liens ScienceDirect par leur PII. La configuration ne
contient que `api_key_env = ELSEVIER_API_KEY` ; la valeur reste dans
`secrets.env`, protégé en mode `600`. Elle se demande sur le
[portail développeur Elsevier](https://dev.elsevier.com/apikey/create). Les droits,
quotas et éventuels coûts dépendent de l’usage et des abonnements ; une organisation
commerciale doit vérifier sa licence auprès d’Elsevier avant la mise en production.

Si le serveur SMTP utilise un compte ou un mot de passe distinct, ajouter
`username` et `password_env = SCIENCE_DIGEST_SMTP_PASSWORD` dans `[smtp]`, puis
ajouter ce secret avec la même méthode :

```bash
read -rsp "Mot de passe SMTP : " SMTP_PASSWORD; printf '\n'
printf 'SCIENCE_DIGEST_SMTP_PASSWORD=%q\n' "$SMTP_PASSWORD" >> secrets.env
unset SMTP_PASSWORD
chmod 600 secrets.env
```

## Prochains incréments

1. évaluation manuelle des faux positifs et faux négatifs sur un échantillon annoté ;
2. retours « utile / inutile » dans le digest ;
3. export automatique vers Zotero ;
4. tableau de bord facultatif de supervision.

## Reprise des résumés manquants

Les publications déjà enrichies sans résumé ne sont pas resélectionnées
automatiquement. Après l’ajout d’une source de résumés, les reprendre par
lots :

```
bash /volume1/Bellegarde/veille-scientifique/scripts/run-refresh.sh
```

Le script charge les secrets, sauvegarde la base au préalable et traite
200 entrées. Pour un autre volume : `REFRESH_LIMIT=500 bash .../run-refresh.sh`.

La commande n’écrit que les entrées pour lesquelles un résumé a été trouvé.
Relancer jusqu’à ce que « Restant sans résumé » cesse de diminuer.
