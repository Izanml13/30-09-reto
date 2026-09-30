# Arquitectura de red — ASIX Speech-to-Text

Este documento describe el recorrido de los datos entre el cliente, el
servidor Flask y Google Gemini, para el perfil **ASIX**.

---

## 1. Diagrama general

```
   ┌──────────────────────────────────────────────────────────────┐
   │  CLIENTE                                                   │
   │                                                              │
   │  ┌────────────────────┐        ┌──────────────────────────┐  │
   │  │ Opción A           │        │ Opción B                 │  │
   │  │ Web Speech API     │        │ <form> multipart/form-   │  │
   │  │ (Chromium)         │        │ data                     │  │
   │  │                    │        │                          │  │
   │  │ SpeechRecognition  │        │ campo: audio (.wav/.mp3) │  │
   │  │ mic → Chromium    │        │ campo: language           │  │
   │  │        │           │        │ campo: provider           │  │
   │  └────────┼───────────┘        └────────────┬─────────────┘  │
   └───────────┼─────────────────────────────────┼───────────────┘
               │                                 │
               │ HTTPS 443                        │ HTTP 127.0.0.1:5000
               │ (salida del usuario)             │ (bucle local)
               v                                 v
   ┌───────────────────────────┐   ┌────────────────────────────────┐
   │  speech.google.com        │   │  SERVIDOR FLASK (localhost)    │
   │  (servicio de Google)     │   │                                │
   │  Chromium NO tiene la key │   │  ┌──────────────────────────┐  │
   └───────────────────────────┘   │  │ Capa de entrada          │  │
                                   │  │  · tamaño (413)          │  │
                                   │  │  · extensión (415)       │  │
                                   │  │  · WAV vacío (400)       │  │
                                   │  └────────────┬─────────────┘  │
                                   │               v                │
                                   │  ┌──────────────────────────┐  │
                                   │  │ audio_utils.py           │  │
                                   │  │  · detección RIFF/WAVE   │  │
                                   │  │  · afconvert → 16 kHz    │  │
                                   │  │    mono PCM 16 bit       │  │
                                   │  └────────────┬─────────────┘  │
                                   │               v                │
                                   │  ┌──────────────────────────┐  │
                                   │  │ Capa de proveedor        │  │
                                   │  │  Transcriber (interfaz)  │  │
                                   │  │   ├── GeminiTranscriber  │  │
                                   │  │   └── MockTranscriber    │  │
                                   │  └────────────┬─────────────┘  │
                                   └───────────────┼────────────────┘
                                                   │ HTTPS 443 + TLS
                                                   │ cabecera x-goog-api-key
                                                   v
                                   ┌────────────────────────────────┐
                                   │  generativelanguage.googleapis  │
                                   │  .com                           │
                                   │                                │
                                   │  POST /v1beta/models/{modelo}  │
                                   │       :generateContent         │
                                   │  base64(audio) + prompt         │
                                   └────────────────────────────────┘
```

---

## 2. Puertos, protocolos y exposure

| Tramo | Protocolo | Puerto | Quién inicia | Exposición |
|---|---|---|---|---|
| Navegador → Web Speech API | HTTPS | 443 | Chromium | **Salida** del usuario |
| Navegador → Flask | HTTP | 5000 | Navegador | **Bucle local** (127.0.0.1) |
| Flask → Gemini | HTTPS | 443 | Flask | **Salida** del servidor |

Puntos clave para ASIX:

- **El servidor Flask está ligado a `127.0.0.1`**, no a `0.0.0.0`. Desde
  la red local es inaccesible: no existe exposición accidental a la LAN.
- **El audio nunca se almacena.** Se escribe en un directorio temporal, se
  transcribe y se borra en el bloque `finally` de la ruta, incluso si la
  transcripción falla.
- **Dos flujos independientes.** La Opción A no pasa por Flask; el audio va
  directamente del micrófono a Google. La Opción B sí pasa por Flask. Por eso
  el audio de la Opción A **nunca toca nuestro servidor**.
