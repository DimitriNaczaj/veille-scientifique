#!/usr/bin/env bash
set -eu

umask 077

VEILLE_ROOT=${VEILLE_ROOT:-/volume1/Bellegarde/veille-scientifique}
CONFIG_PATH=${CONFIG_PATH:-$VEILLE_ROOT/veille-scientifique.ini}
SECRETS_ENV=${SECRETS_ENV:-$VEILLE_ROOT/secrets.env}
OPENAI_ENV=${OPENAI_ENV:-$VEILLE_ROOT/openai.env}

if [ -z "${PYTHON_BIN:-}" ]; then
    for candidate in \
        "$(command -v python3.9 2>/dev/null || true)" \
        "$(command -v python3 2>/dev/null || true)" \
        /var/packages/Python3.9/target/usr/local/bin/python3.9 \
        /var/packages/py3k/target/usr/local/bin/python3; do
        if [ -n "$candidate" ] && [ -x "$candidate" ] && \
            "$candidate" -c \
                'import imaplib, json, sqlite3, ssl, smtplib, sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)' \
                >/dev/null 2>&1; then
            PYTHON_BIN=$candidate
            break
        fi
    done
fi

if [ -z "${PYTHON_BIN:-}" ] || [ ! -x "$PYTHON_BIN" ]; then
    printf 'Python 3 introuvable. Définissez PYTHON_BIN avec son chemin absolu.\n' >&2
    exit 1
fi

cd "$VEILLE_ROOT"

if [ -f "$OPENAI_ENV" ]; then
    . "$OPENAI_ENV"
fi
if [ -f "$SECRETS_ENV" ]; then
    . "$SECRETS_ENV"
fi

[ "${SCIENCE_DIGEST_MAIL_PASSWORD+x}" = x ] && export SCIENCE_DIGEST_MAIL_PASSWORD
[ "${SCIENCE_DIGEST_SMTP_PASSWORD+x}" = x ] && export SCIENCE_DIGEST_SMTP_PASSWORD
[ "${OPENAI_API_KEY+x}" = x ] && export OPENAI_API_KEY

exec "$PYTHON_BIN" -m veille backfill-daily \
    --config "$CONFIG_PATH" \
    --format human
