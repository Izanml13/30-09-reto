#!/usr/bin/env bash
# =============================================================
# generate_audios.sh
# Genera los 3 audios de prueba en español usando el sintetizador
# nativo de macOS (`say`) y los convierte a WAV PCM 16 kHz mono.
#
# El texto de cada audio queda registrado en audios/ground_truth.json
# como "verdad terreno" para medir el WER (Word Error Rate) de cada
# metodo de transcripcion.
# =============================================================
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$DIR/audios"
mkdir -p "$OUT"

# Formato objetivo: WAV PCM signed 16-bit little-endian, mono, 16000 Hz
# (16 kHz mono es lo que espera el endpoint de audio de Gemini).
DATA_FORMAT="LEI16@16000"
FILE_FORMAT="WAVE"

gen () {
  local file="$1" voice="$2" rate="$3" text="$4"
  local tmp
  tmp="$(mktemp -t speechXXXX).wav"

  # `say` exige --file-format=WAVE cuando se pasa --data-format.
  # Se sintetiza a 22050 Hz y despues afconvert remuestrea a 16000 Hz mono.
  echo "[*] Generando $OUT/$file  (voz: $voice, ritmo: $rate)"
  say -v "$voice" -r "$rate" -o "$tmp" \
      --file-format="$FILE_FORMAT" --data-format=LEI16@22050 "$text"

  afconvert -f "$FILE_FORMAT" -d "$DATA_FORMAT" -c 1 "$tmp" "$OUT/$file"
  rm -f "$tmp"

  afinfo "$OUT/$file" | awk -F': *' '/File format ID|Duration|^[0-9]+ ch/{printf "    %s\n",$2}'
}

# -------------------------------------------------------------
# Audio 1 - frase corta, sin diacriticos complejos.
# Objetivo: medir precision base con frase sencilla.
# -------------------------------------------------------------
gen "audio1_frase_corta.wav" "Mónica" 165 \
  "Hola, hoy voy a probar el sistema de transcripción de voz."

# -------------------------------------------------------------
# Audio 2 - numeros, horas y acentos.
# Es el caso clasico donde los STT fallan (cifras, "y media").
# Objetivo: medir precision con contenido numerico.
# -------------------------------------------------------------
gen "audio2_numeros_hora.wav" "Paulina" 175 \
  "El pedido número cuarenta y cinco llegó a las tres y media de la tarde."

# -------------------------------------------------------------
# Audio 3 - frase larga con enfasis yIPLE y punto y coma.
# Objetivo: medir precision con enunciado complejo y respira-
# ciones, tipico de locucion comercial.
# -------------------------------------------------------------
gen "audio3_frase_larga.wav" "Eddy" 150 \
  "La reunión del comité; ciento veinte personas; se pospone porque el presupuesto anual necesita una revisión completa antes de aprobarlo."

cat <<'JSON' > "$OUT/ground_truth.json"
{
  "nota": "Verdad terreno generada por scripts/generate_audios.sh. El texto es exacto porque 'say' sintetiza un texto que ya conocemos.",
  "idioma": "es-ES",
  "audios": [
    {
      "id": "audio1_frase_corta",
      "archivo": "audio1_frase_corta.wav",
      "voz": "Mónica (es_ES)",
      "ritmo_wpm": 165,
      "nivel": "facil",
      "referencia": "Hola, hoy voy a probar el sistema de transcripción de voz."
    },
    {
      "id": "audio2_numeros_hora",
      "archivo": "audio2_numeros_hora.wav",
      "voz": "Paulina (es_MX)",
      "ritmo_wpm": 175,
      "nivel": "dificil",
      "referencia": "El pedido número cuarenta y cinco llegó a las tres y media de la tarde."
    },
    {
      "id": "audio3_frase_larga",
      "archivo": "audio3_frase_larga.wav",
      "voz": "Eddy (es_ES)",
      "ritmo_wpm": 150,
      "nivel": "dificil",
      "referencia": "La reunión del comité; ciento veinte personas; se pospone porque el presupuesto anual necesita una revisión completa antes de aprobarlo."
    }
  ]
}
JSON

echo
echo "[OK] 3 audios generados + audios/ground_truth.json"
ls -la "$OUT"