- Para exponer el servicio en red habría que cambiar `STT_HOST=0.0.0.0` y
  colocar delante un proxy inverso con TLS (nginx, Caddy). Sin esa capa, el
  audio viajaría en claro por la LAN, y la clave de Gemini quedaría expuesta
  a cualquiera que alcance el puerto.

---

## 3. Petición de transcripción (Opción B)

### 3.1 Entrada

```http
POST /api/transcribe HTTP/1.1
Host: 127.0.0.1:5000
Content-Type: multipart/form-data; boundary=----ASIXSTT7f3c9b1e

------ASIXSTT7f3c9b1e
Content-Disposition: form-data; name="language"

es-ES
------ASIXSTT7f3c9b1e
Content-Disposition: form-data; name="provider"

gemini
------ASIXSTT7f3c9b1e
Content-Disposition: form-data; name="audio"; filename="audio1_frase_corta.wav"
Content-Type: audio/wav

<bytes RIFF/WAVE>
------ASIXSTT7f3c9b1e--
```

### 3.2 Pipeline interno (`app/routes/api.py`)

| # | Paso | Fichero | Rechazo |
|---|---|---|---|
| 1 | ¿Hay fichero `audio`? | ruta | 400 |
| 2 | ¿Extensión admitida? | `audio_utils.validate_extension` | 415 |
| 3 | ¿Supera el tamaño máximo? | `MAX_CONTENT_LENGTH` | 413 |
| 4 | ¿Tiene contenido? | `audio_utils.prepare` | 400 |
| 5 | Firmar RIFF/WAVE | `audio_utils.is_wav` | — |
| 6 | Normalizar a 16 kHz mono | `audio_utils.to_wav_16k_mono` | 400 |
| 7 | Resolver proveedor | `providers.build_with_fallback` | 400 / 503 |
| 8 | Transcribir | `GeminiTranscriber.transcribe` | 502 |
| 9 | Responder JSON + borrar temporal | bloque `finally` | — |

### 3.3 Salida a Gemini

```http
POST https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent
x-goog-api-key: <API_KEY>
Content-Type: application/json

{
  "contents": [{
    "role": "user",
    "parts": [
      {"inline_data": {"mime_type": "audio/wav", "data": "<base64 del WAV>"}},
      {"text": "Eres un motor de transcripcion... Idioma esperado: es-ES."}
    ]
  }],
  "generationConfig": {"temperature": 0.0, "max_output_tokens": 2048}
}
```

Detalles de diseño relevantes:

- **La clave viaja en la cabecera `x-goog-api-key`, nunca en la URL.** En una
  URL quedaría escrita en los logs de acceso del servidor proxy; en una
  cabecera no aparece en las trazas de URI. Por eso `/api/health` nunca la
  devuelve (cubierto por `test_health_no_filtra_la_api_key`).
- **`inline_data` con base64** duplica el tamaño: un audio de 12 s ocupa
  ~400 KB → ~530 KB en base64. El límite `STT_MAX_UPLOAD_MB=25` existe para
  que la petición que sale del servidor siga siendo razonable.
- **`temperature: 0.0`** reduce la variación entre llamadas: es una tarea de
  copia literal, no de generación creativa.
- **`afconvert` sin ffmpeg.** La normalización a 16 kHz mono usa la utilidad
  del sistema, lo que evita una dependencia binaria en la instalación.

### 3.4 Respuesta

```json
{
  "text": "Hola, hoy voy a probar el sistema de transcripción de voz.",
  "provider": "gemini",
  "model": "gemini-3.8-flash",
  "language": "es-ES",
  "duration_ms": 842,
  "is_fallback": false,
  "audio": {
    "filename": "audio1_frase_corta.wav",
    "duration_s": 2.91,
    "sample_rate": 16000,
    "channels": 1,
    "format_name": "WAV PCM",
    "normalizado_a_wav_16k_mono": false
  },
  "servicio_ms": 1390
}
```

---

## 4. Estado real de Gemini en esta instalación

Diagnóstico ejecutado con `scripts/diagnose_gemini.py`:

