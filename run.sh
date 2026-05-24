#!/bin/bash
set -e

PROJECT_DIR="/home/grimm/TCC/cheshiretalk-v2"
VENV_DIR="$PROJECT_DIR/.venv"

cd "$PROJECT_DIR"

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

if [ ! -f "$VENV_DIR/.installed" ] || [ "$VENV_DIR/.installed" -ot "requirements.txt" ]; then
    pip install --upgrade pip
    pip install -r requirements.txt
    touch "$VENV_DIR/.installed"
fi

export PYTHONPATH="$PROJECT_DIR:$PYTHONPATH"

echo "[INFO] PYTHONPATH: $PYTHONPATH"
echo "[INFO] Iniciando servidor..."
echo "[INFO] Acesse: http://localhost:8000"

exec python3 -m uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
