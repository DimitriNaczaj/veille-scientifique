import argparse
import json
import os
import sys

from .crossref import CrossrefClient
from .backfill import (
    build_backfill_plan,
    release_backfill_reservation,
    run_backfill,
    run_backfill_daily,
)
from .daily import run_daily
from .filtering import BehavioralScienceFilter
from .imap_sync import run_imap_sync
from .mbox_import import run_mbox_import
from .mail_diagnostics import run_imap_diagnostic, run_smtp_diagnostic
from .pipeline import run_pipeline
from .reporting import (
    format_backfill_daily,
    format_backfill_plan,
    format_daily_error,
    format_daily_report,
)
from .secret_migration import (
    migrate_inline_mail_password,
    set_elsevier_api_key,
    set_openai_api_key,
)


def build_parser():
    parser = argparse.ArgumentParser(description="Veille scientifique Bellegarde")
    subparsers = parser.add_subparsers(dest="command")
    run = subparsers.add_parser("run", help="Traiter les newsletters et générer un digest")
    run.add_argument("--inbox", required=True, help="Dossier contenant les fichiers .eml")
    run.add_argument("--database", required=True, help="Chemin de la base SQLite")
    run.add_argument("--output", required=True, help="Chemin du digest HTML")
    run.add_argument(
        "--crossref-email",
        default=os.environ.get("CROSSREF_EMAIL"),
        help="Adresse de contact transmise à Crossref (ou variable CROSSREF_EMAIL)",
    )
    run.add_argument(
        "--enrichment-limit",
        type=int,
        default=100,
        help="Nombre maximal de DOI enrichis par exécution (défaut : 100)",
    )
    run.add_argument(
        "--no-enrichment",
        action="store_true",
        help="Désactiver les appels Crossref pour cette exécution",
    )
    run.add_argument(
        "--no-filter",
        action="store_true",
        help="Inclure toutes les références sans préfiltrage thématique",
    )
    import_mbox = subparsers.add_parser(
        "import-mbox",
        help="Importer un historique MBOX ou MBOX.ZIP sans appel externe",
    )
    import_mbox.add_argument(
        "--source", required=True, help="Fichier MBOX ou archive ZIP contenant un MBOX"
    )
    import_mbox.add_argument(
        "--database", required=True, help="Chemin de la base SQLite"
    )
    import_mbox.add_argument(
        "--catalog", required=True, help="Chemin du catalogue CSV"
    )
    import_mbox.add_argument(
        "--report", required=True, help="Chemin du rapport JSON"
    )
    test_imap = subparsers.add_parser(
        "test-imap",
        help="Vérifier la connexion IMAP sans modifier les messages",
    )
    test_imap.add_argument(
        "--config", required=True, help="Chemin du fichier INI privé"
    )
    test_smtp = subparsers.add_parser(
        "test-smtp",
        help="Vérifier SMTP et envoyer éventuellement un mail de contrôle",
    )
    test_smtp.add_argument(
        "--config", required=True, help="Chemin du fichier INI privé"
    )
    test_smtp.add_argument(
        "--send-test",
        action="store_true",
        help="Envoyer un mail de contrôle au destinataire configuré",
    )
    sync_imap = subparsers.add_parser(
        "sync-imap",
        help="Télécharger les nouveaux messages IMAP sans modifier la boîte",
    )
    sync_imap.add_argument("--config", required=True, help="Chemin du fichier INI privé")
    sync_imap.add_argument("--inbox", required=True, help="Dossier local des messages .eml")
    sync_imap.add_argument("--database", required=True, help="Chemin de la base SQLite")
    sync_imap.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Nombre maximal de messages téléchargés, 0 pour tous (défaut : 200)",
    )
    sync_imap.add_argument(
        "--initial-mode",
        choices=("all", "latest"),
        default="all",
        help="Au premier passage, tout télécharger ou ignorer l’historique",
    )
    migrate_secrets = subparsers.add_parser(
        "migrate-secrets",
        help="Extraire un ancien mot de passe mail inline vers un fichier privé",
    )
    migrate_secrets.add_argument(
        "--config", required=True, help="Chemin du fichier INI privé"
    )
    migrate_secrets.add_argument(
        "--secrets", required=True, help="Chemin du fichier secrets.env"
    )
    set_openai_key = subparsers.add_parser(
        "set-openai-key",
        help="Enregistrer une clé OpenAI par saisie masquée et validée",
    )
    set_openai_key.add_argument(
        "--secrets", required=True, help="Chemin du fichier secrets.env"
    )
    set_elsevier_key = subparsers.add_parser(
        "set-elsevier-key",
        help="Enregistrer une clé Elsevier par saisie masquée et validée",
    )
    set_elsevier_key.add_argument(
        "--secrets", required=True, help="Chemin du fichier secrets.env"
    )
    daily = subparsers.add_parser(
        "daily",
        help="Synchroniser, analyser, générer et envoyer la veille quotidienne",
    )
    daily.add_argument("--config", required=True, help="Chemin du fichier INI privé")
    daily.add_argument("--inbox", help="Remplacer le dossier local configuré")
    daily.add_argument("--database", help="Remplacer la base SQLite configurée")
    daily.add_argument("--output", help="Remplacer le digest HTML configuré")
    daily.add_argument("--sync-limit", type=int, help="Remplacer la limite IMAP")
    daily.add_argument(
        "--initial-mode",
        choices=("all", "latest"),
        help="Remplacer le mode du premier passage IMAP",
    )
    daily.add_argument(
        "--enrichment-limit", type=int, help="Remplacer la limite d’enrichissement"
    )
    daily.add_argument("--ai-limit", type=int, help="Remplacer la limite IA")
    daily.add_argument("--no-ai", action="store_true", help="Désactiver l’analyse IA")
    daily.add_argument("--no-send", action="store_true", help="Générer sans envoyer")
    daily.add_argument(
        "--format",
        dest="report_format",
        choices=("json", "human"),
        default="json",
        help="Format du rapport affiché (défaut : json)",
    )
    backfill_plan = subparsers.add_parser(
        "backfill-plan",
        help="Estimer sans IA le coût du rattrapage",
    )
    backfill_plan.add_argument("--database", required=True, help="Base SQLite")
    backfill_plan.add_argument("--output", required=True, help="Plan JSON à écrire")
    backfill_plan.add_argument("--config", help="Configuration pour enrichir sans IA")
    backfill_plan.add_argument("--enrichment-limit", type=int, default=0)
    backfill_plan.add_argument("--sample-output", help="Échantillon CSV des candidats")
    backfill_plan.add_argument("--sample-size", type=int, default=50)
    backfill_plan.add_argument("--model", default="gpt-5.6-luna")
    backfill_plan.add_argument(
        "--profile",
        choices=("strict", "standard", "large"),
        default="standard",
    )
    backfill_plan.add_argument(
        "--format",
        dest="report_format",
        choices=("json", "human"),
        default="json",
    )
    backfill_run = subparsers.add_parser(
        "backfill-run",
        help="Exécuter un plan de rattrapage avec un budget strict",
    )
    backfill_run.add_argument("--config", required=True)
    backfill_run.add_argument("--database", required=True)
    backfill_run.add_argument("--plan", required=True)
    backfill_run.add_argument("--output", required=True)
    backfill_run.add_argument("--budget-usd", type=float, required=True)
    backfill_run.add_argument("--article-limit", type=int, default=15)
    backfill_run.add_argument("--no-send", action="store_true")
    backfill_daily = subparsers.add_parser(
        "backfill-daily",
        help="Préparer ou exécuter un lot quotidien de rattrapage",
    )
    backfill_daily.add_argument("--config", required=True)
    backfill_daily.add_argument(
        "--format",
        dest="report_format",
        choices=("json", "human"),
        default="json",
    )
    backfill_release = subparsers.add_parser(
        "backfill-release-reservation",
        help="Libérer une réservation IA confirmée non facturée",
    )
    backfill_release.add_argument("--database", required=True)
    backfill_release.add_argument("--reservation-id", required=True, type=int)
    backfill_release.add_argument(
        "--confirm-unbilled",
        action="store_true",
        required=True,
        help="Confirmer après vérification OpenAI que l’appel n’a pas été facturé",
    )
    return parser


