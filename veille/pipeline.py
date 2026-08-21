from pathlib import Path

from .digest import write_digest
from .mail_parser import parse_message
from .models import PublicationPriority, RunReport
from .storage import Store


MAX_ENRICHMENT_LIMIT = 1000


def run_pipeline(
    inbox,
    database,
    output,
    metadata_provider=None,
    relevance_filter=None,
    enrichment_limit=100,
    deliver_unenriched=False,
):
    if (
        isinstance(enrichment_limit, bool)
        or not isinstance(enrichment_limit, int)
        or enrichment_limit < 0
        or enrichment_limit > MAX_ENRICHMENT_LIMIT
    ):
        raise ValueError(
            "La limite d’enrichissement doit être comprise entre 0 et {}.".format(
                MAX_ENRICHMENT_LIMIT
            )
        )
    inbox_path = Path(inbox)
    if not inbox_path.exists() or not inbox_path.is_dir():
        raise ValueError("Le dossier d’entrée n’existe pas : {}".format(inbox_path))

    messages_processed = 0
    messages_skipped = 0
    publications_detected = 0
    publications_new = 0
    publications_enriched = 0
    warnings = []
    errors = []

    store = Store(database)
    try:
        for message_path in sorted(inbox_path.glob("*.eml")):
            try:
                message = parse_message(message_path)
                if store.has_message(message.identity):
                    messages_skipped += 1
                    continue
                publications_detected += len(message.publications)
                publications_new += store.add_message(message, message_path)
                messages_processed += 1
            except Exception as error:
                errors.append("{}: {}".format(message_path.name, error))

        if metadata_provider is not None:
            consecutive_enrichment_errors = 0
            for identity, doi in store.publications_to_enrich(enrichment_limit):
                try:
                    metadata = metadata_provider.fetch_by_doi(doi)
                    if metadata is None:
                        store.save_metadata_not_found(identity)
                    else:
                        store.save_metadata(identity, metadata)
                        publications_enriched += 1
                    consecutive_enrichment_errors = 0
                except Exception as error:
                    warnings.append("{}: {}".format(doi, error))
                    consecutive_enrichment_errors += 1
                    if consecutive_enrichment_errors >= 3:
                        warnings.append(
                            "Enrichissement Crossref interrompu après trois échecs consécutifs."
                        )
                        break

        pending_publications = store.pending_publications(
            require_metadata=not deliver_unenriched
        )
        if relevance_filter is None:
            selected_publications = pending_publications
            publications_excluded = 0
        else:
            assessed = tuple(
                relevance_filter.assess(publication)
                for publication in pending_publications
            )
            selected_publications = tuple(
                publication
                for publication in assessed
                if publication.priority is not PublicationPriority.EXCLUDED
            )
            publications_excluded = len(assessed) - len(selected_publications)

        write_digest(
            output,
            selected_publications,
            total_count=len(pending_publications),
            excluded_count=publications_excluded,
        )
        store.mark_delivered(pending_publications)
        publications_pending = store.pending_count()
    finally:
        store.close()

    return RunReport(
        messages_processed=messages_processed,
        messages_skipped=messages_skipped,
        publications_detected=publications_detected,
        publications_new=publications_new,
        publications_delivered=len(pending_publications),
        publications_enriched=publications_enriched,
        publications_relevant=len(selected_publications),
        publications_excluded=publications_excluded,
        publications_pending=publications_pending,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )
