"""Classement unique et distribution progressive du rattrapage.

Le classement et l’envoi sont deux opérations séparées. Une publication peut
donc être analysée une seule fois, rester dans la file plusieurs jours, puis
être marquée comme distribuée uniquement après un envoi SMTP réussi.
"""
import csv
import math
import os
import sqlite3
from pathlib import Path

from .ai import OpenAIAnalyzer
from .atomic import atomic_open
from .backfill import (
    MODEL_PRICING,
    _analyzed_publication,
    _cost,
    _load_plan,
    _maximum_call_cost,
)
from .delivery import SMTPDigestSender
from .digest import write_digest
from .feedback import load_feedback_settings
from .mail_diagnostics import _load_config
from .mbox_import import _validate_distinct_paths
from .models import PublicationPriority
from .storage import Store


CLASSIFICATION_FIELDS = (
    "rank",
    "status",
    "reservation_id",
    "priority",
    "interest_score",
    "raw_interest_score",
    "mission_fit_score",
    "scientific_robustness_score",
    "actionability_score",
    "generalizability_score",
    "novelty_score",
    "classification_rules",
    "evidence_quality",
    "has_abstract",
    "classification_reason",
    "title",
    "doi",
    "url",
    "journal",
    "published_date",
    "authors",
    "summary_fr",
    "bellegarde_value",
    "applications",
    "themes",
    "model",
    "prompt_version",
)


def _ensure_classification_backup(database):
    source = Path(database)
    if not source.is_file():
        raise ValueError("Base SQLite introuvable : {}".format(source))
    target = Path(str(source) + ".pre-classification.bak")
    if target.exists():
        _verify_sqlite_backup(target)
        return target
    temporary = target.with_name(
        "{}.tmp-{}".format(target.name, os.getpid())
    )
    try:
        source_connection = sqlite3.connect(str(source))
        target_connection = sqlite3.connect(str(temporary))
        try:
            source_connection.backup(target_connection)
        finally:
            target_connection.close()
            source_connection.close()
        os.chmod(str(temporary), 0o600)
        _verify_sqlite_backup(temporary)
        os.replace(str(temporary), str(target))
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    return target


def _verify_sqlite_backup(path):
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA quick_check").fetchone()
    finally:
        connection.close()
    if result is None or result[0] != "ok":
        raise ValueError("Sauvegarde SQLite invalide : {}".format(path))


def _safe_csv_text(value):
    text = str(value or "")
    stripped = text.lstrip()
    if stripped and stripped[0] in "=+-@":
        return "'" + text
    return text


def campaign_settings(config_path):
    config = _load_config(config_path)
    if not config.has_section("app") or not config.has_section("backfill"):
        raise ValueError("Sections [app] et [backfill] requises pour le rattrapage.")
    database = config.get("app", "database", fallback="").strip()
    plan = config.get("backfill", "plan", fallback="").strip()
    output = config.get("backfill", "output", fallback="").strip()
    if not database or not plan or not output:
        raise ValueError("Chemins app.database, backfill.plan et backfill.output requis.")
    classification = config.get(
        "backfill",
        "classification",
        fallback=str(Path(plan).with_name("rattrapage-classement.csv")),
    ).strip()
    try:
        enabled = config.getboolean("backfill", "enabled", fallback=False)
        ai_enabled = config.getboolean("ai", "enabled", fallback=False)
        budget_usd = config.getfloat("backfill", "budget_usd", fallback=0.0)
        classification_batch_limit = config.getint(
            "backfill", "classification_batch_limit", fallback=0
        )
        daily_articles = config.getint(
            "backfill", "daily_articles", fallback=10
        )
    except ValueError:
        raise ValueError("Une option numérique [backfill] est invalide.") from None
    return {
        "database": database,
        "plan": plan,
        "output": output,
        "classification": classification,
        "budget_usd": budget_usd,
        "classification_batch_limit": classification_batch_limit,
        "daily_articles": daily_articles,
        "model": config.get("ai", "model", fallback="gpt-5.6-luna").strip(),
        "enabled": enabled,
        "ai_enabled": ai_enabled,
    }


