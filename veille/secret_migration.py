import configparser
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from .atomic import atomic_open


MAIL_PASSWORD_ENVIRONMENT = "SCIENCE_DIGEST_MAIL_PASSWORD"
SMTP_PASSWORD_ENVIRONMENT = "SCIENCE_DIGEST_SMTP_PASSWORD"


@dataclass(frozen=True)
class SecretMigrationReport:
    config: str
    secrets: str
    migrated: bool
    errors: tuple = ()

    def as_dict(self):
        return {
            "service": "secret-migration",
            "status": "ok",
            "config": self.config,
            "secrets": self.secrets,
            "migrated": self.migrated,
            "errors": [],
        }


def _atomic_write(path, content):
    path = Path(path)
    with atomic_open(
        path, "w", encoding="utf-8", permissions=0o600
    ) as stream:
        stream.write(content)


def _config_without_inline_passwords(content, replacements):
    output = []
    current_section = None
    inserted = set()
    for line in content.splitlines(keepends=True):
        section = re.match(r"^\s*\[([^]]+)\]", line)
        if section:
            current_section = section.group(1).strip().casefold()
        if current_section not in replacements:
            output.append(line)
            continue
        if re.match(r"^\s*password_env\s*=", line, re.IGNORECASE):
            continue
        if re.match(r"^\s*password\s*=", line, re.IGNORECASE):
            if current_section not in inserted:
                indentation = line[: len(line) - len(line.lstrip())]
                output.append(
                    "{}password_env = {}\n".format(
                        indentation, replacements[current_section]
                    )
                )
                inserted.add(current_section)
            continue
        output.append(line)
    missing = set(replacements) - inserted
    if missing:
        raise ValueError(
            "Option password inline introuvable pendant la migration : {}.".format(
                ", ".join(sorted(missing))
            )
        )
    return "".join(output)


def _secrets_with_mail_passwords(content, passwords):
    environment_names = set(passwords)
    retained = [
        line
        for line in content.splitlines()
        if not any(
            re.match(r"^\s*{}=".format(re.escape(name)), line)
            for name in environment_names
        )
    ]
    for environment_name, password in passwords.items():
        retained.append("{}={}".format(environment_name, shlex.quote(password)))
    return "\n".join(retained) + "\n"


def migrate_inline_mail_password(config_path, secrets_path):
    config_path = Path(config_path)
    secrets_path = Path(secrets_path)
    if config_path.resolve() == secrets_path.resolve():
        raise ValueError(
            "La configuration et le fichier de secrets doivent être distincts."
        )
    if not config_path.is_file():
        raise ValueError(
            "Fichier de configuration introuvable : {}".format(config_path)
        )

    content = config_path.read_text(encoding="utf-8")
    config = configparser.ConfigParser(interpolation=None)
    try:
        config.read_string(content)
    except configparser.Error:
        raise ValueError("La configuration INI est invalide.") from None
    replacements = {}
    passwords = {}
    for section, environment_name in (
        ("imap", MAIL_PASSWORD_ENVIRONMENT),
        ("smtp", SMTP_PASSWORD_ENVIRONMENT),
    ):
        if not config.has_option(section, "password"):
            continue
        password = config.get(section, "password", fallback="").strip()
        if not password:
            raise ValueError(
                "Option {}.password vide ; migration impossible.".format(section)
            )
        replacements[section] = environment_name
        passwords[environment_name] = password

    if not replacements:
        os.chmod(str(config_path), 0o600)
        if secrets_path.exists():
            os.chmod(str(secrets_path), 0o600)
        return SecretMigrationReport(
            config=str(config_path), secrets=str(secrets_path), migrated=False
        )

    secrets_content = (
        secrets_path.read_text(encoding="utf-8") if secrets_path.exists() else ""
    )
    _atomic_write(
        secrets_path, _secrets_with_mail_passwords(secrets_content, passwords)
    )
    _atomic_write(
        config_path, _config_without_inline_passwords(content, replacements)
    )
    return SecretMigrationReport(
        config=str(config_path), secrets=str(secrets_path), migrated=True
    )
