# Veille scientifique Bellegarde

Application de veille scientifique autonome et légère pour Synology DS218.

## Fonctionnalités actuelles

- lecture de newsletters `.eml` ;
- extraction des DOI depuis le texte et les liens HTML ;
- découverte des articles sans DOI depuis les titres et liens de suivi des éditeurs pris en charge ;
- enrichissement des DOI avec les métadonnées et abstracts disponibles dans Crossref ;
- cache Crossref persistant et reprise après panne ;
- préfiltrage explicable en sciences comportementales ;
- classement en « Priorité élevée » et « À surveiller » ;
- déduplication persistante avec SQLite ;
- génération d’un digest HTML ;
- relance idempotente ;
- aucune dépendance Python externe.

Une référence sans DOI est conservée provisoirement à partir de son titre normalisé.
Crossref ne contient pas un abstract pour chaque DOI : le digest affiche uniquement
les métadonnées réellement disponibles et signale les références encore provisoires.

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

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Les tests automatisés utilisent uniquement des messages synthétiques. Les résultats
agrégés de la validation sur les newsletters réelles sont consignés dans
[`VALIDATION.md`](VALIDATION.md) ; les courriels eux-mêmes restent locaux et sont
exclus de Git.

## Installation sur un DS218

1. Installer le paquet Python 3 depuis le Centre de paquets Synology.
2. Copier ce dossier dans un partage, par exemple `/volume1/Bellegarde/veille-scientifique`.
3. Créer les dossiers `inbox`, `data` et `out` s’ils n’existent pas.
4. Dans **Panneau de configuration → Planificateur de tâches**, créer une tâche planifiée exécutée par un utilisateur dédié.
5. Utiliser une commande avec des chemins absolus :

```bash
cd /volume1/Bellegarde/veille-scientifique && \
CROSSREF_EMAIL=veille@votre-domaine.fr \
/var/packages/py3k/target/usr/local/bin/python3 -m veille run \
  --inbox /volume1/Bellegarde/veille-scientifique/inbox \
  --database /volume1/Bellegarde/veille-scientifique/data/veille.sqlite \
  --output /volume1/Bellegarde/veille-scientifique/out/digest.html
```

Le chemin exact de Python doit être vérifié sur le NAS après installation du paquet.
Si Python ne trouve pas les certificats système, définir `SSL_CERT_FILE` avec le
chemin du bundle CA installé sur le NAS ; ne jamais désactiver la vérification TLS.
Aucune tâche DSM ne doit être créée avant ces vérifications.

## Prochains incréments

1. récupération des abstracts absents de Crossref depuis les pages éditeurs ;
2. collecte IMAP en lecture seule ;
3. second filtre et résumés structurés par IA ;
4. newsletter HTML Bellegarde et envoi SMTP ;
5. retours « utile / inutile » et intégration Zotero.
