"""Suite de pruebas para el orquestador del pipeline y generador del sitio estático.

Verifica que run_pipeline procese candidatos secuencialmente, aplique validación contractual,
retenga el último lote válido ante intentos de ingesta corruptos, y exporte correctamente
los artefactos requeridos (index.html, evidently_report.html, metadata.json).
"""

import json
from pathlib import Path
import pandas as pd
import pytest

from src.build_site import generar_index_html, run_pipeline
from src.validator import EXPECTED_ROW_COUNT


def _crear_dataframe_valido(n: int = EXPECTED_ROW_COUNT, mes: str = "01", lote_nombre: str = "referencia") -> pd.DataFrame:
    """Genera un DataFrame en memoria que cumple 100% las reglas contractuales."""
    origenes = (["JFK", "LGA", "EWR"] * (n // 3 + 1))[:n]
    destinos = (["ORD", "LAX", "MIA", "ATL"] * (n // 4 + 1))[:n]
    fechas = [f"2013-{mes}-15"] * n

    return pd.DataFrame(
        {
            "vuelo_id": list(range(1, n + 1)),
            "fecha": fechas,
            "origen": origenes,
            "destino": destinos,
            "demora_salida_min": [5.0] * n,
            "demora_llegada_min": [-2.0] * n,
            "distancia_millas": [1000.0] * n,
            "lote": [lote_nombre] * n,
        }
    )


def test_pipeline_retencion_ultimo_lote_valido(tmp_path):
    """Prueba de integración del orquestador:

    1. Genera un DataFrame de referencia y dos candidatos:
       - cand_valido.csv (12.000 filas, válido)
       - cand_corrupto.csv (500 filas, inválido)
    2. Ejecuta run_pipeline en orden: [cand_valido, cand_corrupto].
    3. Verifica que se generen los 3 artefactos: index.html, evidently_report.html y metadata.json.
    4. Verifica que metadata.json retenga 'cand_valido.csv' como ultimo_lote_valido,
       confirmando la resiliencia del pipeline ante la ingesta del lote corrupto.
    """
    # 1. Crear datasets temporales
    df_ref = _crear_dataframe_valido(mes="01", lote_nombre="referencia")
    df_valido = _crear_dataframe_valido(mes="02", lote_nombre="control")

    # Crear candidato corrupto (violación de volumen e integridad)
    df_corrupto = pd.DataFrame(
        {
            "vuelo_id": list(range(1, 501)),
            "fecha": ["2013-03-10"] * 500,
            "origen": ["MIA"] * 500,  # Origen no permitido
            "destino": ["JFK"] * 500,
            "demora_salida_min": [0.0] * 500,
            "demora_llegada_min": [0.0] * 500,
            "distancia_millas": [1000.0] * 500,
            "lote": ["corrupto"] * 500,
        }
    )

    ref_csv = tmp_path / "lote_referencia_temp.csv"
    valido_csv = tmp_path / "cand_valido.csv"
    corrupto_csv = tmp_path / "cand_corrupto.csv"

    df_ref.to_csv(ref_csv, index=False)
    df_valido.to_csv(valido_csv, index=False)
    df_corrupto.to_csv(corrupto_csv, index=False)

    public_dir = tmp_path / "public"

    # 2. Ejecutar run_pipeline
    candidatos = [str(valido_csv), str(corrupto_csv)]
    resultado_metadata = run_pipeline(
        ref_path=str(ref_csv),
        candidates=candidatos,
        output_dir=str(public_dir),
    )

    # 3. Validar existencia física de los 3 artefactos
    index_file = public_dir / "index.html"
    report_file = public_dir / "evidently_report.html"
    metadata_file = public_dir / "metadata.json"

    assert index_file.is_file(), f"No se encontró {index_file}"
    assert report_file.is_file(), f"No se encontró {report_file}"
    assert metadata_file.is_file(), f"No se encontró {metadata_file}"

    assert index_file.stat().st_size > 0, "index.html está vacío."
    assert report_file.stat().st_size > 0, "evidently_report.html está vacío."
    assert metadata_file.stat().st_size > 0, "metadata.json está vacío."

    # 4. Validar contenido de metadata.json
    with open(metadata_file, "r", encoding="utf-8") as f:
        meta_data = json.load(f)

    assert meta_data["ultimo_lote_valido"] == "cand_valido.csv", (
        f"El pipeline no retuvo el lote correcto; guardó {meta_data.get('ultimo_lote_valido')}"
    )
    assert "drift_detectado" in meta_data
    assert isinstance(meta_data["drift_detectado"], bool)
    assert "metricas_wasserstein" in meta_data
    assert "demora_salida_min" in meta_data["metricas_wasserstein"]

    # 5. Validar elementos clave en el HTML generado
    html_content = index_file.read_text(encoding="utf-8")
    assert "Dashboard de Operaciones: Monitoreo de Vuelos" in html_content
    assert "cand_valido.csv" in html_content
    assert "cand_corrupto.csv" in html_content
    assert "Aprobado" in html_content
    assert "Rechazado" in html_content
    assert "evidently_report.html" in html_content
    assert "cdn.jsdelivr.net/npm/bootstrap" in html_content


def test_pipeline_todos_candidatos_invalidos(tmp_path):
    """Verifica el comportamiento cuando ningún candidato supera la validación."""
    df_ref = _crear_dataframe_valido(mes="01", lote_nombre="referencia")
    df_invalido = pd.DataFrame({"vuelo_id": [1], "lote": ["invalido"]})

    ref_csv = tmp_path / "ref_temp.csv"
    invalido_csv = tmp_path / "invalido.csv"

    df_ref.to_csv(ref_csv, index=False)
    df_invalido.to_csv(invalido_csv, index=False)

    public_dir = tmp_path / "public_fallo"

    meta = run_pipeline(
        ref_path=str(ref_csv),
        candidates=[str(invalido_csv)],
        output_dir=str(public_dir),
    )

    metadata_file = public_dir / "metadata.json"
    assert metadata_file.is_file()
    assert meta["ultimo_lote_valido"] is None
    assert meta["drift_detectado"] is False


def test_generar_index_html_directo(tmp_path):
    """Verifica que la función generar_index_html escriba un archivo HTML funcional."""
    audit_log = [
        {"archivo": "lote_1.csv", "es_valido": True, "errores": [], "drift": "Estable"},
        {"archivo": "lote_2.csv", "es_valido": False, "errores": ["Error de esquema"], "drift": "N/A"},
    ]
    df_origen = pd.DataFrame({"origen": ["JFK", "LGA"], "volumen_act": [100, 200]})
    df_rutas = pd.DataFrame({"ruta": ["JFK -> LAX"], "delta_demora_llegada": [5.2]})

    html_path = generar_index_html(
        audit_log=audit_log,
        last_valid_name="lote_1.csv",
        df_origen=df_origen,
        df_rutas=df_rutas,
        output_dir=tmp_path,
    )

    assert html_path.is_file()
    content = html_path.read_text(encoding="utf-8")
    assert "lote_1.csv" in content
    assert "lote_2.csv" in content
    assert "Error de esquema" in content