def _campaign_paths(config_path, database, plan_path, classification_path, output=None):
    root = Path(config_path).resolve().parent
    paths = {
        "configuration": config_path,
        "base": database,
        "plan": plan_path,
        "classement": classification_path,
        "secrets": root / "secrets.env",
        "anciens secrets": root / "openai.env",
    }
    if output:
        paths["digest"] = output
    _validate_distinct_paths(paths)


def _validate_plan(plan, model):
    if plan.get("model") != model:
        raise ValueError(
            "Le modèle du plan ne correspond plus à la configuration ; "
            "générez un nouveau plan."
        )
    if plan.get("prompt_version") != OpenAIAnalyzer.prompt_version:
        raise ValueError(
            "La consigne IA a changé ; générez un nouveau plan avant le classement."
        )
    if not plan.get("ready_for_ai"):
        raise ValueError(
            "Le plan n’est pas prêt : terminez l’enrichissement avant le classement."
        )


def _analysis_provider(config, model, ai_opener):
    key_environment = (
        config.get("ai", "api_key_env", fallback="OPENAI_API_KEY").strip()
        if config.has_section("ai")
        else "OPENAI_API_KEY"
    ) or "OPENAI_API_KEY"
    api_key = os.environ.get(key_environment)
    if not api_key:
        raise ValueError(
            "Variable d’environnement {} absente ou vide.".format(key_environment)
        )
    return OpenAIAnalyzer(api_key=api_key, model=model, opener=ai_opener)


def _classification_rows(store, candidate_identities, model, prompt_version):
    wanted = set(candidate_identities)
    delivered = store.backfill_delivered_identities()
    publications = {
        publication.identity: publication
        for publication in store.backfill_publications(include_delivered=True)
        if publication.identity in wanted
    }
    rows = []
    for identity in candidate_identities:
        publication = publications.get(identity)
        if publication is None:
            continue
        current_analysis = store.load_ai_assessment(identity, model, prompt_version)
        reservation = store.backfill_budget_reservation(
            identity, model, prompt_version
        )
        analysis = current_analysis
        if current_analysis is None:
            if identity in delivered:
                status = "already_delivered"
            elif reservation is not None and reservation["status"] != "released":
                status = "needs_review"
            else:
                status = "unclassified"
            if identity in delivered:
                analysis = store.load_latest_ai_assessment(identity)
            priority = (
                analysis.priority
                if analysis is not None
                else PublicationPriority.UNFILTERED
            )
            interest_score = analysis.interest_score if analysis is not None else 0
            evidence_quality = (
                analysis.evidence_quality if analysis is not None else "unknown"
            )
        else:
            priority = analysis.priority
            interest_score = analysis.interest_score
            evidence_quality = analysis.evidence_quality
            if identity in delivered:
                status = "delivered"
            elif not analysis.relevant:
                status = "excluded"
            elif not publication.abstract:
                status = "withheld_without_abstract"
            else:
                status = "pending"
        rows.append(
            {
                "publication": publication,
                "analysis": analysis,
                "status": status,
                "priority": priority,
                "interest_score": interest_score,
                "evidence_quality": evidence_quality,
                "reservation_id": reservation["id"] if reservation else None,
            }
        )
    priority_order = {
        PublicationPriority.HIGH: 0,
        PublicationPriority.WATCH: 1,
        PublicationPriority.EXCLUDED: 2,
        PublicationPriority.UNFILTERED: 3,
    }
    status_order = {
        "pending": 0,
        "withheld_without_abstract": 1,
        "delivered": 2,
        "excluded": 3,
        "needs_review": 4,
        "unclassified": 5,
        "already_delivered": 6,
    }
    rows.sort(
        key=lambda row: (
            status_order[row["status"]],
            priority_order[row["priority"]],
            -row["interest_score"],
            row["publication"].published_date or "",
            row["publication"].identity,
        )
    )
    return rows


def _row_counts(rows):
    counts = {}
    for row in rows:
        status = row["status"]
        counts[status] = counts.get(status, 0) + 1
    return counts