| Prueba | Resultado | Interpretación |
|---|---|---|
| Conectividad HTTPS | 200 | Red correcta |
| `GET /v1beta/models` | 200 | **La API key es válida** |
| `gemini-2.0-flash` | 404 *no longer available* | Proyecto nuevo |
| `gemini-2.5-flash` | 404 *no longer available to new users* | Proyecto nuevo |
| `gemini-3.8-flash` texto | **403 PERMISSION_DENIED** | Acceso denegado |
| `gemini-3.8-flash` audio | **403 PERMISSION_DENIED** | Acceso denegado |

```
Your project has been denied access. Please contact support.
```

**Conclusión:** no es un problema de código, ni de clave, ni de modelo. Google
ha denegado el acceso al proyecto a nivel de generación. Solo se resuelve
creando una API key en otro proyecto (<https://aistudio.google.com/apikey>) o
abriendo un ticket con Google Cloud.

Por eso `/api/health` distingue cuatro estados en lugar de un booleano:

| Estado | Significado |
|---|---|
| `operativo` | Sondeo real (`generateContent`) correcto |
| `bloqueado` | Hay key, pero Google deniega la generación ← **este caso** |
| `credencial_presente` | Hay key; pendiente de comprobar |
| `sin_credencial` | Sin key: se usará el proveedor simulado |

Anunciar «Gemini operativo» solo porque existe una clave habría sido
informar mal al usuario. El sondeo cuesta un token y se cachea 5 minutos.

---

## 5. Endpoints

| Método | Ruta | Función | Errores |
|---|---|---|---|
| `GET` | `/` | Interfaz web | — |
| `GET` | `/api/health` | Estado + sondeo de Gemini | — |
| `GET` | `/api/providers` | Proveedores registrados | — |
| `GET` | `/api/groundtruth` | Verdad terreno de los audios | 404 |
| `POST` | `/api/transcribe` | Audio → texto | 400, 413, 415, 502, 503 |
| `POST` | `/api/evaluate` | Calcula el WER de una transcripción | 400 |
| `POST` | `/api/report/webspeech` | Archiva una transcripción del navegador | 400 |

---

## 6. Modelo de amenazas y medidas aplicadas

| Riesgo | Medida |
|---|---|
| Filtrado de la API key | Cabecera `x-goog-api-key`, nunca en URL ni en respuestas |
| Persistencia de audio de usuario | Temporal + borrado en `finally` |
| Agotamiento de memoria | `MAX_CONTENT_LENGTH` y límite de tamaño propio (413) |
| Subida de formato no soportado | Lista blanca de extensiones + validación de firma RIFF |
| Respuesta falsa por error silencioso | Proveedor desconocido → 400; solo *no disponible* cae a `mock` |
| Presentación de datos simulados como reales | `is_fallback`, `warning` y `not_a_real_transcription` en cada respuesta |
| Exposición accidental en la red | Bind a `127.0.0.1` |
| Secuestro de recursos / transcripción ajena | Sin `Access-Control-Allow-Origin`: solo mismo origen |

**Ausencias deliberadas:** no hay autenticación ni rate limiting, porque el
servicio está ligado a bucle local y sin clave. Ambos serían obligatorios
antes de exponerlo; documentarlo es parte del análisis, no una omisión.

---

## 7. Endpoints de la Opción A (Web Speech API)

La Opción A **no usa nuestro backend**. El recorrido es:

```
Micrófono → Chromium (API SpeechRecognition)
          → speech.google.com:443 (audio + resultado)
          ← texto transcrito
```

Chromium incluye su propia clave para este servicio, así que el flujo
funciona sin que el usuario configure nada. Las consecuencias:

- El audio **sale del equipo directamente a Google**, sin pasar por Flask: no
  podemos auditarlo ni borrarlo desde nuestro servidor.
- Es **tiempo real**: no hay fichero de entrada ni salida JSON.
- Es ** Chromium-only** en la práctica. Safari y Firefox no la implementan, y
  el panel lo detecta y lo explica en lugar de fallar en silencio.
