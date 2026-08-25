# Veille scientifique Bellegarde

Application de veille scientifique autonome et légère pour Synology DS218.

## Fonctionnalités actuelles

- lecture de newsletters `.eml` ;
- import ponctuel d’historiques MBOX ou MBOX.ZIP ;
- synchronisation IMAP incrémentale du dossier `Articles` par UID, en lecture seule ;
- extraction des DOI depuis le texte et les liens HTML ;
- découverte des articles sans DOI depuis les titres et liens de suivi des éditeurs pris en charge ;
- enrichissement par Crossref puis par métadonnées HTML/JSON-LD des pages éditeurs ;
- cache Crossref persistant et reprise après panne ;
- préfiltrage explicable en sciences comportementales ;
- classement en « Priorité élevée » et « À surveiller » ;
- second tri et résumés français structurés via l’API OpenAI, lorsque configurée ;
- déduplication persistante avec SQLite ;
- génération d’un digest HTML avec alternative texte et envoi SMTP ;
- diagnostic IMAP en lecture seule et diagnostic SMTP avec envoi test optionnel ;
- relance idempotente ;
- séparation stricte entre le catalogue historique et la file quotidienne livrable ;
- aucune dépendance Python externe.

Une référence sans DOI est conservée provisoirement à partir de son titre normalisé.
Crossref ne contient pas un abstract pour chaque DOI : le digest affiche uniquement
les métadonnées réellement disponibles et signale les références encore provisoires.
L’application ne télécharge pas les PDF et ne contourne aucun paywall.

Les évolutions envisagées pour la version 2 sont suivies dans
[`TODO.md`](TODO.md).

## Exécution quotidienne

Après avoir adapté `veille-scientifique.ini.example` et chargé les secrets dans
l’environnement, une seule commande réalise le parcours complet :

```bash
SCIENCE_DIGEST_MAIL_PASSWORD=... OPENAI_API_KEY=... python3 -m veille daily \
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

Depuis une session SSH ouverte sur le NAS, télécharger puis lancer l’assistant :

```bash
curl -fsSL \
  https://raw.githubusercontent.com/DimitriNaczaj/veille-scientifique/main/scripts/install-nas.sh \
  -o /tmp/install-veille-nas.sh
bash /tmp/install-veille-nas.sh
```

L’assistant détecte Python 3.9, télécharge le projet, crée les dossiers, demande le
mot de passe sans l’afficher, l’isole dans `secrets.env` en mode `600`, exécute les
tests, vérifie IMAP/SMTP et lance une recette `--no-ai --no-send` dans une base
séparée. L’INI ne contient alors que le nom de la variable d’environnement. Il ne
crée et n’active aucune tâche planifiée. Une relance réutilise le dossier et peut
conserver la configuration privée existante.

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

La clé OpenAI doit être enregistrée avec la commande dédiée. Elle remplace toute
ancienne valeur, refuse les collages multilignes et n’affiche jamais la clé :

```bash
python3 -m veille set-openai-key --secrets secrets.env
```

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
