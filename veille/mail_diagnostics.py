import configparser
import imaplib
import socket
import smtplib
import ssl
from contextlib import contextmanager
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path


SYSTEM_CA_FILES = (
    "/etc/ssl/cert.pem",
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/pki/tls/certs/ca-bundle.crt",
)


class MailDiagnosticError(RuntimeError):
    pass


@dataclass(frozen=True)
class IMAPSettings:
    host: str
    port: int
    username: str
    password: str
    folder: str


@dataclass(frozen=True)
class IMAPDiagnosticReport:
    host: str
    port: int
    folder: str
    messages: int

    def as_dict(self):
        return {
            "service": "imap",
            "status": "ok",
            "host": self.host,
            "port": self.port,
            "folder": self.folder,
            "messages": self.messages,
        }


@dataclass(frozen=True)
class SMTPSettings:
    host: str
    port: int
    username: str
    password: str
    security: str
    from_address: str
    test_recipient: str


@dataclass(frozen=True)
class SMTPDiagnosticReport:
    host: str
    port: int
    security: str
    recipient: str
    test_message_sent: bool

    def as_dict(self):
        return {
            "service": "smtp",
            "status": "ok",
            "host": self.host,
            "port": self.port,
            "security": self.security,
            "test_message_sent": self.test_message_sent,
            "recipient": self.recipient,
        }


@contextmanager
def _socket_timeout(seconds):
    previous = socket.getdefaulttimeout()
    socket.setdefaulttimeout(seconds)
    try:
        yield
    finally:
        socket.setdefaulttimeout(previous)


def create_tls_context():
    context = ssl.create_default_context()
    if context.cert_store_stats().get("x509_ca", 0) > 0:
        return context
    for candidate in SYSTEM_CA_FILES:
        if Path(candidate).is_file():
            return ssl.create_default_context(cafile=candidate)
    raise RuntimeError(
        "Aucun certificat racine système n’est disponible. "
        "Configurez SSL_CERT_FILE vers un bundle CA valide."
    )


def _safe_error(error, password):
    message = str(error)
    if password:
        message = message.replace(password, "[secret masqué]")
    return message


def _required(config, section, option):
    if not config.has_section(section):
        raise ValueError("Section [{}] absente de la configuration.".format(section))
    value = config.get(section, option, fallback="").strip()
    if not value:
        raise ValueError("Option {}.{} absente de la configuration.".format(section, option))
    return value


def _port(config, section, default):
    raw = config.get(section, "port", fallback=str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        raise ValueError("Le port {} doit être un entier.".format(section))
    if value < 1 or value > 65535:
        raise ValueError("Le port {} doit être compris entre 1 et 65535.".format(section))
    return value


def _load_config(path):
    source = Path(path)
    if not source.exists() or not source.is_file():
        raise ValueError("Fichier de configuration introuvable : {}".format(source))
    config = configparser.ConfigParser(interpolation=None)
    try:
        with source.open(encoding="utf-8") as stream:
            config.read_file(stream)
    except configparser.Error:
        raise ValueError("La configuration INI est invalide.") from None
    except UnicodeError:
        raise ValueError("La configuration INI doit être encodée en UTF-8.") from None
    except OSError:
        raise ValueError(
            "Le fichier de configuration ne peut pas être lu : {}".format(source)
        ) from None
    return config


def load_imap_settings(path):
    config = _load_config(path)
    return IMAPSettings(
        host=_required(config, "imap", "host"),
        port=_port(config, "imap", 993),
        username=_required(config, "imap", "username"),
        password=_required(config, "imap", "password"),
        folder=config.get("imap", "folder", fallback="INBOX").strip() or "INBOX",
    )


def load_smtp_settings(path):
    config = _load_config(path)
    imap_host = _required(config, "imap", "host")
    imap_username = _required(config, "imap", "username")
    imap_password = _required(config, "imap", "password")
    if config.has_section("smtp"):
        host = config.get("smtp", "host", fallback=imap_host).strip() or imap_host
        port = _port(config, "smtp", 587)
        username = (
            config.get("smtp", "username", fallback=imap_username).strip()
            or imap_username
        )
        password = config.get("smtp", "password", fallback=imap_password).strip()
        security = config.get("smtp", "security", fallback="starttls").strip().lower()
        from_address = (
            config.get("smtp", "from_address", fallback=username).strip() or username
        )
        test_recipient = (
            config.get("smtp", "test_recipient", fallback=username).strip()
            or username
        )
    else:
        host = imap_host
        port = 587
        username = imap_username
        password = imap_password
        security = "starttls"
        from_address = username
        test_recipient = username
    if not password:
        raise ValueError("Option smtp.password absente de la configuration.")
    if security != "starttls":
        raise ValueError("La sécurité SMTP prise en charge est starttls.")
    return SMTPSettings(
        host=host,
        port=port,
        username=username,
        password=password,
        security=security,
        from_address=from_address,
        test_recipient=test_recipient,
    )


def run_imap_diagnostic(config_path, client_factory=None):
    settings = load_imap_settings(config_path)
    factory = client_factory or imaplib.IMAP4_SSL
    client = None
    try:
        with _socket_timeout(15):
            client = factory(
                settings.host,
                settings.port,
                ssl_context=create_tls_context(),
            )
        client.login(settings.username, settings.password)
        status, data = client.select(settings.folder, readonly=True)
        if status != "OK":
            raise RuntimeError("La boîte IMAP n’a pas pu être ouverte en lecture seule.")
        try:
            message_count = int(data[0]) if data and data[0] is not None else 0
        except (TypeError, ValueError):
            message_count = 0
        return IMAPDiagnosticReport(
            host=settings.host,
            port=settings.port,
            folder=settings.folder,
            messages=message_count,
        )
    except Exception as error:
        raise MailDiagnosticError(_safe_error(error, settings.password)) from None
    finally:
        if client is not None:
            try:
                client.logout()
            except Exception:
                pass


def run_smtp_diagnostic(config_path, send_test=False, client_factory=None):
    settings = load_smtp_settings(config_path)
    factory = client_factory or smtplib.SMTP
    client = None
    try:
        client = factory(settings.host, settings.port, timeout=15)
        client.ehlo()
        client.starttls(context=create_tls_context())
        client.ehlo()
        client.login(settings.username, settings.password)
        if send_test:
            message = EmailMessage()
            message["From"] = settings.from_address
            message["To"] = settings.test_recipient
            message["Subject"] = "[Bellegarde] Test de connexion science-digest"
            message.set_content(
                "Test de connexion SMTP réussi pour la veille scientifique Bellegarde."
            )
            client.send_message(message)
        return SMTPDiagnosticReport(
            host=settings.host,
            port=settings.port,
            security=settings.security,
            recipient=settings.test_recipient,
            test_message_sent=send_test,
        )
    except Exception as error:
        raise MailDiagnosticError(_safe_error(error, settings.password)) from None
    finally:
        if client is not None:
            try:
                client.quit()
            except Exception:
                pass
