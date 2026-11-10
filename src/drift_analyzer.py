"""Motor de análisis de data drift y diagnóstico operativo para lotes de vuelos NYC 2013.

Compara lotes operacionales contra el lote de referencia (Enero 2013), generando
reportes HTML con Evidently y diagnósticos estadísticos detallados a nivel de aeropuerto
y ruta con scipy.stats.
"""

import inspect
from pathlib import Path
from typing import Any
import pandas as pd
from scipy.stats import wasserstein_distance


# Columnas contractuales requeridas para el análisis de drift con Evidently
DRIFT_COLUMNS: list[str] = [
    "origen",
    "destino",
    "demora_salida_min",
    "demora_llegada_min",
    "distancia_millas",
]

# Aeropuertos metropolitanos de Nueva York evaluados
AEROPUERTOS_NYC: list[str] = ["EWR", "JFK", "LGA"]


def instanciar_preset_drift(umbral: float = 0.10) -> Any:
    """Instancia DataDriftPreset de Evidently adaptándose a la versión instalada.

    Usa inspect.signature sobre DataDriftPreset.__init__ para garantizar compatibilidad
    entre versiones:
    - Evidently 0.4.x: usa stattest_threshold=umbral
    - Evidently 0.6+: usa num_threshold=umbral, cat_threshold=umbral

    Args:
        umbral: Umbral estadístico para la detección de drift (default: 0.10).

    Returns:
        DataDriftPreset: Objeto instanciado compatible con la versión activa de Evidently.
    """
    try:
        from evidently.metric_preset import DataDriftPreset
    except ImportError:
        from evidently.presets import DataDriftPreset

    sig = inspect.signature(DataDriftPreset.__init__)
    params = sig.parameters

    kwargs: dict[str, Any] = {}
    if "stattest_threshold" in params:
        # Firma de Evidently 0.4.x
        kwargs["stattest_threshold"] = umbral
    else:
        # Firma de Evidently 0.6+ / 0.7+
        if "num_threshold" in params:
            kwargs["num_threshold"] = umbral
        if "cat_threshold" in params:
            kwargs["cat_threshold"] = umbral
        if "threshold" in params and "num_threshold" not in params:
            kwargs["threshold"] = umbral

    return DataDriftPreset(**kwargs)


def generate_evidently_report(
    df_ref: pd.DataFrame, df_act: pd.DataFrame, output_path: str | Path
) -> None:
    """Compara lotes usando un Report con DataDriftPreset y exporta el resultado en HTML.

    Filtra y analiza estrictamente las columnas:
    ["origen", "destino", "demora_salida_min", "demora_llegada_min", "distancia_millas"].

    Maneja la diferencia en la API de exportación entre versiones de Evidently:
    - En Evidently 0.6+, report.run() retorna un Snapshot con .save_html().
    - En Evidently 0.4.x, se invoca .save_html() sobre el objeto Report.

    Args:
        df_ref: DataFrame de referencia (Enero 2013).
        df_act: DataFrame actual/evaluado (Febrero, Julio, etc.).
        output_path: Ruta del archivo HTML de salida.
    """
    try:
        from evidently.report import Report
    except ImportError:
        from evidently import Report

    # Selección de columnas contractuales para drift
    ref_sub = df_ref[DRIFT_COLUMNS].copy()
    act_sub = df_act[DRIFT_COLUMNS].copy()

    preset = instanciar_preset_drift()

    # Instanciación de Report compatible
    report_sig = inspect.signature(Report.__init__)
    if "metrics" in report_sig.parameters:
        report = Report(metrics=[preset])
    else:
        report = Report([preset])

    # Ejecución del reporte comparativo
    run_result = report.run(reference_data=ref_sub, current_data=act_sub)

    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    # Manejo de exportación según versión
    if run_result is not None and hasattr(run_result, "save_html"):
        run_result.save_html(str(out_file))
    elif hasattr(report, "save_html"):
        report.save_html(str(out_file))
    else:
        raise RuntimeError(
            "No se encontró el método save_html en el resultado ni en el objeto Report de Evidently."
        )


