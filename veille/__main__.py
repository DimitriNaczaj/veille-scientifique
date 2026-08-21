import argparse
import json
import os
import sys

from .crossref import CrossrefClient
from .filtering import BehavioralScienceFilter
from .mbox_import import run_mbox_import
from .pipeline import run_pipeline


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
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2

    try:
        if args.command == "import-mbox":
            report = run_mbox_import(
                args.source, args.database, args.catalog, args.report
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
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=True))
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
