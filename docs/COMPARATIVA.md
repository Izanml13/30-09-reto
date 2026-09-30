# Comparativa de motores — Reto Speech-to-Text

Análisis de las dos opciones del reto, con los datos medidos en esta
máquina y las limitaciones de cada una.

---

## 1. Resumen

| | **Opción A** — Web Speech API | **Opción B** — Gemini vía Flask |
|---|---|---|
| Entorno | Navegador (Chromium) | Servidor Python |
| Tiempo | **Real** (sub-segundo) | Por lotes (segundos) |
| API key | **No hace falta** | Sí |
| Coste | 0 € | Cuota gratuita de Google |
| Audio analyzed | Sí, en el navegador | Sí, en el servidor |
| Audio pasa por nuestro servidor | **No** | Sí |
| Privacidad | Audio → Google directo | Audio → servidor → Google |
| Formatos | Solo micrófono en directo | `.wav .mp3 .m4a .ogg .webm .flac` |
| Requiere backend | No | Sí |
| Estado en esta máquina | **Funciona** | **Bloqueado (403)** |

---

## 2. Ventajas y desventajas

### Opción A — Web Speech API

**Ventajas**
- **Cero configuración.** Ni clave, ni cuenta, ni billing.
- **Latencia mínima.** El texto aparece mientras hablas, que es lo que pide un
  servicio de dictado o un subtitulado en vivo.
- **Sin infraestructura.** No hay servidor que desplegar ni mantener.
- **Gratuita** sin cuotas que agotar.

**Desventajas**
- **Solo navegador y solo Chromium.** Safari y Firefox no la ofrecen. La API
  existe pero su soporte es desigual: `SpeechRecognition` y
  `webkitSpeechRecognition` se implementaron en Chromium y no se han
  estandarizado.
- **Sin control del modelo.** No se puede ajustar el prompt, la temperatura ni
  el idioma más allá del BCP-47.
- **Sin opción por lotes.** No acepta un fichero: hay que reproducir el audio
  en tiempo real. Medir su precisión sobre ficheros exige inyectar el audio
  como micrófono, un truco que necesita flags de arranque de Chrome.
- **La clave está dentro del navegador.** Chromium incluye la suya, así que
  el desarrollador no controla ni audita esa llamada.
- **El audio se va del equipo sin pasar por tu servidor.** No se puede
  registrar en un log ni auditar.

### Opción B — Gemini vía Flask

**Ventajas**
- **Control total del proceso**: formato de salida, prompt, `temperature`, y
  filtrado o registro del audio en servidor.
- **Por lotes**: acepta ficheros, así que es automatizable y repetible.
- **Formatos flexibles** y normalización a 16 kHz mono en el servidor.
- **Ampliable**: añadir más proveedores (Whisper local, Azure) es implementar
  una clase y registrarla.
- **Métricas medibles**: se puede calcular WER contra la verdad terreno.

**Desventajas**
- **Requiere credencial y la cuota asociada.** Y en este proyecto, además,
  una credencial que *no basta*: el acceso está denegado (§4).
- **Coste por audio** y límite de peticiones.
- **Latencia de segundos**, inaceptable para tiempo real.
- **Infraestructura**: servidor, proceso, despliegue y endurecimiento.

---

## 3. Precisión medida

Método: **WER (Word Error Rate)** = (sustituciones + borrados + insertados) /
palabras de referencia, sobre 3 audios con verdad terreno conocida.

> Los audios se generaron con `say` a partir de un texto que ya conocemos,
> así que la referencia es exacta. Se normaliza el texto (minúsculas, sin
> acentos ni puntuación) antes de comparar, para que un `,` frente a un `.`
> no cuente como error.

### Resultado en esta máquina

| Audio | Nivel | Web Speech API | WER API | Gemini | WER Endpoint |
|---|---|---|---|---|---|
| `audio1_frase_corta` | fácil | no capturado | n/d | mock | **no evaluable** |
| `audio2_numeros_hora` | difícil | no capturado | n/d | mock | **no evaluable** |
| `audio3_frase_larga` | difícil | no capturado | n/d | mock | **no evaluable** |

**Por qué la columna de Gemini está vacía:** el acceso está denegado por
Google (§4) y el proveedor activo es `mock`, que no analiza el audio. El
script de evaluación marca esas filas como *no evaluables* en lugar de
imprimir un número. Medir precisión sobre texto inventado daría un WER del
100 % y una falsa impresión de datos.

Para completar la tabla hacen falta dos cosas:

1. **Una API key de Gemini en un proyecto no bloqueado** → el código ya está
   escrito y probado; basta con cambiar `GEMINI_API_KEY`.
2. **Capturar la Web Speech API sobre los 3 audios.** Se puede leer cada frase
   al micrófono en `web/index.html` (el botón «Copiar» exporta el texto) o
   usar `web/captura_webspeech.html`, que lo archiva en
   `resultados/webspeech.json` y se mide con el mismo script.

Después, una sola orden regenera el informe completo:

```bash
python scripts/evaluate.py --endpoint http://127.0.0.1:5000 \
    --webspeech resultados/webspeech.json
```

### Lectura de los resultados (con Gemini operativo)

Por lo observado en otros motores con audio de síntesis, la hipótesis
razonable es:

- **`audio1_frase_corta`**: WER bajo en ambos. Una frase corta y sin cifras es
  el caso fácil.
- **`audio2_numeros_hora`**: el punto crítico. «cuarenta y cinco» y «tres y
  media» son reformulados o mal segmentados con frecuencia. Aquí es donde
  Gemini (LLM con contexto léxico) suele superar a un STT especializado.
- **`audio3_frase_larga`**: la duración penaliza. Los errores se acumulan y
  cualquier silencio mal detectado desalinea el resto. Suele tener **WER más
  alto que la frase corta pese a ser texto fácil**, por lo que la duración
  debe reportarse siempre junto al WER.

Esto es una hipótesis razonada, **no un dato medido**. Los números que
aparezcan en el informe deben salir de `scripts/evaluate.py`, no de aquí.

---

## 4. Por qué Gemini no se pudo medir

| Prueba | Resultado |
|---|---|
| `GET /v1beta/models` | 200 — la key es **válida** |
| `gemini-2.0-flash` / `2.5-flash` | 404 — proyecto **nuevo** |
| `generateContent` texto | **403 PERMISSION_DENIED** |
| `generateContent` audio | **403 PERMISSION_DENIED** |

```
Your project has been denied access. Please contact support.
```

La generación está denegada a nivel de proyecto. El bloqueo no depende del
código, de la clave ni del modelo elegido.

---

## 5. Cuál elegir

**Opción A** si el objetivo es una transcripción en vivo, sin costes ni
mantenimiento, aceptando depender de Chromium.

**Opción B** si el audio ya existe como fichero, si se necesita automatizar o
medir, o si el audio debe pasar por un control propio.

En la práctica **se complementan**: el panel B consume el endpoint, así que
ambos conviven en la misma interfaz y se comparan sobre los mismos audios.
Esa es precisamente la razón de haber medido el WER con una única función
compartida (`app/metrics.py`) en vez de dos implementaciones: cualquier
diferencia observada en la tabla es del motor, no de la métrica.
