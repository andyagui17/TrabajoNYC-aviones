"""Suite de pruebas automatizadas para el motor de análisis de data drift y diagnóstico operativo.

Verifica la sensibilidad de detección de drift (Febrero vs Enero, Julio vs Enero),
el filtrado riguroso de rutas críticas (>= 50 vuelos), la estructura de diagnóstico por origen,
y la correcta generación y exportación del reporte HTML de Evidently.
"""

from pathlib import Path
import pandas as pd
import pytest

from src.drift_analyzer import (
    calcular_diagnostico_operativo,
    generate_evidently_report,
    instanciar_preset_drift,
)
from src.prepare_batches import prepare_batches


@pytest.fixture(scope="session", autouse=True)
def ensure_batches_exist():
    """Garantiza que los lotes CSV requeridos existan en data/batches/."""
    batches_dir = Path("data/batches")
    required = [
        "lote_referencia.csv",
        "lote_control.csv",
        "lote_nuevo.csv",
    ]
    if not all((batches_dir / f).is_file() for f in required):
        prepare_batches()


@pytest.fixture
def lotes_cargados() -> dict[str, pd.DataFrame]:
    """Carga los tres lotes operacionales en memoria para agilizar las pruebas."""
    return {
        "referencia": pd.read_csv("data/batches/lote_referencia.csv"),
        "control": pd.read_csv("data/batches/lote_control.csv"),
        "nuevo": pd.read_csv("data/batches/lote_nuevo.csv"),
    }


