# Veille scientifique Bellegarde

Premier incrément d’une application de veille scientifique autonome et légère pour Synology DS218.

## Fonctionnalités actuelles

- lecture de newsletters `.eml` ;
- extraction des DOI depuis le texte et les liens HTML ;
- découverte des articles sans DOI depuis les titres et liens de suivi des éditeurs pris en charge ;
- déduplication persistante avec SQLite ;
- génération d’un digest HTML ;
- relance idempotente ;
- aucune dépendance Python externe.

Une référence sans DOI est conservée provisoirement à partir de son titre normalisé.
L’enrichissement futur remplacera ces informations par les métadonnées canoniques de
l’éditeur ou de Crossref.

## Exécution locale

```bash
python3 -m veille run \
  --inbox ./inbox \
  --database ./data/veille.sqlite \
  --output ./out/digest.html
```

Le programme affiche un rapport JSON exploitable par un script ou le Planificateur de tâches DSM.

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
/var/packages/py3k/target/usr/local/bin/python3 -m veille run \
  --inbox /volume1/Bellegarde/veille-scientifique/inbox \
  --database /volume1/Bellegarde/veille-scientifique/data/veille.sqlite \
  --output /volume1/Bellegarde/veille-scientifique/out/digest.html
```

Le chemin exact de Python doit être vérifié sur le NAS après installation du paquet. Aucune tâche DSM ne doit être créée avant cette vérification.

## Prochains incréments

1. collecte IMAP en lecture seule ;
2. enrichissement Crossref et récupération des abstracts ;
3. filtrage à deux étages et résumés structurés ;
4. newsletter HTML Bellegarde et envoi SMTP ;
5. retours « utile / inutile » et intégration Zotero.