def main(
    argv=None,
    imap_factory=None,
    smtp_factory=None,
    http_opener=None,
    ai_opener=None,
):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2

    try:
        if args.command == "daily":
            report = run_daily(
                args.config,
                inbox=args.inbox,
                database=args.database,
                output=args.output,
                sync_limit=args.sync_limit,
                initial_mode=args.initial_mode,
                enrichment_limit=args.enrichment_limit,
                ai_limit=args.ai_limit,
                no_ai=args.no_ai,
                no_send=args.no_send,
                imap_factory=imap_factory,
                smtp_factory=smtp_factory,
                http_opener=http_opener,
                ai_opener=ai_opener,
            )
        elif args.command == "sync-imap":
            report = run_imap_sync(
                args.config,
                args.inbox,
                args.database,
                limit=args.limit,
                initial_mode=args.initial_mode,
                client_factory=imap_factory,
            )
        elif args.command == "test-smtp":
            report = run_smtp_diagnostic(
                args.config,
                send_test=args.send_test,
                client_factory=smtp_factory,
            )
        elif args.command == "test-imap":
            report = run_imap_diagnostic(
                args.config, client_factory=imap_factory
            )
        elif args.command == "migrate-secrets":
            report = migrate_inline_mail_password(args.config, args.secrets)
        elif args.command == "set-openai-key":
            report = set_openai_api_key(args.secrets)
        elif args.command == "set-elsevier-key":
            report = set_elsevier_api_key(args.secrets)
        elif args.command == "import-mbox":
            report = run_mbox_import(
                args.source, args.database, args.catalog, args.report
            )
        elif args.command == "backfill-plan":
            report = build_backfill_plan(
                args.database,
                args.output,
                model=args.model,
                profile=args.profile,
                config_path=args.config,
                enrichment_limit=args.enrichment_limit,
                http_opener=http_opener,
                sample_output=args.sample_output,
                sample_size=args.sample_size,
            )
        elif args.command == "backfill-run":
            report = run_backfill(
                args.config,
                args.database,
                args.plan,
                args.output,
                args.budget_usd,
                article_limit=args.article_limit,
                no_send=args.no_send,
                smtp_factory=smtp_factory,
                ai_opener=ai_opener,
            )
        elif args.command == "backfill-daily":
            report = run_backfill_daily(
                args.config,
                smtp_factory=smtp_factory,
                http_opener=http_opener,
                ai_opener=ai_opener,
            )
        elif args.command == "backfill-release-reservation":
            report = release_backfill_reservation(
                args.database,
                args.reservation_id,
            )
        else:
            metadata_provider = None
            if not args.no_enrichment:
                metadata_provider = CrossrefClient(contact_email=args.crossref_email)
            relevance_filter = None if args.no_filter else BehavioralScienceFilter()
            report = run_pipeline(
                args.inbox,
                args.database,
                args.output,
                metadata_provider=metadata_provider,
                relevance_filter=relevance_filter,
                enrichment_limit=args.enrichment_limit,
            )
    except Exception as error:
        if (
            args.command == "daily"
            and getattr(args, "report_format", "json") == "human"
        ):
            print(format_daily_error(error), file=sys.stderr)
        else:
            print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1

    report_payload = report if isinstance(report, dict) else report.as_dict()
    if args.command == "daily" and args.report_format == "human":
        print(format_daily_report(report_payload))
    elif args.command == "backfill-plan" and args.report_format == "human":
        print(format_backfill_plan(report_payload))
    elif args.command == "backfill-daily" and args.report_format == "human":
        print(format_backfill_daily(report_payload))
    else:
        print(json.dumps(report_payload, ensure_ascii=False, sort_keys=True))
    return 1 if getattr(report, "errors", ()) else 0


if __name__ == "__main__":
    sys.exit(main())
