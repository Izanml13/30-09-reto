"""
Tests del calculo de WER.

Los valores esperados se derivan a mano sobre casos pequenos donde el
resultado es inequivoco, de modo que un fallo del algoritmo se detecte
siempre. `scripts/evaluate.py` usa este mismo codigo, asi que aqui queda
verificada la metrica que aparece en el informe final.
"""
import math

import pytest

from app.metrics import calcular_wer, normalizar


# ---------------------------------------------------------------- normalizar
def test_normalizacion_quita_acentos_y_mayusculas():
    assert normalizar("El Número CINCUENTA") == ["el", "numero", "cincuenta"]


def test_normalizacion_quita_puntuacion():
    assert normalizar("Hola, ¿qué tal?") == ["hola", "que", "tal"]


def test_normalizacion_vacia():
    assert normalizar("") == []
    assert normalizar("   ,,, ") == []


def test_stopwords_opcionales():
    texto = "el pedido numero cuarenta y cinco"
    assert len(normalizar(texto)) == 6
    # Se descartan "el" y "y", que son palabras vacias.
    assert normalizar(texto, quitar_stopwords=True) == [
        "pedido", "numero", "cuarenta", "cinco"
    ]


# --------------------------------------------------------------------- WER
def test_coincidencia_exacta_wer_cero():
    r = calcular_wer("hola mundo", "hola mundo")
    assert r.wer == 0.0
    assert r.coincidencia_exacta is True
    assert (r.sustituciones, r.borrados, r.insertados) == (0, 0, 0)


def test_una_sustitucion():
    # "mundo" -> "monton": 1 error sobre 2 palabras de referencia.
    r = calcular_wer("hola mundo", "hola monton")
    assert r.sustituciones == 1
    assert r.palabras_referencia == 2
    assert r.wer_porcentaje == 50.0


def test_un_borrado():
    # Referencia de 3 palabras; la hipotesis omite "mundo".
    r = calcular_wer("hola mundo cruel", "hola cruel")
    assert r.borrados == 1
    assert r.palabras_referencia == 3
    assert r.wer_porcentaje == pytest.approx(33.33, abs=0.01)


def test_un_insertado():
    # Se anade "grande" al final: 1 insercion sobre 3 palabras de referencia.
    r = calcular_wer("hola mundo cruel", "hola mundo cruel grande")
    assert r.insertados == 1
    assert r.sustituciones == 0
    assert r.wer_porcentaje == pytest.approx(33.33, abs=0.01)


def test_orden_distinto_cuesta_mas_que_una_palroma():
    """Reordenar palabras produce mas error que anadir una palabra suelta."""
    r = calcular_wer("hola mundo cruel", "hola cruel mundo extra")
    assert r.wer > calcular_wer(
        "hola mundo cruel", "hola mundo cruel grande").wer


def test_diferencias_de_puntuacion_no_cuentan_como_error():
    """Un STT que no pone comas no debe penalizarse por ello."""
    r = calcular_wer("Hola, hoy voy a probar.", "hola hoy voy a probar")
    assert r.wer == 0.0


def test_acentos_no_cuentan_como_error():
    r = calcular_wer("La reunión del comité", "la reunion del comite")
    assert r.wer == 0.0


def test_hipotesis_vacia_es_errores_totales():
    r = calcular_wer("hola mundo cruel", "")
    assert r.palabras_referencia == 3
    assert r.borrados == 3
    assert r.wer_porcentaje == 100.0


def test_referencia_vacia_con_hipotesis():
    r = calcular_wer("", "hola mundo")
    assert r.wer == 1.0
    assert r.palabras_referencia == 0


def test_referencia_vacia_sin_hipotesis():
    r = calcular_wer("", "")
    assert r.wer == 0.0


def test_resultado_no_evaluable_no_inventa_wer():
    r = calcular_wer(
        "hola mundo", "[MOCK] texto simulado",
        evaluable=False, motivo_no_evaluable="proveedor simulado",
    )
    assert r.evaluable is False
    assert r.motivo_no_evaluable == "proveedor simulado"
    # NaN, no 0: para que ningun informe lo presente como una precision real.
    assert math.isnan(r.wer)


def test_wer_puede_superar_el_100_por_ciento():
    """
    El WER no tiene cota superior: con una sola palabra de referencia y cinco
    en la hipotesis, los 4 insertados mas la sustitucion dan 500 %. Por eso en
    el informe se documenta el valor sin recortar a 100 %.
    """
    r = calcular_wer("hola", "uno dos tres cuatro cinco")
    assert r.wer_porcentaje == 500.0
    assert r.wer > 1.0
    assert r.palabras_correctas == 0  # nunca negativo


def test_wer_siempre_no_negativo():
    r = calcular_wer("a b c d e", "a b")
    assert r.wer >= 0.0


def test_frase_real_con_orden_distinto():
    """Palabras correctas pero desordenadas: Levenshtein las cuenta como error."""
    r = calcular_wer("uno dos tres", "tres dos uno")
    assert r.wer > 0
    assert r.palabras_referencia == 3


def test_uso_real_del_reto_numeros():
    """Caso del audio 2: 'cuarenta y cinco' frente a una lectura plausible."""
    ref = "El pedido número cuarenta y cinco llegó a las tres y media de la tarde."
    hip = "El pedido número cuarenta y cinco llego a las tres y media de la tarde."
    r = calcular_wer(ref, hip)
    # Sin acentos ni tildes, la frase debe ser identica salvo la tilde,
    # que la normalizacion elimina: WER 0.
    assert r.wer == 0.0
