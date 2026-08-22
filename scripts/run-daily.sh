#!/usr/bin/env bash
set -eu

umask 077

VEILLE_ROOT=${VEILLE_ROOT:-/volume1/Bellegarde/veille-scientifique}
PYTHON_BIN=${PYTHON_BIN:-/var/packages/py3k/target/usr/local/bin/python3}
CONFIG_PATH=${CONFIG_PATH:-$VEILLE_ROOT/veille-scientifique.ini}
SECRETS_ENV=${SECRETS_ENV:-$VEILLE_ROOT/secrets.env}
OPENAI_ENV=${OPENAI_ENV:-$VEILLE_ROOT/openai.env}

cd "$VEILLE_ROOT"

if [ -f "$OPENAI_ENV" ]; then
    # Compatibilité avec les installations antérieures.
    . "$OPENAI_ENV"
fi
if [ -f "$SECRETS_ENV" ]; then
    # Fichier local en mode 600, jamais versionné. Ses valeurs sont prioritaires.
    . "$SECRETS_ENV"
fi

[ "${SCIENCE_DIGEST_MAIL_PASSWORD+x}" = x ] && export SCIENCE_DIGEST_MAIL_PASSWORD
[ "${SCIENCE_DIGEST_SMTP_PASSWORD+x}" = x ] && export SCIENCE_DIGEST_SMTP_PASSWORD
[ "${OPENAI_API_KEY+x}" = x ] && export OPENAI_API_KEY

exec "$PYTHON_BIN" -m veille daily --config "$CONFIG_PATH"
