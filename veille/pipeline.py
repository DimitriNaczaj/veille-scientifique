from pathlib import Path

from .digest import write_digest
from .mail_parser import parse_message
from .models import RunReport
from .storage import Store


def run_pipeline(inbox, database, output):
    inbox_path = Path(inbox)
    if not inbox_path.exists() or not inbox_path.is_dir():
        raise ValueError("Le dossier d’entrée n’existe pas : {}".format(inbox_path))

    messages_processed = 0
    messages_skipped = 0
    publications_detected = 0
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
                store.add_message(message, message_path)
                messages_processed += 1
            except Exception as error:
                errors.append("{}: {}".format(message_path.name, error))

        pending_publications = store.pending_publications()
        write_digest(output, pending_publications)
        store.mark_delivered(pending_publications)
    finally:
        store.close()

    return RunReport(
        messages_processed=messages_processed,
        messages_skipped=messages_skipped,
        publications_detected=publications_detected,
        publications_new=len(pending_publications),
        errors=tuple(errors),
    )
