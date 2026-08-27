"""Reprise explicite des métadonnées enrichies sans résumé.

Les publications déjà pourvues d’une ligne de métadonnées sont exclues de la
sélection automatique. Quand une nouvelle source de résumés apparaît, elles
restent donc figées sur leur ancien résultat. Ce module les réinterroge, à la
demande et par lots bornés.
"""
from configparser import ConfigParser

from .crossref import CrossrefClient
from .elsevier import elsevier_client_from_config
from .europepmc import europepmc_client_from_config
from .openalex import openalex_client_from_config
from .publisher_pages import MetadataCascade, PublisherPageClient
from .storage import Store


def _load_config(path):
    config = ConfigParser()
    with open(path, encoding="utf-8") as handle:
        config.read_file(handle)
    return config


def refresh_missing_abstracts(database, config_path, limit=100, http_opener=None):
    if limit < 0 or limit > 1000:
        raise ValueError("La limite de reprise doit être comprise entre 0 et 1 000.")
    config = _load_config(config_path)
    contact_email = config.get("app", "crossref_email", fallback="").strip()
    if not contact_email:
        contact_email = config.get("imap", "username", fallback="").strip() or None

    elsevier_client = elsevier_client_from_config(config, opener=http_opener)
    provider = MetadataCascade(
        CrossrefClient(contact_email=contact_email, opener=http_opener),
        PublisherPageClient(opener=http_opener),
        elsevier_client=elsevier_client,
        openalex_client=openalex_client_from_config(config, opener=http_opener),
        europepmc_client=europepmc_client_from_config(config, opener=http_opener),
    )

    store = Store(database)
    warnings = []
    recovered = attempted = 0
    consecutive_failures = 0
    try:
        pending = store.metadata_without_abstract_count()
        for identity, doi, url in store.metadata_without_abstract(limit):
            attempted += 1
            reference = doi or url
            try:
                metadata = (
                    provider.fetch_by_doi(doi, source_url=url)
                    if doi
                    else provider.fetch_by_url(url)
                )
            except Exception as error:
                consecutive_failures += 1
                warnings.append("{} : {}".format(reference, error))
                # L’entrée passe en fin de file même en cas d’échec, sinon le
                # lot suivant rejouerait exactement les mêmes entrées.
                store.touch_metadata(identity)
                if consecutive_failures >= 3:
                    warnings.append(
                        "Reprise interrompue après trois erreurs consécutives "
                        "du service."
                    )
                    break
                continue
            consecutive_failures = 0
            if metadata is None or not metadata.abstract:
                store.touch_metadata(identity)
                continue
            store.save_metadata(identity, metadata)
            recovered += 1
    finally:
        store.close()

    if elsevier_client is not None and elsevier_client.entitlement_notice:
        warnings.append(elsevier_client.entitlement_notice)
    for name, count in sorted(provider.source_failures.items()):
        warnings.append(
            "{} : {} échec(s) ; reprise poursuivie sans cette source.".format(
                name, count
            )
        )
    return {
        "pending_before": pending,
        "attempted": attempted,
        "recovered": recovered,
        "remaining": max(pending - recovered, 0),
        "warnings": warnings,
    }
