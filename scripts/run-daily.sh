#!/bin/sh
set -eu

umask 077

VEILLE_ROOT=${VEILLE_ROOT:-/volume1/Bellegarde/veille-scientifique}
PYTHON_BIN=${PYTHON_BIN:-/var/packages/py3k/target/usr/local/bin/python3}
CONFIG_PATH=${CONFIG_PATH:-$VEILLE_ROOT/veille-scientifique.ini}
OPENAI_ENV=${OPENAI_ENV:-$VEILLE_ROOT/openai.env}

cd "$VEILLE_ROOT"

if [ -f "$OPENAI_ENV" ]; then
    # Fichier local en mode 600 contenant uniquement OPENAI_API_KEY=...
    . "$OPENAI_ENV"
    export OPENAI_API_KEY
fi

exec "$PYTHON_BIN" -m veille daily --config "$CONFIG_PATH"
