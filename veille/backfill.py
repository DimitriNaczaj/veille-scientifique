import csv
import hashlib
import json
import math
import os
from dataclasses import replace
from datetime import date
from pathlib import Path

from .ai import INSTRUCTIONS
from .ai import OpenAIAnalyzer
from .atomic import atomic_open
from .crossref import CrossrefClient
from .delivery import SMTPDigestSender
from .digest import write_digest
from .elsevier import elsevier_client_from_config, pii_from_sciencedirect_url
from .europepmc import europepmc_client_from_config
from .openalex import openalex_client_from_config
from .filtering import BehavioralScienceFilter
from .mail_diagnostics import _load_config
from .mbox_import import _validate_distinct_paths
from .models import PublicationPriority
from .publisher_pages import MetadataCascade, PublisherPageClient
from .storage import Store


MODEL_PRICING = {
    "gpt-5.6-luna": {
        "input": 0.20,
        "input_upper_bound": 0.25,
        "output": 1.20,
        "source": "OpenAI",
        "checked_at": "2026-07-30",
    }
}
PROFILE_MINIMUM_SCORES = {"strict": 5, "standard": 2, "large": 1}
SAMPLE_FIELDS = (
    "identity",
    "doi",
    "title",
    "source_sender",
    "relevance_score",
    "relevance_reasons",
)


