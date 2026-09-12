#!/usr/bin/env bash
set -eu

umask 077

INSTALL_DIR=${VEILLE_INSTALL_DIR:-/volume1/Bellegarde/veille-scientifique}
CONFIG_PATH=${VEILLE_CONFIG:-$INSTALL_DIR/veille-scientifique.ini}
DATABASE_PATH=${VEILLE_DATABASE:-$INSTALL_DIR/data/veille.sqlite}
SECRETS_ENV=${SECRETS_ENV:-$INSTALL_DIR/secrets.env}

if [ -z "${PYTHON_BIN:-}" ]; then
  PYTHON_BIN=$(command -v python3.9 2>/dev/null || command -v python3)
fi
if [ -z "${PYTHON_BIN:-}" ] || [ ! -x "$PYTHON_BIN" ]; then
  printf 'Python 3 introuvable. Définissez PYTHON_BIN avec son chemin absolu.\n' >&2
  exit 1
fi

cd "$INSTALL_DIR"
if [ -f "$SECRETS_ENV" ]; then
  . "$SECRETS_ENV"
fi
[ "${SCIENCE_DIGEST_MAIL_PASSWORD+x}" = x ] && export SCIENCE_DIGEST_MAIL_PASSWORD
[ "${SCIENCE_DIGEST_LINKEDIN_SECRET+x}" = x ] && export SCIENCE_DIGEST_LINKEDIN_SECRET

exec "$PYTHON_BIN" -m veille linkedin-worker \
  --config "$CONFIG_PATH" \
  --database "$DATABASE_PATH"
