import argparse
import json
import sys

from .pipeline import run_pipeline


def build_parser():
    parser = argparse.ArgumentParser(description="Veille scientifique Bellegarde")
    subparsers = parser.add_subparsers(dest="command")
    run = subparsers.add_parser("run", help="Traiter les newsletters et générer un digest")
    run.add_argument("--inbox", required=True, help="Dossier contenant les fichiers .eml")
    run.add_argument("--database", required=True, help="Chemin de la base SQLite")
    run.add_argument("--output", required=True, help="Chemin du digest HTML")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "run":
        parser.print_help()
        return 2

    try:
        report = run_pipeline(args.inbox, args.database, args.output)
    except Exception as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=True))
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
