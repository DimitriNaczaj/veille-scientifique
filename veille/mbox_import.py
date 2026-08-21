import csv
import json
import mailbox
import shutil
import tempfile
import zipfile
from collections import defaultdict
from contextlib import contextmanager
from email import policy
from email.utils import parseaddr
from pathlib import Path

from .mail_parser import parse_message_bytes
from .models import ImportReport
from .storage import Store


CATALOG_FIELDS = (
    "identity",
    "doi",
    "title",
    "url",
    "source_subject",
    "source_sender",
)
MAX_MBOX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024


def _validate_distinct_paths(paths):
    items = list(paths.items())
    for index, (first_name, first_path) in enumerate(items):
        first = Path(first_path)
        for second_name, second_path in items[index + 1 :]:
            second = Path(second_path)
            same_path = first.resolve() == second.resolve()
            same_file = False
            if first.exists() and second.exists():
                same_file = first.samefile(second)
            if same_path or same_file:
                raise ValueError(
                    "Les chemins source, base, catalogue et rapport doivent être "
                    "distincts (collision entre {} et {}).".format(
                        first_name, second_name
                    )
                )


def _write_text_atomically(path, writer, newline=None):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline=newline,
            prefix=destination.name + ".",
            suffix=".tmp",
            dir=str(destination.parent),
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            writer(stream)
        temporary.replace(destination)
    except Exception:
        if temporary is not None and temporary.exists():
            temporary.unlink()
        raise


def _sender_domain(sender):
    address = parseaddr(sender)[1]
    if "@" not in address:
        return "unknown"
    return address.rsplit("@", 1)[1].casefold()


def _write_catalog(path, publications):
    def write(stream):
        writer = csv.DictWriter(stream, fieldnames=CATALOG_FIELDS)
        writer.writeheader()
        for publication in publications:
            writer.writerow(
                {
                    "identity": publication.identity,
                    "doi": publication.doi or "",
                    "title": publication.title or "",
                    "url": publication.url or "",
                    "source_subject": publication.source_subject,
                    "source_sender": publication.source_sender,
                }
            )

    _write_text_atomically(path, write, newline="")


def _write_report(path, report):
    def write(stream):
        stream.write(
            json.dumps(report.as_dict(), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        )

    _write_text_atomically(path, write)


@contextmanager
def _readable_mbox(source_path):
    if not zipfile.is_zipfile(source_path):
        yield source_path
        return

    with zipfile.ZipFile(source_path) as archive:
        candidates = [
            info
            for info in archive.infolist()
            if not info.is_dir()
            and "__macosx" not in {
                part.casefold() for part in Path(info.filename).parts
            }
            and not Path(info.filename).name.startswith("._")
            and (
                Path(info.filename).name.casefold() == "mbox"
                or info.filename.casefold().endswith(".mbox")
            )
        ]
        if len(candidates) != 1:
            raise ValueError(
                "L’archive ZIP doit contenir exactement un fichier MBOX."
            )
        member = candidates[0]
        if member.file_size > MAX_MBOX_UNCOMPRESSED_BYTES:
            raise ValueError("Le fichier MBOX décompressé dépasse la limite de 2 Go.")
        with tempfile.TemporaryDirectory(prefix="veille-mbox-") as directory:
            extracted = Path(directory) / "archive.mbox"
            with archive.open(member) as source, extracted.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            yield extracted


def run_mbox_import(source, database, catalog, report_output):
    source_path = Path(source)
    if not source_path.exists() or not source_path.is_file():
        raise ValueError("Le fichier MBOX n’existe pas : {}".format(source_path))
    _validate_distinct_paths(
        {
            "source": source_path,
            "base": database,
            "catalogue": catalog,
            "rapport": report_output,
        }
    )

    messages_total = 0
    messages_processed = 0
    messages_skipped = 0
    messages_without_publication = 0
    publications_detected = 0
    publications_new = 0
    domain_stats = defaultdict(
        lambda: {
            "messages": 0,
            "messages_without_publication": 0,
            "publications_detected": 0,
        }
    )
    errors = []

    store = Store(database)
    try:
        with _readable_mbox(source_path) as readable_source:
            archive = mailbox.mbox(str(readable_source), create=False)
            try:
                for index, raw_message in enumerate(archive, start=1):
                    messages_total += 1
                    source_reference = "{}#{:06d}".format(source_path, index)
                    try:
                        message = parse_message_bytes(
                            raw_message.as_bytes(policy=policy.default)
                        )
                        domain = _sender_domain(message.sender)
                        domain_stats[domain]["messages"] += 1
                        domain_stats[domain]["publications_detected"] += len(
                            message.publications
                        )
                        publications_detected += len(message.publications)
                        if not message.publications:
                            messages_without_publication += 1
                            domain_stats[domain]["messages_without_publication"] += 1
                        if store.has_message(message.identity):
                            messages_skipped += 1
                            continue
                        publications_new += store.add_message(message, source_reference)
                        messages_processed += 1
                    except Exception as error:
                        errors.append("message {}: {}".format(index, error))
            finally:
                archive.close()

        publications = store.catalog_publications()
        publications_unique = store.publication_count()
        _write_catalog(catalog, publications)
    finally:
        store.close()

    report = ImportReport(
        messages_total=messages_total,
        messages_processed=messages_processed,
        messages_skipped=messages_skipped,
        messages_without_publication=messages_without_publication,
        publications_detected=publications_detected,
        publications_new=publications_new,
        publications_unique=publications_unique,
        sender_domains=dict(sorted(domain_stats.items())),
        errors=tuple(errors),
    )
    _write_report(report_output, report)
    return report
