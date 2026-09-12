"""Relève les demandes LinkedIn et prépare leurs sources sans relancer le digest."""
from dataclasses import dataclass

from .article_pdf import OpenAccessPdfFetcher
from .imap_sync import run_imap_sync
from .linkedin_bridge import load_linkedin_settings
from .linkedin_import import run_linkedin_import


@dataclass(frozen=True)
class LinkedinWorkerReport:
    sync_report: object
    import_report: object

    @property
    def errors(self):
        import_errors = tuple(
            self.import_report.warnings
            if self.import_report.rejected
            else ()
        )
        return tuple(self.sync_report.errors) + import_errors

    def as_dict(self):
        return {
            "service": "linkedin-worker",
            "status": "ok" if not self.errors else "partial",
            "sync": self.sync_report.as_dict(),
            "import": self.import_report.as_dict(),
            "errors": list(self.errors),
        }


def run_linkedin_worker(config_path, database, imap_factory=None, http_opener=None):
    settings = load_linkedin_settings(config_path)
    if settings is None:
        raise ValueError("Le transfert LinkedIn est désactivé dans [linkedin].")
    missing = [
        name
        for name, value in (
            ("linkedin.inbox", settings.inbox),
            ("linkedin.output", settings.output),
            ("linkedin.authorized_sender", settings.authorized_sender),
        )
        if not value
    ]
    if missing:
        raise ValueError("Configuration LinkedIn incomplète : {}.".format(", ".join(missing)))
    sync_report = run_imap_sync(
        config_path,
        settings.inbox,
        database,
        limit=settings.sync_limit,
        initial_mode="all",
        client_factory=imap_factory,
        folder=settings.folder,
    )
    fetcher = (
        OpenAccessPdfFetcher(
            settings.recipient,
            max_bytes=settings.max_pdf_mb * 1024 * 1024,
            opener=http_opener,
        )
        if settings.download_pdf
        else None
    )
    import_report = run_linkedin_import(
        settings.inbox,
        database,
        settings.output,
        authorized_sender=settings.authorized_sender,
        token_secret=settings.token_secret,
        pdf_fetcher=fetcher,
    )
    return LinkedinWorkerReport(sync_report, import_report)