def _write_classification(path, rows, model, prompt_version):
    with atomic_open(path, "w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CLASSIFICATION_FIELDS)
        writer.writeheader()
        for rank, row in enumerate(rows, 1):
            publication = row["publication"]
            analysis = row["analysis"]
            writer.writerow(
                {
                    "rank": rank,
                    "status": _safe_csv_text(row["status"]),
                    "reservation_id": row["reservation_id"] or "",
                    "priority": (
                        _safe_csv_text(analysis.priority.value)
                        if analysis is not None
                        else ""
                    ),
                    "interest_score": (
                        analysis.interest_score if analysis is not None else ""
                    ),
                    "raw_interest_score": (
                        analysis.raw_interest_score if analysis is not None else ""
                    ),
                    "mission_fit_score": (
                        analysis.mission_fit_score if analysis is not None else ""
                    ),
                    "scientific_robustness_score": (
                        analysis.scientific_robustness_score
                        if analysis is not None
                        else ""
                    ),
                    "actionability_score": (
                        analysis.actionability_score if analysis is not None else ""
                    ),
                    "generalizability_score": (
                        analysis.generalizability_score
                        if analysis is not None
                        else ""
                    ),
                    "novelty_score": (
                        analysis.novelty_score if analysis is not None else ""
                    ),
                    "classification_rules": (
                        _safe_csv_text(" | ".join(analysis.classification_rules))
                        if analysis is not None
                        else ""
                    ),
                    "evidence_quality": (
                        _safe_csv_text(analysis.evidence_quality)
                        if analysis is not None
                        else ""
                    ),
                    "has_abstract": "yes" if publication.abstract else "no",
                    "classification_reason": (
                        _safe_csv_text(analysis.classification_reason)
                        if analysis is not None
                        else ""
                    ),
                    "title": _safe_csv_text(publication.title),
                    "doi": _safe_csv_text(publication.doi),
                    "url": _safe_csv_text(publication.url),
                    "journal": _safe_csv_text(publication.journal),
                    "published_date": _safe_csv_text(publication.published_date),
                    "authors": _safe_csv_text(" | ".join(publication.authors)),
                    "summary_fr": (
                        _safe_csv_text(analysis.summary_fr)
                        if analysis is not None
                        else ""
                    ),
                    "bellegarde_value": (
                        _safe_csv_text(analysis.bellegarde_value)
                        if analysis is not None
                        else ""
                    ),
                    "applications": (
                        _safe_csv_text(" | ".join(analysis.applications))
                        if analysis is not None
                        else ""
                    ),
                    "themes": (
                        _safe_csv_text(" | ".join(analysis.themes))
                        if analysis is not None
                        else ""
                    ),
                    "model": (
                        _safe_csv_text(analysis.model)
                        if analysis is not None
                        else ""
                    ),
                    "prompt_version": (
                        _safe_csv_text(analysis.prompt_version)
                        if analysis is not None
                        else ""
                    ),
                }
            )


def export_backfill_classification(database, plan_path, output, model):
    plan = _load_plan(plan_path)
    _validate_plan(plan, model)
    store = Store(database)
    try:
        rows = _classification_rows(
            store,
            plan["candidate_identities"],
            model,
            OpenAIAnalyzer.prompt_version,
        )
        _write_classification(
            output, rows, model, OpenAIAnalyzer.prompt_version
        )
    finally:
        store.close()
    counts = _row_counts(rows)
    return {
        "service": "backfill-export",
        "status": "ok",
        "classification_output": str(output),
        "publications_total": len(rows),
        "classification_pending": counts.get("unclassified", 0)
        + counts.get("needs_review", 0),
        "unresolved_reservations": counts.get("needs_review", 0),
        "digest_ready": counts.get("pending", 0),
        "withheld_without_abstract": counts.get(
            "withheld_without_abstract", 0
        ),
        "publications_excluded": counts.get("excluded", 0),
        "publications_delivered": counts.get("delivered", 0)
        + counts.get("already_delivered", 0),
        "errors": [],
    }


def classify_backfill(
    config_path,
    database,
    plan_path,
    classification_output,
    budget_usd,
    batch_limit=0,
    ai_opener=None,
    progress=None,
):
    if not math.isfinite(budget_usd) or budget_usd <= 0:
        raise ValueError("Le budget de classement doit être strictement positif.")
    if batch_limit < 0 or batch_limit > 10000:
        raise ValueError("La taille du lot doit être comprise entre 0 et 10 000.")
    _campaign_paths(config_path, database, plan_path, classification_output)
    config = _load_config(config_path)
    if not config.getboolean("backfill", "enabled", fallback=False):
        raise ValueError("Le rattrapage est désactivé dans [backfill].")
    if not config.getboolean("ai", "enabled", fallback=False):
        raise ValueError("L’IA est désactivée dans [ai].")
    model = config.get("ai", "model", fallback="gpt-5.6-luna").strip()
    plan = _load_plan(plan_path)
    _validate_plan(plan, model)
    analyzer = _analysis_provider(config, model, ai_opener)
    pricing = MODEL_PRICING[model]
    backup_path = _ensure_classification_backup(database)

    store = Store(database)
    analyzed = 0
    input_tokens = 0
    output_tokens = 0
    budget_exhausted = False
    warnings = []
    try:
        wanted = set(plan["candidate_identities"])
        publications = tuple(
            publication
            for publication in store.backfill_publications()
            if publication.identity in wanted
        )
        pending = []
        for publication in publications:
            assessment = store.load_ai_assessment(
                publication.identity, model, analyzer.prompt_version
            )
            reservation = store.backfill_budget_reservation(
                publication.identity, model, analyzer.prompt_version
            )
            if (
                assessment is not None
                and reservation is not None
                and reservation["status"] == "reserved"
            ):
                store.complete_backfill_budget_reservation(
                    reservation["id"],
                    _cost(
                        assessment.input_tokens,
                        assessment.output_tokens,
                        pricing,
                        upper_bound=True,
                    ),
                    assessment.input_tokens,
                    assessment.output_tokens,
                )
                reservation = store.backfill_budget_reservation(
                    publication.identity, model, analyzer.prompt_version
                )
            if assessment is not None:
                continue
            if reservation is not None and reservation["status"] != "released":
                warnings.append(
                    "La réservation IA #{} est inachevée pour {} ; vérifiez "
                    "la facturation avant de la libérer.".format(
                        reservation["id"], publication.identity
                    )
                )
                continue
            pending.append(publication)
        pending = tuple(pending)
        total_pending = len(pending)
        if batch_limit:
            pending = pending[:batch_limit]
        legacy_input_tokens, legacy_output_tokens = (
            store.backfill_unreserved_ai_usage()
        )
        legacy_cost_upper_bound = _cost(
            legacy_input_tokens,
            legacy_output_tokens,
            pricing,
            upper_bound=True,
        )
        consecutive_failures = 0
        for publication in pending:
            reservation_id, reservation_status = store.reserve_backfill_budget(
                publication.identity,
                model,
                analyzer.prompt_version,
                _maximum_call_cost(publication, pricing),
                budget_usd,
                legacy_cost_upper_bound,
            )
            if reservation_status == "existing":
                warnings.append(
                    "La réservation IA #{} est inachevée pour {} ; vérifiez "
                    "la facturation avant de la libérer.".format(
                        reservation_id, publication.identity
                    )
                )
                continue
            if reservation_status == "budget":
                budget_exhausted = True
                break
            try:
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
            except Exception as error:
                consecutive_failures += 1
                warnings.append(
                    "{} : {}".format(publication.identity, error)
                )
                if consecutive_failures >= 3:
                    warnings.append(
                        "Classement interrompu après trois erreurs consécutives."
                    )
                    break
                continue
            consecutive_failures = 0
            analyzed += 1
            input_tokens += analysis.input_tokens
            output_tokens += analysis.output_tokens
            if progress is not None:
                progress(analyzed, total_pending, publication, analysis)

        rows = _classification_rows(
            store,
            plan["candidate_identities"],
            model,
            analyzer.prompt_version,
        )
        _write_classification(
            classification_output, rows, model, analyzer.prompt_version
        )
        counts = _row_counts(rows)
        reserved_cost, campaign_input, campaign_output = (
            store.backfill_budget_usage()
        )
    finally:
        store.close()

    unresolved_count = counts.get("needs_review", 0)
    pending_count = counts.get("unclassified", 0) + unresolved_count
    return {
        "service": "backfill-classify",
        "status": "partial" if pending_count else "ok",
        "ai_called": analyzed > 0,
        "budget_exhausted": budget_exhausted,
        "budget_usd": budget_usd,
        "actual_cost_usd": _cost(input_tokens, output_tokens, pricing),
        "campaign_cost_upper_bound_usd": round(reserved_cost, 6),
        "campaign_input_tokens": campaign_input,
        "campaign_output_tokens": campaign_output,
        "publications_classified": analyzed,
        "classification_pending": pending_count,
        "unresolved_reservations": unresolved_count,
        "digest_ready": counts.get("pending", 0),
        "withheld_without_abstract": counts.get(
            "withheld_without_abstract", 0
        ),
        "publications_excluded": counts.get("excluded", 0),
        "classification_output": str(classification_output),
        "classification_backup": str(backup_path),
        "warnings": warnings,
        "errors": [],
    }


def dispatch_backfill(
    config_path,
    database,
    plan_path,
    output,
    article_limit=10,
    classification_output=None,
    no_send=False,
    smtp_factory=None,
):
    if article_limit < 1 or article_limit > 100:
        raise ValueError("La limite quotidienne doit être comprise entre 1 et 100.")
    config = _load_config(config_path)
    if not config.getboolean("backfill", "enabled", fallback=False):
        raise ValueError("Le rattrapage est désactivé dans [backfill].")
    model = config.get("ai", "model", fallback="gpt-5.6-luna").strip()
    plan = _load_plan(plan_path)
    _validate_plan(plan, model)
    if classification_output is None:
        classification_output = str(
            Path(plan_path).with_name("rattrapage-classement.csv")
        )
    _campaign_paths(
        config_path,
        database,
        plan_path,
        classification_output,
        output=output,
    )

    store = Store(database)
    try:
        rows = _classification_rows(
            store,
            plan["candidate_identities"],
            model,
            OpenAIAnalyzer.prompt_version,
        )
        counts = _row_counts(rows)
        incomplete_count = counts.get("unclassified", 0) + counts.get(
            "needs_review", 0
        )
        if incomplete_count:
            raise ValueError(
                "Le classement n’est pas terminé : {} article(s) restent à "
                "analyser ou vérifier.".format(incomplete_count)
            )
        selected_rows = [row for row in rows if row["status"] == "pending"][
            :article_limit
        ]
        selected = tuple(
            _analyzed_publication(row["publication"], row["analysis"])
            for row in selected_rows
        )
        sender = None
        if selected:
            write_digest(
                output,
                selected,
                total_count=len(selected),
                excluded_count=0,
                feedback_settings=load_feedback_settings(config_path),
            )
            if not no_send:
                sender = SMTPDigestSender(
                    config_path,
                    smtp_factory=smtp_factory,
                    subject_prefix="Rattrapage",
                )
                sender.send(output, selected)
                if sender.sent:
                    store.mark_delivered(selected)
            store.record_digest_run(
                "rattrapage",
                selected,
                recipient=getattr(sender, "recipient", "") or "",
                output_path=output,
                sent=bool(getattr(sender, "sent", False)),
                total_count=len(selected),
            )
        rows_after = _classification_rows(
            store,
            plan["candidate_identities"],
            model,
            OpenAIAnalyzer.prompt_version,
        )
        _write_classification(
            classification_output,
            rows_after,
            model,
            OpenAIAnalyzer.prompt_version,
        )
        counts_after = _row_counts(rows_after)
    finally:
        store.close()

    delivered = len(selected) if sender is not None and sender.sent else 0
    return {
        "service": "backfill-dispatch",
        "status": "ok",
        "email_sent": bool(sender and sender.sent),
        "recipient": sender.recipient if sender else None,
        "publications_selected": len(selected),
        "publications_delivered": delivered,
        "digest_remaining": counts_after.get("pending", 0),
        "withheld_without_abstract": counts_after.get(
            "withheld_without_abstract", 0
        ),
        "publications_excluded": counts_after.get("excluded", 0),
        "classification_output": str(classification_output),
        "warnings": [],
        "errors": [],
    }
