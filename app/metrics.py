"""
Metricas de evaluacion de transcripcion.

El WER (Word Error Rate) es la metrica estandar: la fraccion de palabras de la
referencia que el sistema no reproduce correctamente.

    WER = (Sustituciones + Borrados + Insertados) / Palabras de la referencia

Se implementa la distancia de Levenshtein con una unica matriz que devuelve el
desglose de los tres tipos de error, porque un WER sin desglose no permite saber
*por que* falla un motor.

La normalizacion de texto es la parte mas importante del resultado: sin ella,
un simple cambio de mayusculas o el uso de comas vs puntos generaria errores
falsos que inflarian el WER.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict

# Palabras vacias (mulieres) del espanol. Se pueden eliminar para medir el WER
# "de contenido", que es menos sensible a muletillas de relleno.
STOPWORDS_ES = {
    "a", "al", "algo", "ante", "antes", "como", "con", "contra", "cual",
    "cuando", "de", "del", "desde", "donde", "dos", "el", "ella", "ellos",
    "en", "entre", "era", "es", "esa", "ese", "eso", "esta", "este", "ha",
    "hasta", "hay", "la", "las", "le", "lo", "los", "mas", "me", "mi", "mis",
    "mucho", "muy", "nada", "ni", "no", "nos", "o", "otro", "para", "pero",
    "poco", "por", "porque", "que", "quien", "se", "sea", "ser", "si", "sin",
    "sobre", "son", "su", "sus", "tambien", "tanto", "te", "tiene", "todo",
    "tu", "un", "una", "uno", "y", "ya",
}

_PUNCT_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_SPACE_RE = re.compile(r"\s+", flags=re.UNICODE)


def normalizar(texto: str, quitar_stopwords: bool = False) -> list[str]:
    """
    Normaliza texto para comparar de forma justa:
      1. pasa a minusculas sin acentos (Unicode NFKD)
      2. elimina signos de puntuacion
      3. colapsa espacios y divide en palabras
      4. opcionalmente descarta palabras vacias
    """
    if not texto:
        return []
    t = unicodedata.normalize("NFKD", texto)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower()
    t = _PUNCT_RE.sub(" ", t)
    palabras = [p for p in _SPACE_RE.split(t) if p]
    if quitar_stopwords:
        palabras = [p for p in palabras if p not in STOPWORDS_ES]
    return palabras


@dataclass
class WerResult:
    """Desglose completo de la evaluacion de una transcripcion."""

    wer: float
    wer_porcentaje: float
    sustituciones: int
    borrados: int
    insertados: int
    palabras_referencia: int
    palabras_hipotesis: int
    palabras_correctas: int
    coincidencia_exacta: bool
    evaluable: bool
    motivo_no_evaluable: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _levenshtein_desglose(ref: list[str], hip: list[str]) -> tuple[int, int, int]:
    """
    Distancia de Levenshtein con desglose (sustituciones, borrados, insertados).

    Devuelve el coste minimo y los recuentos. La matriz se llena hacia atras
    guardando, para cada celda, el desglose acumulado; al retroceder desde
    (n, m) se reconstruye que operacion produjo cada celda.
    """
    n, m = len(ref), len(hip)
    INF = float("inf")

    # coste[i][j] = coste minimo de alinear ref[i:] con hip[j:]
    coste = [[INF] * (m + 1) for _ in range(n + 1)]
    # op[i][j] = 'S' sustitucion/coincidencia, 'B' borrado, 'I' insertado
    op = [[""] * (m + 1) for _ in range(n + 1)]

    for i in range(n + 1):
        coste[i][m] = 0.0 if i == n else float(n - i)
    for j in range(m + 1):
        coste[n][j] = 0.0 if j == m else float(m - j)
    for i in range(n, -1, -1):
        op[i][m] = "B"
    for j in range(m, -1, -1):
        op[n][j] = "I"

    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            coincide = ref[i] == hip[j]
            diag = coste[i + 1][j + 1] + (0.0 if coincide else 1.0)
            borra = coste[i + 1][j] + 1.0
            inserta = coste[i][j + 1] + 1.0
            mejor = min(diag, borra, inserta)
            coste[i][j] = mejor
            if mejor == diag:
                op[i][j] = "S"
            elif mejor == borra:
                op[i][j] = "B"
            else:
                op[i][j] = "I"

    # Retroceso para contar cada tipo de operacion en la alineacion optima.
    s = b = ins = 0
    i = j = 0
    while i < n and j < m:
        o = op[i][j]
        if o == "S":
            if ref[i] != hip[j]:
                s += 1
            i += 1
            j += 1
        elif o == "B":
            b += 1
            i += 1
        else:
            ins += 1
            j += 1
    b += n - i
    ins += m - j
    return s, b, ins


def calcular_wer(
    referencia: str,
    hipotesis: str,
    *,
    evaluable: bool = True,
    quitar_stopwords: bool = False,
    motivo_no_evaluable: str | None = None,
) -> WerResult:
    """
    Calcula el WER de una hipotesis frente a su referencia.

    `evaluable=False` marca el resultado como no medible (por ejemplo, cuando la
    transcripcion viene del proveedor simulado) para que un informe nunca
    presente un numero inventado como si fuera real.
    """
    ref = normalizar(referencia, quitar_stopwords)
    hip = normalizar(hipotesis, quitar_stopwords)

    if not evaluable:
        return WerResult(
            wer=float("nan"), wer_porcentaje=float("nan"),
            sustituciones=0, borrados=0, insertados=0,
            palabras_referencia=len(ref), palabras_hipotesis=len(hip),
            palabras_correctas=0, coincidencia_exacta=False,
            evaluable=False,
            motivo_no_evaluable=motivo_no_evaluable or "resultado no evaluable",
        )

    if not ref:
        return WerResult(
            wer=0.0 if not hip else 1.0,
            wer_porcentaje=0.0 if not hip else 100.0,
            sustituciones=0, borrados=len(hip), insertados=0,
            palabras_referencia=0, palabras_hipotesis=len(hip),
            palabras_correctas=0, coincidencia_exacta=not hip,
            evaluable=True,
        )

    s, b, ins = _levenshtein_desglose(ref, hip)
    errores = s + b + ins
    wer = errores / len(ref)

    return WerResult(
        wer=round(wer, 4),
        wer_porcentaje=round(wer * 100, 2),
        sustituciones=s,
        borrados=b,
        insertados=ins,
        palabras_referencia=len(ref),
        palabras_hipotesis=len(hip),
        palabras_correctas=max(0, len(ref) - errores),
        coincidencia_exacta=(errores == 0),
        evaluable=True,
    )
