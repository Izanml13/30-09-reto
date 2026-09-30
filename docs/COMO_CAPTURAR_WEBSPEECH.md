# Cómo completar la columna de la Web Speech API

La tabla de precisión sale con las dos columnas vacías porque falta una cosa
que no se puede automatizar desde aquí: **hablar al micrófono**.

Gemini además está bloqueado (ver §4 de `COMPARATIVA.md`). Esta guía cubre solo
la parte de la Web Speech API, que es la que puedes completar hoy mismo.

---

## Requisito: un navegador con `SpeechRecognition`

| Navegador | ¿Soporta la Web Speech API? |
|---|---|
| **Chrome / Edge / Chromium** | Sí |
| Safari | No |
| Firefox | No |

Si usas Safari, la instalación de Chrome es el paso previo:

```bash
brew install --cask google-chrome
```

---

## Opción 1 — Manualmente (la más directa)

1. Arranca el servicio:
   ```bash
   cd speech-to-text
   python run.py
   ```
2. Abre <http://127.0.0.1:5000> en **Chrome**.
3. Pulsa **«Empezar a escuchar»** en el panel A y di la frase.
4. Cuando tengas el texto, pulsa **«Copiar»** (descarga un `.txt`).
5. Repite con las otras dos frases.

Luego pega cada transcripción aquí:

```bash
cd speech-to-text
cat > resultados/webspeech.json <<'JSON'
{
  "metodo": "Web Speech API",
  "resultados": [
    {"audio_id": "audio1_frase_corta", "hipotesis": "pega aqui lo que transcribio"},
    {"audio_id": "audio2_numeros_hora", "hipotesis": "pega aqui lo que transcribio"},
    {"audio_id": "audio3_frase_larga",  "hipotesis": "pega aqui lo que transcribio"}
  ]
}
JSON

python scripts/evaluate.py --endpoint http://127.0.0.1:5000
```

Las frases exactas están en `audios/ground_truth.json`:

1. «Hola, hoy voy a probar el sistema de transcripción de voz.»
2. «El pedido número cuarenta y cinco llegó a las tres y media de la tarde.»
3. «La reunión del comité; ciento veinte personas; se pospone porque el
   presupuesto anual necesita una revisión completa antes de aprobarlo.»

> **Importante:** di la frase con tu voz, no reproduzcas el WAV. La Web Speech
> API captura del micrófono, no de un fichero.

---

## Opción 2 — Página de captura automática

Útil si quieres que el navegador archive solo el texto, sin copiar y pegar.

Abre, para cada audio:

```
http://127.0.0.1:5000/captura_webspeech.html?id=audio1_frase_corta
```

- Escribe el `audio_id` y pulsa «Empezar a escuchar».
- Al detenerte, el texto se envía solo a `/api/report/webspeech` y se guarda
  en `resultados/webspeech.json`.

Repite para los tres y regenera el informe:

```bash
python scripts/evaluate.py --endpoint http://127.0.0.1:5000
```

---

## Opción 3 — Automatizar con audio inyectado

Chrome puede usar un WAV como micrófono virtual, lo que permite medir la
Web Speech API sobre los ficheros **sin hablar**:

```bash
cd speech-to-text
./scripts/capturar_webspeech_automatica.sh
```

Requiere Chrome instalado y macOS con permisos de micrófono concedidos a
Chrome la primera vez. El script lanza Chrome con:

```
--use-file-for-fake-audio-capture=audios/audio1_frase_corta.wav
```

y abre la página en modo automático. Los resultados se archivan solos.

Si el navegador usado no es Chromium, esta vía no funciona.

---

## Comprobar que ha funcionado

```bash
cat resultados/webspeech.json
python scripts/evaluate.py --endpoint http://127.0.0.1:5000
```

En `resultados/informe.md` la columna **WER API** debe quedar con un
porcentaje. Si aparece `n/d`, el `audio_id` del JSON no coincide con los de
`audios/ground_truth.json`.

---

## Comprobación de coherencia

Un WER de **exactamente 0 %** en los tres audios es sospechoso. Si has pegado
el texto de referencia en vez del transcrito, el informe comparará el original
consigo mismo. La métrica está diseñada para detectar el fallo, pero conviene
mirar la tabla: si las tres filas son perfectas y además el JSON contiene
palabras idénticas a la referencia, el dato es circular.
