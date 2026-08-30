from dataclasses import replace
from pathlib import Path

from .digest import write_digest
from .mail_parser import parse_message
from .models import PublicationPriority, RunReport
from .publisher_pages import pii_from_sciencedirect_url
from .storage import Store


MAX_ENRICHMENT_LIMIT = 1000
MAX_AI_LIMIT = 1000


def _apply_ai_analysis(publication, analysis):
    priority = analysis.priority
    if not analysis.relevant:
        priority = PublicationPriority.EXCLUDED
    return replace(
        publication,
        priority=priority,
        summary_fr=analysis.summary_fr,
        bellegarde_value=analysis.bellegarde_value,
        applications=analysis.applications,
        themes=analysis.themes,
    )


def run_pipeline(
    inbox,
    database,
    output,
    metadata_provider=None,
    relevance_filter=None,
    enrichment_limit=100,
    deliver_unenriched=False,
    analysis_provider=None,
    ai_limit=30,
    delivery_handler=None,
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
    if (
        isinstance(ai_limit, bool)
        or not isinstance(ai_limit, int)
        or ai_limit < 0
        or ai_limit > MAX_AI_LIMIT
    ):
        raise ValueError(
            "La limite IA doit être comprise entre 0 et {}.".format(MAX_AI_LIMIT)
        )
    inbox_path = Path(inbox)
    if not inbox_path.exists() or not inbox_path.is_dir():
        raise ValueError("Le dossier d’entrée n’existe pas : {}".format(inbox_path))

    messages_processed = 0
    messages_skipped = 0
    publications_detected = 0
    publications_new = 0
    publications_enriched = 0
    publications_ai_analyzed = 0
    ai_input_tokens = 0
    ai_output_tokens = 0
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
            for identity, doi, url, title in store.publications_to_enrich(
                enrichment_limit
            ):
                reference = doi or url
                try:
                    if doi is not None:
                        cached = store.load_metadata(identity)
                        cached_status = store.metadata_status(identity)
                        if hasattr(metadata_provider, "fetch_publisher_fallback"):
                            primary = (
                                None
                                if cached_status == "crossref_not_found"
                                else cached
                            )
                            if primary is None and cached_status != "crossref_not_found":
                                primary = metadata_provider.fetch_primary_by_doi(doi)
                                if primary is None:
                                    store.save_metadata_not_found(
                                        identity,
                                        status="crossref_not_found",
                                    )
                                elif not primary.abstract:
                                    store.save_metadata(
                                        identity,
                                        primary,
                                        status="crossref_incomplete",
                                    )
                            if primary is not None and primary.abstract:
                                metadata = (
                                    metadata_provider.fetch_by_known_title(
                                        title, primary
                                    )
                                    if url
                                    and pii_from_sciencedirect_url(url) is not None
                                    else primary
                                )
                            else:
                                metadata = metadata_provider.fetch_publisher_fallback(
                                    doi,
                                    primary,
                                    source_url=url,
                                    title=title,
                                )
                        else:
                            metadata = metadata_provider.fetch_by_doi(doi)
                    elif hasattr(metadata_provider, "fetch_by_url"):
                        if hasattr(metadata_provider, "fetch_by_known_title"):
                            metadata = metadata_provider.fetch_by_url(
                                url, title=title
                            )
                        else:
                            metadata = metadata_provider.fetch_by_url(url)
                    else:
                        continue
                    if metadata is None:
                        store.save_metadata_not_found(identity)
                    else:
                        store.save_metadata(identity, metadata)
                        publications_enriched += 1
                    consecutive_enrichment_errors = 0
                except Exception as error:
                    warnings.append("{}: {}".format(reference, error))
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
            assessed = pending_publications
        else:
            assessed = tuple(
                relevance_filter.assess(publication)
                for publication in pending_publications
            )

        if analysis_provider is None:
            handled_publications = assessed
            selected_publications = tuple(
                publication
                for publication in assessed
                if publication.priority is not PublicationPriority.EXCLUDED
            )
        else:
            handled = []
            selected = []
            for publication in assessed:
                if publication.priority is PublicationPriority.EXCLUDED:
                    handled.append(publication)
                    continue
                analysis = store.load_ai_assessment(
                    publication.identity,
                    analysis_provider.model,
                    analysis_provider.prompt_version,
                )
                if analysis is None:
                    if publications_ai_analyzed >= ai_limit:
                        continue
                    try:
                        analysis = analysis_provider.analyze(publication)
                        store.save_ai_assessment(publication.identity, analysis)
                        publications_ai_analyzed += 1
                        ai_input_tokens += analysis.input_tokens
                        ai_output_tokens += analysis.output_tokens
                    except Exception as error:
                        warnings.append(
                            "Analyse IA {}: {}".format(publication.identity, error)
                        )
                        continue
                analyzed = _apply_ai_analysis(publication, analysis)
                handled.append(analyzed)
                if analyzed.priority is not PublicationPriority.EXCLUDED:
                    selected.append(analyzed)
            handled_publications = tuple(handled)
            selected_publications = tuple(selected)

        publications_excluded = len(handled_publications) - len(selected_publications)

        write_digest(
            output,
            selected_publications,
            total_count=len(handled_publications),
            excluded_count=publications_excluded,
        )
        if delivery_handler is not None:
            delivery_handler.send(output, selected_publications)
        store.mark_delivered(handled_publications)
        publications_pending = store.pending_count()
    finally:
        store.close()

    return RunReport(
        messages_processed=messages_processed,
        messages_skipped=messages_skipped,
        publications_detected=publications_detected,
        publications_new=publications_new,
        publications_delivered=len(handled_publications),
        publications_enriched=publications_enriched,
        publications_ai_analyzed=publications_ai_analyzed,
        publications_relevant=len(selected_publications),
        publications_excluded=publications_excluded,
        publications_pending=publications_pending,
        ai_input_tokens=ai_input_tokens,
        ai_output_tokens=ai_output_tokens,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )
