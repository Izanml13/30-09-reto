# Comparativa de precision — Reto Speech-to-Text

Metrica: WER (Word Error Rate) = (S + B + I) / palabras_referencia

> El texto se normaliza (minusculas, sin acentos ni puntuacion) antes de comparar, de modo que diferencias tipograficas no cuentan como error. El WER no tiene cota superior.

| Audio | Nivel | Referencia | Web Speech API | WER API | Endpoint | WER Endpoint |
|---|---|---|---|---|---|---|
| `audio1_frase_corta` | facil | Hola, hoy voy a probar el sistema de transcripción de voz. | *no capturado* | n/d | *mock: no evaluable* | n/d |
| `audio2_numeros_hora` | dificil | El pedido número cuarenta y cinco llegó a las tres y media de la tarde. | *no capturado* | n/d | *mock: no evaluable* | n/d |
| `audio3_frase_larga` | dificil | La reunión del comité; ciento veinte personas; se pospone porque el presupuesto anual necesita una revisión completa antes de aprobarlo. | *no capturado* | n/d | *mock: no evaluable* | n/d |

## Resumen

| Motor | Audios medidos | WER medio |
|---|---|---|
| Web Speech API (navegador) | 0/3 | no medible |
| Endpoint Flask -> Gemini | 0/3 | no medible |

