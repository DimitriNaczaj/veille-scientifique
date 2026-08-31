import os
from dataclasses import dataclass

from .ai import OpenAIAnalyzer
from .crossref import CrossrefClient
from .delivery import SMTPDigestSender
from .elsevier import elsevier_client_from_config
from .europepmc import europepmc_client_from_config
from .openalex import openalex_client_from_config
from .filtering import BehavioralScienceFilter
from .feedback import load_feedback_settings, run_feedback_import
from .imap_sync import run_imap_sync
from .mail_diagnostics import _load_config, load_imap_settings
from .pipeline import run_pipeline
from .publisher_pages import MetadataCascade, PublisherPageClient


@dataclass(frozen=True)
class DailyReport:
    sync_report: object
    pipeline_report: object
    ai_enabled: bool
    email_sent: bool
    recipient: object
    daily_warnings: tuple
    feedback_sync_report: object = None
    feedback_import_report: object = None

    @property
    def errors(self):
        feedback_errors = (
            tuple(self.feedback_sync_report.errors)
            if self.feedback_sync_report is not None
            else ()
        )
        return (
            feedback_errors
            + tuple(self.sync_report.errors)
            + tuple(self.pipeline_report.errors)
        )

    def as_dict(self):
        return {
            "service": "daily",
            "status": "ok" if not self.errors else "partial",
            "sync": self.sync_report.as_dict(),
            "feedback": (
                {
                    "enabled": True,
                    "sync": self.feedback_sync_report.as_dict(),
                    "import": self.feedback_import_report.as_dict(),
                }
                if self.feedback_sync_report is not None
                else {"enabled": False}
            ),
            "pipeline": self.pipeline_report.as_dict(),
            "ai_enabled": self.ai_enabled,
            "email_sent": self.email_sent,
            "recipient": self.recipient,
            "warnings": list(self.daily_warnings),
            "errors": list(self.errors),
        }


def _app_path(config, option, override):
    if override:
        return override
    if not config.has_section("app"):
        raise ValueError("Section [app] absente de la configuration.")
    value = config.get("app", option, fallback="").strip()
    if not value:
        raise ValueError("Option app.{} absente de la configuration.".format(option))
    return value


def _app_limit(config, option, override, default):
    if override is not None:
        return override
    if not config.has_section("app"):
        return default
    try:
        return config.getint("app", option, fallback=default)
    except ValueError:
        raise ValueError("Option app.{} invalide.".format(option)) from None


def run_daily(
    config_path,
    inbox=None,
    database=None,
    output=None,
    sync_limit=None,
    initial_mode=None,
    enrichment_limit=None,
    ai_limit=None,
    no_ai=False,
    no_send=False,
    no_feedback=False,
    imap_factory=None,
    smtp_factory=None,
    http_opener=None,
    ai_opener=None,
):
    config = _load_config(config_path)
    inbox = _app_path(config, "inbox", inbox)
    database = _app_path(config, "database", database)
    output = _app_path(config, "output", output)
    sync_limit = _app_limit(config, "sync_limit", sync_limit, 200)
    if initial_mode is None:
        initial_mode = config.get(
            "imap", "initial_mode", fallback="latest"
        ).strip().lower() or "latest"
    enrichment_limit = _app_limit(
        config, "enrichment_limit", enrichment_limit, 100
    )
    ai_limit = _app_limit(config, "ai_limit", ai_limit, 30)

    imap = load_imap_settings(config_path)
    contact_email = os.environ.get("CROSSREF_EMAIL")
    if config.has_section("app"):
        contact_email = (
            config.get("app", "crossref_email", fallback=contact_email or "").strip()
            or contact_email
        )
    contact_email = contact_email or imap.username
    metadata_provider = MetadataCascade(
        CrossrefClient(contact_email=contact_email, opener=http_opener),
        PublisherPageClient(opener=http_opener),
        elsevier_client=elsevier_client_from_config(
            config,
            opener=http_opener,
        ),
        openalex_client=openalex_client_from_config(config, opener=http_opener),
        europepmc_client=europepmc_client_from_config(config, opener=http_opener),
    )

    warnings = []
    feedback_settings = None if no_feedback else load_feedback_settings(config_path)
    analysis_provider = None
    ai_enabled = not no_ai
    if config.has_section("ai"):
        try:
            ai_enabled = ai_enabled and config.getboolean(
                "ai", "enabled", fallback=True
            )
        except ValueError:
            raise ValueError("Option ai.enabled invalide.") from None
    if ai_enabled:
        key_environment = (
            config.get("ai", "api_key_env", fallback="OPENAI_API_KEY").strip()
            if config.has_section("ai")
            else "OPENAI_API_KEY"
        ) or "OPENAI_API_KEY"
        api_key = os.environ.get(key_environment)
        if not api_key:
            ai_enabled = False
            warnings.append(
                "IA désactivée : variable {} absente ; préfiltre local utilisé.".format(
                    key_environment
                )
            )
        else:
            model = (
                config.get("ai", "model", fallback="gpt-5.6-luna").strip()
                if config.has_section("ai")
                else "gpt-5.6-luna"
            ) or "gpt-5.6-luna"
            analysis_provider = OpenAIAnalyzer(
                api_key=api_key,
                model=model,
                opener=ai_opener,
            )

    delivery_handler = None
    if not no_send:
        delivery_handler = SMTPDigestSender(
            config_path,
            smtp_factory=smtp_factory,
        )

    feedback_sync_report = None
    feedback_import_report = None
    if feedback_settings is not None:
        feedback_sync_report = run_imap_sync(
            config_path,
            feedback_settings.inbox,
            database,
            limit=feedback_settings.sync_limit,
            initial_mode="latest",
            client_factory=imap_factory,
            folder=feedback_settings.folder,
        )
        feedback_import_report = run_feedback_import(
            feedback_settings.inbox,
            database,
            authorized_sender=feedback_settings.authorized_sender,
            token_secret=feedback_settings.token_secret,
        )
        warnings.extend(feedback_import_report.warnings)

    sync_report = run_imap_sync(
        config_path,
        inbox,
        database,
        limit=sync_limit,
        initial_mode=initial_mode,
        client_factory=imap_factory,
    )
    pipeline_report = run_pipeline(
        inbox,
        database,
        output,
        metadata_provider=metadata_provider,
        relevance_filter=BehavioralScienceFilter(),
        enrichment_limit=enrichment_limit,
        analysis_provider=analysis_provider,
        ai_limit=ai_limit,
        delivery_handler=delivery_handler,
        feedback_settings=feedback_settings,
    )
    return DailyReport(
        sync_report=sync_report,
        pipeline_report=pipeline_report,
        ai_enabled=ai_enabled,
        email_sent=bool(delivery_handler and delivery_handler.sent),
        recipient=delivery_handler.recipient if delivery_handler else None,
        daily_warnings=tuple(warnings),
        feedback_sync_report=feedback_sync_report,
        feedback_import_report=feedback_import_report,
    )
