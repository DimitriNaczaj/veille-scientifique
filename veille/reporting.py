def _row(label, value):
    return "{:<24}{}".format(label, value)


def _backfill_row(label, value):
    return "{:<28}{}".format(label, value)


def _unique_messages(*groups):
    messages = []
    for group in groups:
        for message in group or ():
            text = str(message).strip()
            if text and text not in messages:
                messages.append(text)
    return messages


def _message_summary(lines, label, messages, empty_label):
    if not messages:
        lines.append(_row(label, empty_label))
        return
    lines.append(_row(label, len(messages)))
    lines.extend("  - {}".format(message) for message in messages)


def format_refresh_report(report):
    lines = [
        "REPRISE DES RÉSUMÉS",
        "===================",
        _row("Entrées sans résumé", report.get("pending_before", 0)),
        _row("Reprises tentées", report.get("attempted", 0)),
        _row("Résumés récupérés", report.get("recovered", 0)),
        _row("Restant sans résumé", report.get("remaining", 0)),
    ]
    _message_summary(
        lines, "Avertissements", _unique_messages(report.get("warnings")), "aucun"
    )
    return "\n".join(lines)


def format_backfill_classification(report):
    row = _backfill_row
    lines = [
        "RATTRAPAGE – CLASSEMENT",
        "=======================",
        row("Statut", str(report.get("status") or "inconnu").upper()),
        row("Analysés dans ce lot", report.get("publications_classified") or 0),
        row("Restant à classer", report.get("classification_pending") or 0),
        row(
            "Réservations à vérifier",
            report.get("unresolved_reservations") or 0,
        ),
        row("Prêts pour le digest", report.get("digest_ready") or 0),
        row(
            "Sans abstract, retenus à part",
            report.get("withheld_without_abstract") or 0,
        ),
        row("Écartés par l’IA", report.get("publications_excluded") or 0),
        row("Fichier de contrôle", report.get("classification_output") or "absent"),
        row("Sauvegarde SQLite", report.get("classification_backup") or "existante"),
        row(
            "Coût cumulé maximal",
            "{:.6f} $US".format(
                report.get("campaign_cost_upper_bound_usd") or 0
            ),
        ),
    ]
    lines.append("")
    _message_summary(
        lines,
        "Avertissements",
        _unique_messages(report.get("warnings")),
        "aucun",
    )
    return "\n".join(str(line) for line in lines)


def format_backfill_dispatch(report):
    row = _backfill_row
    lines = [
        "RATTRAPAGE – DIGEST QUOTIDIEN",
        "=============================",
        row("Statut", str(report.get("status") or "inconnu").upper()),
        row("Articles sélectionnés", report.get("publications_selected") or 0),
        row("Articles envoyés", report.get("publications_delivered") or 0),
        row("Restant dans la file", report.get("digest_remaining") or 0),
        row(
            "Sans abstract, retenus à part",
            report.get("withheld_without_abstract") or 0,
        ),
        row("Newsletter envoyée", "oui" if report.get("email_sent") else "non"),
        row("Fichier de contrôle", report.get("classification_output") or "absent"),
    ]
    lines.append("")
    _message_summary(
        lines,
        "Avertissements",
        _unique_messages(report.get("warnings")),
        "aucun",
    )
    return "\n".join(str(line) for line in lines)


def format_daily_error(error):
    detail = str(error).strip() or "Erreur inconnue"
    return "\n".join(
        (
            "VEILLE SCIENTIFIQUE",
            "===================",
            _row("Statut", "ERREUR"),
            "",
            "EXÉCUTION",
            "---------",
            "Le traitement n’a pas pu se terminer.",
            _row("Détail", detail),
        )
    )


def format_backfill_plan(plan):
    row = _backfill_row
    comparison = plan.get("profile_comparison") or {}
    lines = [
        "RATTRAPAGE – PLAN SANS IA",
        "=========================",
        row("Statut", str(plan.get("status") or "inconnu").upper()),
        row("Profil", plan.get("profile") or "non renseigné"),
        row("Modèle", plan.get("model") or "non renseigné"),
        row(
            "Tarifs",
            "{} – vérifiés le {}".format(
                plan.get("pricing_source") or "source inconnue",
                plan.get("pricing_checked_at") or "date inconnue",
            ),
        ),
        row(
            "Entrée / sortie",
            "{:.2f} / {:.2f} $US par million de tokens".format(
                (plan.get("pricing_usd_per_million") or {}).get("input") or 0,
                (plan.get("pricing_usd_per_million") or {}).get("output") or 0,
            ),
        ),
        "",
        "SÉLECTION LOCALE",
        "----------------",
        row("Publications disponibles", plan.get("publications_available") or 0),
        row("Abstracts disponibles", plan.get("abstracts_available") or 0),
        row("Enrichissements en attente", plan.get("enrichment_pending") or 0),
        row("Candidates pour l’IA", plan.get("publications_ai_candidates") or 0),
        row("Écartées localement", plan.get("publications_locally_excluded") or 0),
        row("Échantillon CSV", plan.get("sample_output") or "non généré"),
        row("Titres échantillonnés", plan.get("sample_size") or 0),
        "",
        "COMPARAISON AVANT ABSTRACTS",
        "----------------------------",
        row("Profil strict", comparison.get("strict") or 0),
        row("Profil standard", comparison.get("standard") or 0),
        row("Profil large", comparison.get("large") or 0),
        "",
        "ESTIMATION",
        "----------",
        row(
            "Tokens attendus",
            (plan.get("expected") or {}).get("total_tokens") or 0,
        ),
        row(
            "Coût attendu",
            "{:.6f} $US".format((plan.get("expected") or {}).get("cost_usd") or 0),
        ),
        row(
            "Coût prudent",
            "{:.6f} $US".format(
                (plan.get("conservative") or {}).get("cost_usd") or 0
            ),
        ),
        row(
            "Plafond calculé",
            "{:.6f} $US".format((plan.get("maximum") or {}).get("cost_usd") or 0),
        ),
        row("Prêt pour l’IA", "oui" if plan.get("ready_for_ai") else "non"),
        "",
        "Aucun appel IA effectué.",
    ]
    return "\n".join(str(line) for line in lines)


