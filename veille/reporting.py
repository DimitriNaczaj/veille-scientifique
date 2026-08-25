def _row(label, value):
    return "{:<24}{}".format(label, value)


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
