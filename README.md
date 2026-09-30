# Reto del día · Speech-to-Text (ASIX)

Implementación de los dos métodos de transcripción del reto y de la
comparativa de precisión entre ellos.

- **Opción A — Web Speech API**: transcripción en tiempo real en el navegador,
  sin API key.
- **Opción B — Gemini**: endpoint Flask que recibe audio, lo envía a Gemini y
  devuelve el texto (formato de entrega ASIX).

Incluye 3 audios de prueba en español con verdad terreno conocida y una
métrica de precisión (WER) compartida por ambos métodos.

> **Estado actual:** Gemini está bloqueado por Google en esta máquina
> (403 *Your project has been denied access*), aunque la API key es válida.
> El cliente de Gemini está implementado y probado; cuando haya una key de
> un proyecto operativo, la comparativa se completa sin tocar código. Ver
> [`docs/COMPARATIVA.md`](docs/COMPARATIVA.md) §4.

---

## Puesta en marcha

```bash
cd speech-to-text
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 1. Generar los 3 audios de prueba (+ su verdad terreno)
./scripts/generate_audios.sh

# 2. Arrancar el servicio
python run.py
```

Abre <http://127.0.0.1:5000>.

### Configuración

La clave se lee de `~/.env` y del `.env` del proyecto (el del proyecto tiene
prioridad), así que **no hace falta copiar el secreto al repositorio**:

```bash
cp .env.example .env     # opcional, para configuración propia
```

| Variable | Por defecto | Para qué |
|---|---|---|
| `GEMINI_API_KEY` | *(vacía)* | Credencial. Sin ella se usa el proveedor `mock` |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Modelo. Alternativa: `gemini-3.5-transcribe` |
| `STT_HOST` / `STT_PORT` | `127.0.0.1` / `5000` | Bind y puerto |
| `STT_MAX_UPLOAD_MB` | `25` | Tamaño máximo de audio |
| `STT_ALLOW_MOCK_FALLBACK` | `true` | Si Gemini falla, responder con `mock` |

---

## Uso

### Opción A — Web Speech API

En <http://127.0.0.1:5000>, panel **A**: pulsa «Empezar a escuchar» y habla en
español. El texto aparece provisional mientras hablas y se consolida al
detenerse.

Requiere un navegador con `SpeechRecognition` (Chromium). Si no está
disponible, el panel lo indica en lugar de fallar en silencio.

Para capturar transcripciones de forma archivable, usa
[`web/captura_webspeech.html`](web/captura_webspeech.html).

### Opción B — Endpoint

```bash
curl -X POST -F "audio=@audios/audio1_frase_corta.wav" \
         -F "language=es-ES" -F "provider=gemini" \
         http://127.0.0.1:5000/api/transcribe
```

| Endpoint | Función |
|---|---|
| `GET /api/health` | Estado del servicio y **sondeo real** de Gemini |
| `GET /api/providers` | Proveedores registrados |
| `GET /api/groundtruth` | Verdad terreno de los audios |
| `POST /api/transcribe` | Audio → texto |
| `POST /api/evaluate` | WER de una transcripción |
| `POST /api/report/webspeech` | Archiva una transcripción del navegador |

---

## Evaluación

```bash
# Arranca el servidor en otra terminal:  python run.py

python scripts/evaluate.py --endpoint http://127.0.0.1:5000
```

Genera `resultados/informe.md` y `resultados/informe.json`. Para incluir la
columna de la Web Speech API, captura primero sus transcripciones siguiendo
[`docs/COMO_CAPTURAR_WEBSPEECH.md`](docs/COMO_CAPTURAR_WEBSPEECH.md):

```bash
python scripts/evaluate.py --endpoint http://127.0.0.1:5000 \
    --webspeech resultados/webspeech.json
```

Con `--offline` no hace falta servidor y se reevalúa lo ya capturado.

El WER se calcula con `app/metrics.py`, el mismo módulo que usa la web y los
tests, de modo que las tres rutas no puedan divergir.

### Metodología de la verdad terreno

Los 3 audios se generan con el sintetizador `say` de macOS a partir de un
texto que ya se conoce, por lo que la transcripción ideal es exacta:

| Audio | Voz | Qué mide |
|---|---|---|
| `audio1_frase_corta` | Mónica (es_ES) | Caso fácil, frase corta |
| `audio2_numeros_hora` | Paulina (es_MX) | Cifras y horas: el punto crítico |
| `audio3_frase_larga` | Eddy (es_ES) | Enunciado largo: errores acumulados |

Antes de comparar, el texto se normaliza (minúsculas, sin acentos ni
puntuación) para que un `,` frente a un `.` no cuente como error.

---

## Estructura

```
speech-to-text/
├── app/
│   ├── main.py              # Application Factory
│   ├── config.py            # configuración por entorno
│   ├── audio_utils.py       # validación y normalización a WAV 16 kHz mono
│   ├── metrics.py           # WER (Levenshtein con desglose S/B/I)
│   ├── providers/
│   │   ├── base.py          # interfaz Transcriber + TranscriptionResult
│   │   ├── gemini.py        # Gemini real
│   │   └── mock.py          # reserva, etiquetado como no real
│   └── routes/api.py        # endpoints HTTP
├── web/
│   ├── index.html           # interfaz con los dos métodos
│   └── captura_webspeech.html
├── scripts/
│   ├── generate_audios.sh   # audios de prueba + verdad terreno
│   ├── diagnose_gemini.py   # diagnóstico de la conexión con Gemini
│   └── evaluate.py          # comparativa y WER
├── audios/                  # 3 .wav de prueba + ground_truth.json
├── docs/
│   ├── ARQUITECTURA_RED.md  # arquitectura de red (ASIX)
│   └── COMPARATIVA.md       # ventajas/desventajas y resultados
└── tests/                   # 48 tests
```

### Por qué un proveedor `mock`

El reto pide un endpoint que envíe audio a Gemini. Como la credencial está
bloqueada, el endpoint debe seguir siendo demostrable. `MockTranscriber`
mantiene el flujo de extremo a extremo, pero **no se hace pasar por una
transcripción**:

- `provider: "mock"` y `is_fallback: true` en cada respuesta.
- `warning` que explica por qué y desaconseja medir precisión con ella.
- `raw.not_a_real_transcription: true`.
- `evaluate.py` lo marca **no evaluable** en lugar de imprimir un WER.

Un simulador que devolviera el texto de referencia daría siempre WER 0 %, y
eso falsearía la comparativa del reto.

---

## Diagnóstico

```bash
python scripts/diagnose_gemini.py
```

Separa las cinco causas posibles de fallo: clave ausente, sin conectividad,
credencial rechazada, modelo inexistente y fallo en la transcripción. Nunca
imprime la clave (solo formato y 4 últimos caracteres).

---

## Tests

```bash
pytest
```

48 tests: cálculo de WER (con casos de desglose S/B/I), detección de firma
RIFF/WAVE, contrato HTTP de cada endpoint y el caso en que un proveedor
desconocido debe devolver 400 en lugar de caer silenciosamente a `mock`.

---

## Documentación

- [`docs/ARQUITECTURA_RED.md`](docs/ARQUITECTURA_RED.md) — puertos, protocolos,
  exposición, diagrama, modelo de amenazas y estado de Gemini.
- [`docs/COMPARATIVA.md`](docs/COMPARATIVA.md) — ventajas, desventajas, criterio
  de elección y resultados medidos.