def format_backfill_daily(report):
    row = _backfill_row
    plan = report.get("plan") or {}
    execution = report.get("execution") or {}
    status_labels = {
        "waiting_for_approval": "EN ATTENTE D’APPROBATION",
        "preparing": "PRÉPARATION",
        "ok": "OK",
    }
    status = str(report.get("status") or "inconnu")
    lines = [
        "RATTRAPAGE",
        "==========",
        row("Statut", status_labels.get(status, status.upper())),
        row("Appel IA", "oui" if report.get("ai_called") else "non"),
        "",
        "PLAN",
        "----",
        row("Publications disponibles", plan.get("publications_available") or 0),
        row("Candidates pour l’IA", plan.get("publications_ai_candidates") or 0),
        row("Enrichissements en attente", plan.get("enrichment_pending") or 0),
        row("Prêt pour l’IA", "oui" if plan.get("ready_for_ai") else "non"),
        row("Échantillon CSV", plan.get("sample_output") or "non généré"),
        row(
            "Coût attendu",
            "{:.6f} $US".format((plan.get("expected") or {}).get("cost_usd") or 0),
        ),
        row(
            "Plafond calculé",
            "{:.6f} $US".format((plan.get("maximum") or {}).get("cost_usd") or 0),
        ),
    ]
    if execution:
        lines.extend(
            [
                "",
                "LOT",
                "---",
                row("Articles analysés", execution.get("publications_ai_analyzed") or 0),
                row("Articles retenus", execution.get("publications_relevant") or 0),
                row("Articles restants", execution.get("publications_remaining") or 0),
                row(
                    "Budget restant",
                    "{:.6f} $US".format(execution.get("budget_remaining_usd") or 0),
                ),
                row("Newsletter envoyée", "oui" if execution.get("email_sent") else "non"),
            ]
        )
    warnings = _unique_messages(plan.get("warnings"), execution.get("warnings"))
    lines.append("")
    _message_summary(lines, "Avertissements", warnings, "aucun")
    return "\n".join(str(line) for line in lines)


def format_daily_report(report):
    sync = report.get("sync") or {}
    pipeline = report.get("pipeline") or {}
    input_tokens = int(pipeline.get("ai_input_tokens") or 0)
    output_tokens = int(pipeline.get("ai_output_tokens") or 0)
    warnings = _unique_messages(
        report.get("warnings"),
        sync.get("warnings"),
        pipeline.get("warnings"),
    )
    errors = _unique_messages(
        report.get("errors"),
        sync.get("errors"),
        pipeline.get("errors"),
    )
    status = str(report.get("status") or "inconnu").upper()
    email_status = "oui" if report.get("email_sent") else "non"
    if report.get("email_sent") and report.get("recipient"):
        email_status += " → {}".format(report["recipient"])

    lines = [
        "VEILLE SCIENTIFIQUE",
        "===================",
        _row("Statut", status),
        _row("IA", "activée" if report.get("ai_enabled") else "désactivée"),
        "",
        "SYNCHRONISATION",
        "---------------",
        _row("Dossier IMAP", sync.get("folder") or "non renseigné"),
        _row("Dernier UID", sync.get("last_uid") or 0),
        _row("Messages disponibles", sync.get("messages_available") or 0),
        _row("Messages téléchargés", sync.get("messages_downloaded") or 0),
        _row("Messages déjà présents", sync.get("messages_existing") or 0),
        "",
        "TRAITEMENT",
        "----------",
        _row("Newsletters traitées", pipeline.get("messages_processed") or 0),
        _row("Newsletters ignorées", pipeline.get("messages_skipped") or 0),
        _row("Articles détectés", pipeline.get("publications_detected") or 0),
        _row("Nouveaux articles", pipeline.get("publications_new") or 0),
        _row("Articles analysés", pipeline.get("publications_ai_analyzed") or 0),
        _row("Articles retenus", pipeline.get("publications_relevant") or 0),
        _row("Articles écartés", pipeline.get("publications_excluded") or 0),
        _row("Articles en attente", pipeline.get("publications_pending") or 0),
        _row(
            "Tokens IA",
            "{} ({} entrée + {} sortie)".format(
                input_tokens + output_tokens,
                input_tokens,
                output_tokens,
            ),
        ),
        "",
        "ENVOI",
        "-----",
        _row("Newsletter envoyée", email_status),
    ]
    _message_summary(lines, "Avertissements", warnings, "aucun")
    _message_summary(lines, "Erreurs", errors, "aucune")
    return "\n".join(str(line) for line in lines)
