#!/usr/bin/env bash
# =============================================================
# capturar_webspeech_automatica.sh
# =============================================================
# Mide la Web Speech API sobre los 3 audios de prueba SIN hablar:
# Chrome usa cada WAV como microfono virtual mediante el flag
# --use-file-for-fake-audio-capture, y la pagina web/captura_webspeech.html
# archiva la transcripcion en resultados/webspeech.json.
#
# Requisitos:
#   - Google Chrome instalado (/Applications/Google Chrome.app)
#   - Python 3
#   - macOS: permisos de microfono concedidos a Chrome la 1a vez
#
# Uso:
#   ./scripts/capturar_webspeech_automatica.sh
#   ./scripts/capturar_webspeech_automatica.sh audio2_numeros_hora
# =============================================================
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

PORT="${STT_PORT:-5000}"
URL_BASE="http://127.0.0.1:${PORT}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PERFIL="$(mktemp -d -t sttchromeXXXX)"

# -------------------------------------------------------------
# 1. Comprobaciones
# -------------------------------------------------------------
if [[ ! -x "$CHROME" ]]; then
  echo "[ERROR] No se encuentra Google Chrome en:"
  echo "        $CHROME"
  echo
  echo "Instálalo con:  brew install --cask google-chrome"
  echo "Alternativa: captura manual siguiendo docs/COMO_CAPTURAR_WEBSPEECH.md"
  exit 1
fi

if ! curl -s -o /dev/null --max-time 3 "$URL_BASE/api/health"; then
  echo "[ERROR] El servidor no responde en $URL_BASE"
  echo "        Arráncalo en otra terminal con:  python run.py"
  exit 1
fi

# -------------------------------------------------------------
# 2. Audios a capturar
# -------------------------------------------------------------
if [[ $# -gt 0 ]]; then
  IDS=("$@")
else
  IDS=(audio1_frase_corta audio2_numeros_hora audio3_frase_larga)
fi

# -------------------------------------------------------------
# 3. Captura
# -------------------------------------------------------------
echo "============================================================="
echo " Captura automatica de la Web Speech API"
echo "============================================================="
echo

for id in "${IDS[@]}"; do
  wav="audios/${id}.wav"
  if [[ ! -f "$wav" ]]; then
    echo "[AVISO] No existe $wav; se omite '$id'."
    continue
  fi

  # El WAV debe existir y ser WAV PCM: Chrome no acepta otro formato aqui.
  if ! afinfo "$wav" >/dev/null 2>&1; then
    echo "[AVISO] $wav no es un WAV valido; se omite '$id'."
    continue
  fi

  echo "[*] Capturando: $id"
  echo "    (Chrome se abrira ~35 s. No interactues con la ventana.)"

  "$CHROME" \
    --user-data-dir="$PERFIL" \
    --no-first-run \
    --no-default-browser-check \
    --use-fake-device-for-media-stream \
    --use-file-for-fake-audio-capture="$(pwd)/$wav" \
    "$URL_BASE/captura_webspeech.html?id=${id}&auto=1" \
    >/dev/null 2>&1 &

  CHROME_PID=$!

  # Espera activa: hasta 60 s a que el servidor registre el resultado.
  ok=0
  for _ in $(seq 1 60); do
    if [[ -f resultados/webspeech.json ]] && \
       grep -q "\"$id\"" resultados/webspeech.json 2>/dev/null; then
      ok=1
      break
    fi
    sleep 1
  done

  # Se espera a que el proceso de Chrome termine por si mismo.
  for _ in $(seq 1 15); do
    kill -0 "$CHROME_PID" 2>/dev/null || break
    sleep 1
  done
  kill "$CHROME_PID" 2>/dev/null || true
  wait "$CHROME_PID" 2>/dev/null || true

  if [[ $ok -eq 1 ]]; then
    echo "    [OK] Transcripcion registrada."
  else
    echo "    [AVISO] No se registro nada. Causas habituales:"
    echo "            · Chrome pidio permiso de microfono: aceptalo en el candado."
    echo "            · El WAV debe ser PCM mono 16 kHz (lo genera generate_audios.sh)."
    echo "            · La Web Speech API necesita conexion a Internet."
  fi
  echo
done

rm -rf "$PERFIL"

# -------------------------------------------------------------
# 4. Informe
# -------------------------------------------------------------
echo "============================================================="
if [[ -f resultados/webspeech.json ]]; then
  echo " Resultados guardados en resultados/webspeech.json"
  echo ""
  echo " Siguiente paso:"
  echo "   python scripts/evaluate.py --endpoint $URL_BASE"
else
  echo " No se capturo ninguna transcripcion."
  echo " Consulta docs/COMO_CAPTURAR_WEBSPEECH.md para la via manual."
fi
echo "============================================================="