def calcular_diagnostico_operativo(
    df_ref: pd.DataFrame,
    df_act: pd.DataFrame,
    umbral_wasserstein: float = 0.10,
) -> tuple[bool, dict[str, float], pd.DataFrame, pd.DataFrame]:
    """Calcula métricas de drift y genera diagnósticos a nivel de aeropuerto y ruta.

    Métricas calculadas:
    1. Distancia de Wasserstein normalizada (scipy.stats.wasserstein_distance(ref, act) / ref.std())
       para 'demora_salida_min', 'demora_llegada_min' y 'distancia_millas'.
    2. Alerta operativa: hay_drift es True si el drift en la demora de salida o llegada supera
       el umbral_wasserstein.
    3. Diagnóstico Origen: DataFrame comparativo por origen (EWR, JFK, LGA) con volumen de vuelos,
       medias de demoras, porcentaje de vuelos con demora de llegada >= 15 min y deltas (act - ref).
    4. Diagnóstico Rutas: DataFrame con ruta (origen -> destino), volumen, medias de demoras y delta
       de llegada. Filtra rutas con >= 50 vuelos en ambos meses y ordena descendentemente por delta.

    Args:
        df_ref: DataFrame de referencia (lote Enero 2013).
        df_act: DataFrame actual a contrastar (lote Control o Nuevo).
        umbral_wasserstein: Límite para disparar la alerta de drift operativo (default: 0.10).

    Returns:
        tuple[bool, dict[str, float], pd.DataFrame, pd.DataFrame]:
            - hay_drift: Booleano indicador de alerta de drift.
            - dict_metricas: Diccionario de distancias de Wasserstein normalizadas por variable.
            - df_origen: Tabla de diagnóstico agregada por aeropuerto de origen.
            - df_rutas: Tabla de diagnóstico agregada por ruta, filtrada (>=50) y ordenada.
    """
    # -----------------------------------------------------------------
    # 1. Métricas: Distancia de Wasserstein normalizada
    # -----------------------------------------------------------------
    metric_cols = ["demora_salida_min", "demora_llegada_min", "distancia_millas"]
    dict_metricas: dict[str, float] = {}

    for col in metric_cols:
        ref_vals = df_ref[col].dropna()
        act_vals = df_act[col].dropna()
        ref_std = float(ref_vals.std())
        divisor = ref_std if ref_std > 0 else 1.0
        w_dist = float(wasserstein_distance(ref_vals, act_vals))
        dict_metricas[col] = float(w_dist / divisor)

    # -----------------------------------------------------------------
    # 2. Alerta de drift operativo
    # -----------------------------------------------------------------
    hay_drift: bool = bool(
        (dict_metricas["demora_salida_min"] > umbral_wasserstein)
        or (dict_metricas["demora_llegada_min"] > umbral_wasserstein)
    )

    # -----------------------------------------------------------------
    # 3. Diagnóstico por Origen (EWR, JFK, LGA)
    # -----------------------------------------------------------------
    def _agregar_origen(df: pd.DataFrame, sufijo: str) -> pd.DataFrame:
        copia = df.copy()
        copia["es_demora_15"] = (copia["demora_llegada_min"] >= 15).astype(float) * 100.0
        res = copia.groupby("origen").agg(
            volumen=("vuelo_id", "count"),
            media_demora_salida=("demora_salida_min", "mean"),
            media_demora_llegada=("demora_llegada_min", "mean"),
            pct_demora_llegada_15=("es_demora_15", "mean"),
        )
        res.columns = [f"{col}_{sufijo}" for col in res.columns]
        return res

    orig_ref = _agregar_origen(df_ref, "ref")
    orig_act = _agregar_origen(df_act, "act")
    df_origen = orig_ref.join(orig_act, how="outer").fillna(0)

    # Garantizar presencia y orden canónico de aeropuertos de NYC
    indices_presentes = [a for a in AEROPUERTOS_NYC if a in df_origen.index] or list(df_origen.index)
    df_origen = df_origen.reindex(indices_presentes).reset_index()

    # Cálculo de deltas (actual - referencia)
    df_origen["delta_volumen"] = df_origen["volumen_act"] - df_origen["volumen_ref"]
    df_origen["delta_demora_salida"] = (
        df_origen["media_demora_salida_act"] - df_origen["media_demora_salida_ref"]
    )
    df_origen["delta_demora_llegada"] = (
        df_origen["media_demora_llegada_act"] - df_origen["media_demora_llegada_ref"]
    )
    df_origen["delta_pct_demora_llegada_15"] = (
        df_origen["pct_demora_llegada_15_act"] - df_origen["pct_demora_llegada_15_ref"]
    )

    # -----------------------------------------------------------------
    # 4. Diagnóstico por Rutas (origen -> destino)
    # -----------------------------------------------------------------
    def _agregar_rutas(df: pd.DataFrame, sufijo: str) -> pd.DataFrame:
        copia = df.copy()
        copia["ruta"] = copia["origen"].astype(str) + " -> " + copia["destino"].astype(str)
        res = copia.groupby("ruta").agg(
            volumen=("vuelo_id", "count"),
            media_demora_salida=("demora_salida_min", "mean"),
            media_demora_llegada=("demora_llegada_min", "mean"),
        )
        res.columns = [f"{col}_{sufijo}" for col in res.columns]
        return res

    rutas_ref = _agregar_rutas(df_ref, "ref")
    rutas_act = _agregar_rutas(df_act, "act")
    df_rutas = rutas_ref.join(rutas_act, how="inner")

    # Crucial: Filtrar solo aquellas rutas que tengan >= 50 vuelos en ambos meses
    df_rutas = df_rutas[
        (df_rutas["volumen_ref"] >= 50) & (df_rutas["volumen_act"] >= 50)
    ].copy()

    # Delta de demora de llegada y orden descendente
    df_rutas["delta_demora_llegada"] = (
        df_rutas["media_demora_llegada_act"] - df_rutas["media_demora_llegada_ref"]
    )
    df_rutas["delta_demora_salida"] = (
        df_rutas["media_demora_salida_act"] - df_rutas["media_demora_salida_ref"]
    )

    df_rutas = df_rutas.sort_values(by="delta_demora_llegada", ascending=False).reset_index()

    return hay_drift, dict_metricas, df_origen, df_rutas