def _estimated_document(publication):
    return json.dumps(
        {
            "title": publication.title,
            "abstract": (publication.abstract or "")[:12000],
            "journal": publication.journal,
            "published_date": publication.published_date,
            "authors": list(publication.authors[:20]),
            "doi": publication.doi,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _tokens(characters, characters_per_token):
    return int(math.ceil(characters / characters_per_token))


def _cost(input_tokens, output_tokens, pricing, upper_bound=False):
    input_rate = (
        pricing["input_upper_bound"] if upper_bound else pricing["input"]
    )
    value = (
        input_tokens * input_rate + output_tokens * pricing["output"]
    ) / 1_000_000
    return round(value, 6)


def _usage(candidates, pricing, conservative=False):
    characters_per_token = 3 if conservative else 4
    output_per_publication = 400 if conservative else 250
    instruction_characters = len(INSTRUCTIONS)
    input_tokens = sum(
        _tokens(
            instruction_characters + len(_estimated_document(publication)),
            characters_per_token,
        )
        for publication in candidates
    )
    output_tokens = len(candidates) * output_per_publication
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cost_usd": _cost(input_tokens, output_tokens, pricing),
    }


def _plan_id(payload):
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _candidate_sample(candidates, size):
    if size < 1 or size > 1000:
        raise ValueError(
            "La taille de l’échantillon doit être comprise entre 1 et 1 000."
        )
    count = min(size, len(candidates))
    if count == 0:
        return ()
    return tuple(
        candidates[(index * len(candidates)) // count]
        for index in range(count)
    )


def _write_candidate_sample(path, candidates):
    with atomic_open(path, "w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=SAMPLE_FIELDS)
        writer.writeheader()
        for publication in candidates:
            writer.writerow(
                {
                    "identity": publication.identity,
                    "doi": publication.doi or "",
                    "title": publication.title or "",
                    "source_sender": publication.source_sender,
                    "relevance_score": publication.relevance_score,
                    "relevance_reasons": " | ".join(
                        publication.relevance_reasons
                    ),
                }
            )
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_plan(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("Le plan de rattrapage est illisible.") from None
    supplied_id = payload.pop("plan_id", None)
    if not supplied_id or supplied_id != _plan_id(payload):
        raise ValueError("Le plan de rattrapage a été modifié ou est invalide.")
    payload["plan_id"] = supplied_id
    sample_output = payload.get("sample_output")
    sample_sha256 = payload.get("sample_sha256")
    if sample_output or sample_sha256:
        try:
            actual_sample_sha256 = hashlib.sha256(
                Path(sample_output).read_bytes()
            ).hexdigest()
        except (OSError, TypeError):
            raise ValueError(
                "L’échantillon CSV associé au plan est absent ou illisible."
            ) from None
        if not sample_sha256 or actual_sample_sha256 != sample_sha256:
            raise ValueError(
                "L’échantillon CSV ne correspond plus au plan ; "
                "générez un nouveau plan avant tout appel IA."
            )
    return payload


def _maximum_call_cost(publication, pricing):
    request_overhead_bytes = 3000
    input_tokens = (
        len(INSTRUCTIONS.encode("utf-8"))
        + len(_estimated_document(publication).encode("utf-8"))
        + request_overhead_bytes
    )
    return _cost(input_tokens, 1200, pricing, upper_bound=True)


def _maximum_usage(candidates, pricing):
    input_tokens = sum(
        len(INSTRUCTIONS.encode("utf-8"))
        + len(_estimated_document(publication).encode("utf-8"))
        + 3000
        for publication in candidates
    )
    output_tokens = len(candidates) * 1200
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cost_usd": _cost(input_tokens, output_tokens, pricing, upper_bound=True),
    }


def _analyzed_publication(publication, analysis):
    priority = analysis.priority if analysis.relevant else PublicationPriority.EXCLUDED
    return replace(
        publication,
        priority=priority,
        summary_fr=analysis.summary_fr,
        bellegarde_value=analysis.bellegarde_value,
        applications=analysis.applications,
        themes=analysis.themes,
    )


def _with_metadata(publication, metadata):
    return replace(
        publication,
        title=metadata.title or publication.title,
        abstract=metadata.abstract,
        journal=metadata.journal,
        published_date=metadata.published_date,
        authors=metadata.authors,
        url=metadata.url or publication.url,
        metadata_status="success",
    )


def _should_retry_legacy_elsevier(publication, cached_status, enabled):
    return (
        enabled
        and cached_status == "not_found"
        and bool(publication.url)
        and pii_from_sciencedirect_url(publication.url) is not None
    )


def _enrich_backfill(database, config_path, limit, http_opener, candidates):
    if limit < 0 or limit > 1000:
        raise ValueError("La limite d’enrichissement doit être comprise entre 0 et 1 000.")
    if not config_path or limit == 0:
        return 0, (), {}
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
    enriched = 0
    warnings = []
    metadata_updates = {}
    consecutive_failures = 0
    attempted = 0
    try:
        for publication in candidates:
            if attempted >= limit:
                break
            if not (publication.doi or publication.url):
                continue
            cached_status = store.metadata_status(publication.identity)
            retry_legacy_elsevier = _should_retry_legacy_elsevier(
                publication,
                cached_status,
                elsevier_client is not None,
            )
            if cached_status is not None and not retry_legacy_elsevier:
                continue
            attempted += 1
            reference = publication.doi or publication.url
            try:
                metadata = (
                    provider.fetch_by_doi(
                        publication.doi,
                        source_url=publication.url,
                    )
                    if publication.doi is not None
                    else provider.fetch_by_url(publication.url)
                )
                if metadata is None:
                    status = (
                        "elsevier_not_found"
                        if elsevier_client is not None
                        and publication.url
                        and pii_from_sciencedirect_url(publication.url) is not None
                        else "not_found"
                    )
                    store.save_metadata_not_found(
                        publication.identity,
                        status=status,
                    )
                else:
                    store.save_metadata(publication.identity, metadata)
                    metadata_updates[publication.identity] = metadata
                    enriched += 1
                consecutive_failures = 0
            except Exception as error:
                consecutive_failures += 1
                warnings.append("{}: {}".format(reference, error))
                if consecutive_failures >= 3:
                    warnings.append(
                        "Enrichissement interrompu après trois erreurs "
                        "consécutives du service."
                    )
                    break
    finally:
        store.close()
    if elsevier_client is not None and elsevier_client.entitlement_notice:
        warnings.append(elsevier_client.entitlement_notice)
    for name, count in sorted(provider.source_failures.items()):
        warnings.append(
            "{} : {} échec(s) ; enrichissement poursuivi sans cette source.".format(
                name, count
            )
        )
    return enriched, tuple(warnings), metadata_updates


def build_backfill_plan(
    database,
    output,
    model="gpt-5.6-luna",
    profile="standard",
    config_path=None,
    enrichment_limit=0,
    http_opener=None,
    sample_output=None,
    sample_size=50,
):
    paths = {"base": database, "plan": output}
    installation_root = Path(database).resolve().parent.parent
    paths["secrets"] = installation_root / "secrets.env"
    paths["anciens secrets"] = installation_root / "openai.env"
    if config_path:
        paths["configuration"] = config_path
    if sample_output:
        paths["échantillon"] = sample_output
    _validate_distinct_paths(paths)
    if profile not in PROFILE_MINIMUM_SCORES:
        raise ValueError("Profil de rattrapage invalide.")
    if model not in MODEL_PRICING:
        raise ValueError(
            "Tarif inconnu pour le modèle {} ; mettez à jour la table de prix "
            "avant tout appel IA.".format(model)
        )
    store = Store(database)
    try:
        publications = store.backfill_publications()
    finally:
        store.close()

    assessor = BehavioralScienceFilter()
    comparison_assessed = tuple(
        assessor.assess(replace(publication, abstract=None))
        for publication in publications
    )
    profile_comparison = {
        name: sum(
            publication.relevance_score >= threshold
            for publication in comparison_assessed
        )
        for name, threshold in PROFILE_MINIMUM_SCORES.items()
    }
    assessed = tuple(assessor.assess(publication) for publication in publications)
    minimum_score = PROFILE_MINIMUM_SCORES[profile]
    preliminary_candidates = tuple(
        publication
        for publication in assessed
        if publication.relevance_score >= minimum_score
    )
    publications_enriched, warnings, metadata_updates = _enrich_backfill(
        database,
        config_path,
        enrichment_limit,
        http_opener,
        preliminary_candidates,
    )
    candidates = tuple(
        assessor.assess(
            _with_metadata(publication, metadata_updates[publication.identity])
            if publication.identity in metadata_updates
            else publication
        )
        for publication in preliminary_candidates
    )
    candidates = tuple(
        publication
        for publication in candidates
        if publication.relevance_score >= minimum_score
    )
    store = Store(database)
    try:
        metadata_statuses = store.backfill_metadata_statuses()
    finally:
        store.close()
    retry_legacy_elsevier = False
    if config_path:
        retry_legacy_elsevier = elsevier_client_from_config(
            _load_config(config_path),
            opener=http_opener,
        ) is not None
    enrichment_pending = sum(
        bool(publication.doi or publication.url)
        and (
            publication.identity not in metadata_statuses
            or (
                _should_retry_legacy_elsevier(
                    publication,
                    metadata_statuses.get(publication.identity),
                    retry_legacy_elsevier,
                )
            )
        )
        for publication in candidates
    )
    sample = _candidate_sample(candidates, sample_size)
    sample_sha256 = None
    if sample_output:
        sample_sha256 = _write_candidate_sample(sample_output, sample)
    pricing = MODEL_PRICING[model]
    payload = {
        "service": "backfill-plan",
        "status": "ok",
        "created_on": date.today().isoformat(),
        "ai_called": False,
        "approval_required": True,
        "model": model,
        "profile": profile,
        "minimum_local_score": minimum_score,
        "publications_available": len(publications),
        "publications_ai_candidates": len(candidates),
        "publications_locally_excluded": len(publications) - len(candidates),
        "profile_comparison": profile_comparison,
        "publications_enriched": publications_enriched,
        "enrichment_pending": enrichment_pending,
        "ready_for_ai": enrichment_pending == 0,
        "abstracts_available": sum(bool(publication.abstract) for publication in candidates),
        "pricing_usd_per_million": {
            "input": pricing["input"],
            "input_upper_bound": pricing["input_upper_bound"],
            "output": pricing["output"],
        },
        "pricing_source": pricing["source"],
        "pricing_checked_at": pricing["checked_at"],
        "expected": _usage(candidates, pricing),
        "conservative": _usage(candidates, pricing, conservative=True),
        "maximum": _maximum_usage(candidates, pricing),
        "candidate_identities": [publication.identity for publication in candidates],
        "sample_output": str(sample_output) if sample_output else None,
        "sample_size": len(sample),
        "sample_sha256": sample_sha256,
        "warnings": list(warnings),
    }
    payload["plan_id"] = _plan_id(payload)
    output_path = Path(output)
    with atomic_open(output_path, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    return payload


def run_backfill(
    config_path,
    database,
    plan_path,
    output,
    budget_usd,
    article_limit=15,
    no_send=False,
    smtp_factory=None,
    ai_opener=None,
):
    config_parent = Path(config_path).resolve().parent
    plan = _load_plan(plan_path)
    paths = {
        "configuration": config_path,
        "base": database,
        "plan": plan_path,
        "digest": output,
        "secrets": config_parent / "secrets.env",
        "anciens secrets": config_parent / "openai.env",
    }
    if plan.get("sample_output"):
        paths["échantillon"] = plan["sample_output"]
    _validate_distinct_paths(paths)
    if not math.isfinite(budget_usd) or budget_usd <= 0:
        raise ValueError("Le budget de rattrapage doit être strictement positif.")
    if article_limit < 1 or article_limit > 100:
        raise ValueError("La limite d’articles doit être comprise entre 1 et 100.")
    model = plan.get("model")
    profile = plan.get("profile")
    if model not in MODEL_PRICING or profile not in PROFILE_MINIMUM_SCORES:
        raise ValueError("Le modèle ou le profil du plan n’est plus pris en charge.")
    pricing = MODEL_PRICING[model]
    if plan.get("pricing_usd_per_million") != {
        "input": pricing["input"],
        "input_upper_bound": pricing["input_upper_bound"],
        "output": pricing["output"],
    }:
        raise ValueError("Le tarif a changé ; générez un nouveau plan avant tout appel IA.")
    if not plan.get("ready_for_ai"):
        raise ValueError(
            "Le plan n’est pas prêt : terminez l’enrichissement avant tout appel IA."
        )

    store = Store(database)
    try:
        available = store.backfill_publications()
        assessor = BehavioralScienceFilter()
        assessed = tuple(assessor.assess(publication) for publication in available)
        minimum_score = PROFILE_MINIMUM_SCORES[profile]
        candidates = tuple(
            publication
            for publication in assessed
            if publication.relevance_score >= minimum_score
        )
        excluded_locally = tuple(
            publication
            for publication in assessed
            if publication.relevance_score < minimum_score
        )
        if [publication.identity for publication in candidates] != plan.get(
            "candidate_identities"
        ):
            raise ValueError(
                "Le catalogue a changé depuis le plan ; générez un nouveau plan."
            )

        config = _load_config(config_path)
        key_environment = (
            config.get("ai", "api_key_env", fallback="OPENAI_API_KEY").strip()
            if config.has_section("ai")
            else "OPENAI_API_KEY"
        ) or "OPENAI_API_KEY"
        api_key = os.environ.get(key_environment)
        if not api_key:
            raise ValueError(
                "Variable d’environnement {} absente ou vide.".format(
                    key_environment
                )
            )
        analyzer = OpenAIAnalyzer(api_key=api_key, model=model, opener=ai_opener)
        legacy_input_tokens, legacy_output_tokens = (
            store.backfill_unreserved_ai_usage()
        )
        legacy_cost_upper_bound = _cost(
            legacy_input_tokens,
            legacy_output_tokens,
            pricing,
            upper_bound=True,
        )

        selected = []
        analyzed_publications = []
        input_tokens = 0
        output_tokens = 0
        budget_exhausted = False
        ai_called = False
        warnings = []
        for publication in candidates:
            if len(analyzed_publications) >= article_limit:
                break
            analysis = store.load_ai_assessment(
                publication.identity,
                analyzer.model,
                analyzer.prompt_version,
            )
            if analysis is None:
                reservation_id, reservation_status = store.reserve_backfill_budget(
                    publication.identity,
                    analyzer.model,
                    analyzer.prompt_version,
                    _maximum_call_cost(publication, pricing),
                    budget_usd,
                    legacy_cost_upper_bound,
                )
                if reservation_status == "existing":
                    warnings.append(
                        "La réservation IA #{} est inachevée pour {} ; "
                        "aucun nouvel appel n’a été tenté.".format(
                            reservation_id,
                            publication.identity
                        )
                    )
                    continue
                if reservation_status == "budget":
                    budget_exhausted = True
                    break
                analysis = analyzer.analyze(publication)
                store.save_ai_assessment(publication.identity, analysis)
                store.complete_backfill_budget_reservation(
                    reservation_id,
                    _cost(
                        analysis.input_tokens,
                        analysis.output_tokens,
                        pricing,
                        upper_bound=True,
                    ),
                    analysis.input_tokens,
                    analysis.output_tokens,
                )
                input_tokens += analysis.input_tokens
                output_tokens += analysis.output_tokens
                ai_called = True
            analyzed = _analyzed_publication(publication, analysis)
            analyzed_publications.append(analyzed)
            if analyzed.priority is not PublicationPriority.EXCLUDED:
                selected.append(analyzed)

        handled = tuple(excluded_locally) + tuple(analyzed_publications)
        write_digest(
            output,
            selected,
            total_count=len(handled),
            excluded_count=len(handled) - len(selected),
        )
        sender = None
        if not no_send:
            sender = SMTPDigestSender(
                config_path,
                smtp_factory=smtp_factory,
                subject_prefix="Rattrapage",
            )
            sender.send(output, selected)
        store.mark_delivered(handled)
        remaining = len(store.backfill_publications())
        (
            reserved_cost_upper_bound,
            reserved_input_tokens,
            reserved_output_tokens,
        ) = store.backfill_budget_usage()
        legacy_input_tokens, legacy_output_tokens = (
            store.backfill_unreserved_ai_usage()
        )
    finally:
        store.close()

    campaign_input_tokens = reserved_input_tokens + legacy_input_tokens
    campaign_output_tokens = reserved_output_tokens + legacy_output_tokens
    campaign_cost_upper_bound = round(
        reserved_cost_upper_bound
        + _cost(
            legacy_input_tokens,
            legacy_output_tokens,
            pricing,
            upper_bound=True,
        ),
        6,
    )
    return {
        "service": "backfill-run",
        "status": "partial" if budget_exhausted or remaining else "ok",
        "plan_id": plan["plan_id"],
        "model": model,
        "profile": profile,
        "budget_usd": budget_usd,
        "actual_cost_usd": _cost(input_tokens, output_tokens, pricing),
        "billed_cost_upper_bound_usd": _cost(
            input_tokens,
            output_tokens,
            pricing,
            upper_bound=True,
        ),
        "campaign_input_tokens": campaign_input_tokens,
        "campaign_output_tokens": campaign_output_tokens,
        "campaign_cost_upper_bound_usd": campaign_cost_upper_bound,
        "budget_remaining_usd": round(
            max(0.0, budget_usd - campaign_cost_upper_bound),
            6,
        ),
        "ai_called": ai_called,
        "budget_exhausted": budget_exhausted,
        "publications_ai_analyzed": len(analyzed_publications),
        "publications_relevant": len(selected),
        "publications_locally_excluded": len(excluded_locally),
        "publications_remaining": remaining,
        "ai_input_tokens": input_tokens,
        "ai_output_tokens": output_tokens,
        "email_sent": bool(sender and sender.sent),
        "recipient": sender.recipient if sender else None,
        "warnings": warnings,
        "errors": [],
    }


def release_backfill_reservation(database, reservation_id):
    store = Store(database)
    try:
        publication_identity = store.release_backfill_budget_reservation(
            reservation_id
        )
    finally:
        store.close()
    if publication_identity is None:
        raise ValueError(
            "Aucune réservation IA ouverte ne correspond à cet identifiant."
        )
    return {
        "service": "backfill-release-reservation",
        "status": "ok",
        "reservation_id": reservation_id,
        "publication_identity": publication_identity,
        "reservation_released": True,
        "errors": [],
    }


def _backfill_option(config, option):
    if not config.has_section("backfill"):
        raise ValueError("Section [backfill] absente de la configuration.")
    value = config.get("backfill", option, fallback="").strip()
    if not value:
        raise ValueError("Option backfill.{} absente.".format(option))
    return value


def run_backfill_daily(
    config_path,
    smtp_factory=None,
    http_opener=None,
    ai_opener=None,
):
    config = _load_config(config_path)
    if not config.has_section("app"):
        raise ValueError("Section [app] absente de la configuration.")
    database = config.get("app", "database", fallback="").strip()
    if not database:
        raise ValueError("Option app.database absente de la configuration.")
    plan_path = _backfill_option(config, "plan")
    output = _backfill_option(config, "output")
    default_sample = str(
        Path(plan_path).with_name(
            "{}-sample.csv".format(Path(plan_path).stem)
        )
    )
    sample_output = config.get(
        "backfill", "sample", fallback=default_sample
    ).strip() or default_sample
    profile = config.get("backfill", "profile", fallback="standard").strip()
    model = config.get("ai", "model", fallback="gpt-5.6-luna").strip()
    try:
        enabled = config.getboolean("backfill", "enabled", fallback=False)
        ai_enabled = config.getboolean("ai", "enabled", fallback=False)
        enrichment_limit = config.getint(
            "backfill", "enrichment_limit", fallback=100
        )
        article_limit = config.getint("backfill", "article_limit", fallback=15)
        sample_size = config.getint("backfill", "sample_size", fallback=50)
        budget_usd = config.getfloat("backfill", "budget_usd", fallback=0.0)
    except ValueError:
        raise ValueError("Une option numérique ou booléenne [backfill] est invalide.") from None

    config_parent = Path(config_path).resolve().parent
    _validate_distinct_paths(
        {
            "configuration": config_path,
            "base": database,
            "plan": plan_path,
            "digest": output,
            "échantillon": sample_output,
            "secrets": config_parent / "secrets.env",
            "anciens secrets": config_parent / "openai.env",
        }
    )

    plan = build_backfill_plan(
        database,
        plan_path,
        model=model,
        profile=profile,
        config_path=config_path,
        enrichment_limit=enrichment_limit,
        http_opener=http_opener,
        sample_output=sample_output,
        sample_size=sample_size,
    )
    if not enabled or not ai_enabled:
        return {
            "service": "backfill-daily",
            "status": "waiting_for_approval",
            "ai_called": False,
            "plan": plan,
            "errors": [],
        }
    if not plan["ready_for_ai"]:
        return {
            "service": "backfill-daily",
            "status": "preparing",
            "ai_called": False,
            "plan": plan,
            "errors": [],
        }
    execution = run_backfill(
        config_path,
        database,
        plan_path,
        output,
        budget_usd,
        article_limit=article_limit,
        smtp_factory=smtp_factory,
        ai_opener=ai_opener,
    )
    return {
        "service": "backfill-daily",
        "status": execution["status"],
        "ai_called": execution["ai_called"],
        "plan": plan,
        "execution": execution,
        "errors": execution["errors"],
    }