@pytest.fixture
def mock_100_rows_df() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Genera dos DataFrames simulados pequeños (100 filas) con esquema contractual."""
    n = 100
    origenes = (["JFK", "LGA", "EWR"] * 34)[:n]
    destinos = (["ORD", "LAX", "MIA", "ATL"] * 25)[:n]

    df_ref = pd.DataFrame(
        {
            "vuelo_id": list(range(1, n + 1)),
            "fecha": ["2013-01-15"] * n,
            "origen": origenes,
            "destino": destinos,
            "demora_salida_min": [10.0 + (i % 5) for i in range(n)],
            "demora_llegada_min": [5.0 + (i % 7) for i in range(n)],
            "distancia_millas": [1000.0 + (i * 10) for i in range(n)],
            "lote": ["referencia"] * n,
        }
    )

    df_act = df_ref.copy()
    df_act["lote"] = "control"
    df_act["demora_salida_min"] = df_act["demora_salida_min"] + 2.0
    df_act["demora_llegada_min"] = df_act["demora_llegada_min"] + 1.5

    return df_ref, df_act


# =====================================================================
# PRUEBAS DE SENSIBILIDAD Y DIAGNÓSTICO
# =====================================================================


def test_sensibilidad_febrero_vs_enero_sin_drift(lotes_cargados):
    """Prueba de sensibilidad (Febrero vs Enero):

    Ejecuta calcular_diagnostico_operativo usando referencia y control.
    Verifica mediante un assert que hay_drift es False (comportamiento operacional estable).
    """
    df_ref = lotes_cargados["referencia"]
    df_ctrl = lotes_cargados["control"]

    hay_drift, dict_metricas, df_origen, df_rutas = calcular_diagnostico_operativo(
        df_ref, df_ctrl, umbral_wasserstein=0.10
    )

    assert hay_drift is False, (
        f"Se detectó drift inesperado entre Febrero y Enero: {dict_metricas}"
    )
    assert dict_metricas["demora_salida_min"] <= 0.10
    assert dict_metricas["demora_llegada_min"] <= 0.10
    assert "distancia_millas" in dict_metricas


def test_sensibilidad_julio_vs_enero_con_drift(lotes_cargados):
    """Prueba de sensibilidad (Julio vs Enero):

    Ejecuta calcular_diagnostico_operativo usando referencia y nuevo.
    Verifica mediante un assert que hay_drift es True (alta degradación en demoras de verano).
    """
    df_ref = lotes_cargados["referencia"]
    df_nuevo = lotes_cargados["nuevo"]

    hay_drift, dict_metricas, df_origen, df_rutas = calcular_diagnostico_operativo(
        df_ref, df_nuevo, umbral_wasserstein=0.10
    )

    assert hay_drift is True, (
        f"No se detectó drift entre Julio y Enero cuando debía detectarse: {dict_metricas}"
    )
    # Al menos una de las dos métricas de demora debe exceder el umbral
    assert (
        dict_metricas["demora_salida_min"] > 0.10
        or dict_metricas["demora_llegada_min"] > 0.10
    )


def test_rutas_criticas_filtro_y_orden(lotes_cargados):
    """Prueba de rutas críticas:

    Verifica que en el DataFrame de rutas generado entre Julio y Enero:
    1. Ninguna ruta filtrada tenga menos de 50 vuelos en ninguno de los dos meses.
    2. El DataFrame esté ordenado descendentemente por delta_demora_llegada.
    """
    df_ref = lotes_cargados["referencia"]
    df_nuevo = lotes_cargados["nuevo"]

    _, _, _, df_rutas = calcular_diagnostico_operativo(df_ref, df_nuevo)

    assert isinstance(df_rutas, pd.DataFrame)
    assert len(df_rutas) > 0, "El DataFrame de rutas filtradas no debe estar vacío."

    # Verificación del filtro muestral crucial: >= 50 en ambos meses
    assert (
        df_rutas["volumen_ref"] >= 50
    ).all(), "Existen rutas con menos de 50 vuelos en el lote de referencia."
    assert (
        df_rutas["volumen_act"] >= 50
    ).all(), "Existen rutas con menos de 50 vuelos en el lote actual."

    # Verificación del ordenamiento descendente por degradación (delta_demora_llegada)
    assert df_rutas["delta_demora_llegada"].is_monotonic_decreasing, (
        "El DataFrame de rutas no está ordenado descendentemente por delta_demora_llegada."
    )

    # Verificación del formato de ruta concatenada
    assert "ruta" in df_rutas.columns
    assert (df_rutas["ruta"].str.contains(" -> ")).all(), (
        "El formato de la ruta debe ser 'origen -> destino'."
    )


def test_diagnostico_origen_metricas_y_deltas(lotes_cargados):
    """Verifica que el diagnóstico por origen contenga aeropuertos clave y deltas matemáticos."""
    df_ref = lotes_cargados["referencia"]
    df_nuevo = lotes_cargados["nuevo"]

    _, _, df_origen, _ = calcular_diagnostico_operativo(df_ref, df_nuevo)

    assert isinstance(df_origen, pd.DataFrame)
    assert set(df_origen["origen"].tolist()) == {"EWR", "JFK", "LGA"}

    # Verificación de consistencia en el cálculo de deltas
    for _, row in df_origen.iterrows():
        assert row["delta_volumen"] == row["volumen_act"] - row["volumen_ref"]
        assert pytest.approx(row["delta_demora_salida"]) == (
            row["media_demora_salida_act"] - row["media_demora_salida_ref"]
        )
        assert pytest.approx(row["delta_demora_llegada"]) == (
            row["media_demora_llegada_act"] - row["media_demora_llegada_ref"]
        )
        assert pytest.approx(row["delta_pct_demora_llegada_15"]) == (
            row["pct_demora_llegada_15_act"] - row["pct_demora_llegada_15_ref"]
        )


# =====================================================================
# PRUEBAS DE EVIDENTLY Y REPORTE HTML
# =====================================================================


def test_instanciar_preset_drift_compatibilidad():
    """Verifica que instanciar_preset_drift devuelva un objeto válido de Evidently."""
    preset = instanciar_preset_drift(umbral=0.15)
    assert preset is not None
    assert type(preset).__name__ == "DataDriftPreset"


def test_generate_evidently_report_html(mock_100_rows_df, tmp_path):
    """Prueba de reporte HTML:

    Pasa DataFrames simulados pequeños (100 filas) a generate_evidently_report
    y verifica que el archivo físico se crea correctamente en una carpeta temporal
    generada por pytest (tmp_path).
    """
    df_mock_ref, df_mock_act = mock_100_rows_df
    output_file = tmp_path / "reporte_drift_test.html"

    assert not output_file.exists()

    generate_evidently_report(
        df_ref=df_mock_ref, df_act=df_mock_act, output_path=output_file
    )

    assert output_file.is_file(), f"No se generó el archivo esperado en {output_file}"
    assert output_file.stat().st_size > 0, "El archivo HTML generado está vacío."

    # Validar que contiene estructura HTML válida
    contenido = output_file.read_text(encoding="utf-8")
    assert "<html" in contenido.lower() or "<!doctype html" in contenido.lower(), (
        "El archivo generado no presenta encabezado HTML estándar."
    )
