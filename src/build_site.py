"""Orquestador del pipeline de validación, monitoreo y generación del sitio estático.

Procesa secuencialmente los lotes candidatos, aplica el validador contractual,
retiene el último lote válido, calcula el data drift con Evidently y scipy.stats,
y compila un dashboard web completo en la carpeta de salida (por defecto public/).
"""

import json
from pathlib import Path
import sys

# Asegurar que la raíz del proyecto esté en sys.path para resolución de módulos de src
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from src.drift_analyzer import (
    calcular_diagnostico_operativo,
    generate_evidently_report,
)
from src.validator import validate_batch


def generar_index_html(
    audit_log: list[dict],
    last_valid_name: str,
    df_origen: pd.DataFrame,
    df_rutas: pd.DataFrame,
    output_dir: str | Path,
) -> Path:
    """Genera el archivo index.html estilizado con Bootstrap 5 para el dashboard.

    Args:
        audit_log: Historial estructurado de procesamiento y auditoría de lotes.
        last_valid_name: Nombre del último lote que superó la validación contractual.
        df_origen: Tabla de diagnóstico agrupada por aeropuerto de origen.
        df_rutas: Tabla de diagnóstico agrupada por ruta filtrada.
        output_dir: Directorio de salida donde se guardará index.html.

    Returns:
        Path: Ruta al archivo index.html generado.
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    html_file = out_path / "index.html"

    # Tablas de diagnóstico en formato HTML con clases Bootstrap 5
    tabla_origen_html = df_origen.to_html(classes="table table-striped table-hover align-middle", index=False)
    tabla_rutas_html = df_rutas.to_html(classes="table table-striped table-hover align-middle", index=False)

    # Construcción de filas para la tabla de registro de auditoría
    audit_rows = []
    for entry in audit_log:
        archivo = entry.get("archivo", "Desconocido")
        es_valido = entry.get("es_valido", False)
        drift = entry.get("drift", "N/A")
        errores = entry.get("errores", [])

        if es_valido:
            badge_estado = '<span class="badge bg-success">Aprobado</span>'
        else:
            badge_estado = '<span class="badge bg-danger">Rechazado</span>'

        if errores:
            lista_errores = "<ul class='mb-0 ps-3'>" + "".join(f"<li>{e}</li>" for e in errores) + "</ul>"
        else:
            lista_errores = "<span class='text-muted'>Sin errores contractuales</span>"

        audit_rows.append(
            f"<tr>"
            f"<td><code>{archivo}</code></td>"
            f"<td>{badge_estado}</td>"
            f"<td><span class='badge bg-secondary'>{drift}</span></td>"
            f"<td><small>{lista_errores}</small></td>"
            f"</tr>"
        )

    filas_auditoria_html = "\n".join(audit_rows)

    html_content = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard de Operaciones: Monitoreo de Vuelos</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {{ background-color: #f8f9fa; font-family: system-ui, -apple-system, sans-serif; }}
        .card {{ border-radius: 0.75rem; box-shadow: 0 4px 6px rgba(0,0,0,0.05); margin-bottom: 1.5rem; }}
        .table-responsive {{ max-height: 450px; overflow-y: auto; }}
        .table thead {{ position: sticky; top: 0; background-color: #f1f3f5; z-index: 1; }}
    </style>
</head>
<body>
<div class="container py-4">
    <!-- Header Principal -->
    <header class="pb-3 mb-4 border-bottom">
        <h1 class="display-6 fw-bold text-primary">Dashboard de Operaciones: Monitoreo de Vuelos</h1>
        <p class="text-muted mb-0">Sistema automatizado de validación contractual y monitoreo continuo de data drift (NYC 2013).</p>
    </header>

    <!-- Alerta: Último lote válido procesado -->
    <div class="alert alert-success d-flex align-items-center mb-4" role="alert">
        <span class="fs-3 me-3">✈️</span>
        <div>
            <h5 class="alert-heading mb-1">Último lote válido procesado: <strong>{last_valid_name}</strong></h5>
            <small class="text-muted">Este lote ha superado todas las pruebas contractuales y se encuentra contrastado contra la referencia operacional.</small>
        </div>
    </div>

    <!-- Sección: Registro de Auditoría (Audit Log) -->
    <div class="card">
        <div class="card-header bg-dark text-white fw-semibold">
            📋 Registro de Auditoría (Audit Log)
        </div>
        <div class="card-body p-0">
            <div class="table-responsive">
                <table class="table table-hover mb-0">
                    <thead class="table-light">
                        <tr>
                            <th scope="col">Archivo Candidato</th>
                            <th scope="col">Estado</th>
                            <th scope="col">Drift</th>
                            <th scope="col">Detalle de Reglas y Errores</th>
                        </tr>
                    </thead>
                    <tbody>
                        {filas_auditoria_html}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- Sección: Diagnóstico Operativo por Origen -->
    <div class="card">
        <div class="card-header bg-primary text-white fw-semibold">
            📊 Diagnóstico Operativo por Aeropuerto de Origen (NYC)
        </div>
        <div class="card-body p-0">
            <div class="table-responsive">
                {tabla_origen_html}
            </div>
        </div>
    </div>

    <!-- Sección: Diagnóstico Operativo por Rutas Críticas -->
    <div class="card">
        <div class="card-header bg-secondary text-white fw-semibold">
            🗺️ Diagnóstico Operativo: Rutas Críticas Filtradas (&ge; 50 vuelos en ambos meses)
        </div>
        <div class="card-body p-0">
            <div class="table-responsive">
                {tabla_rutas_html}
            </div>
        </div>
    </div>

    <!-- Sección: Enlace e Iframe al Reporte de Evidently -->
    <div class="card">
        <div class="card-header bg-info text-white fw-semibold d-flex justify-content-between align-items-center">
            <span>📈 Reporte Completo de Data Drift (Evidently AI)</span>
            <a href="evidently_report.html" target="_blank" class="btn btn-sm btn-light fw-bold text-info">
                Abrir en Pestaña Completa &nearr;
            </a>
        </div>
        <div class="card-body p-2">
            <iframe src="evidently_report.html" style="width: 100%; height: 650px; border: none; border-radius: 0.5rem;" title="Reporte Evidently"></iframe>
        </div>
    </div>
</div>
</body>
</html>
"""
    html_file.write_text(html_content, encoding="utf-8")
    return html_file


def run_pipeline(
    ref_path: str, candidates: list[str], output_dir: str = "public"
) -> dict:
    """Ejecuta el pipeline de validación contractual, data drift y publicación web.

    1. Crea output_dir si no existe.
    2. Carga el lote de referencia desde ref_path.
    3. Inicializa audit_log = [].
    4. Itera secuencialmente sobre candidates:
       - Valida el lote con validate_batch(df).
       - Si falla, registra el rechazo en audit_log y salta al siguiente.
       - Si aprueba, registra el éxito y actualiza last_valid_df y last_valid_name.
    5. Si last_valid_df existe:
       - Calcula diagnóstico con calcular_diagnostico_operativo(df_referencia, last_valid_df).
       - Genera output_dir/evidently_report.html con generate_evidently_report.
       - Exporta output_dir/metadata.json con ultimo_lote_valido, drift_detectado y metricas_wasserstein.
       - Construye el Dashboard llamando a generar_index_html.

    Args:
        ref_path: Ruta al archivo CSV del lote de referencia (Enero).
        candidates: Lista de rutas a los archivos CSV candidatos a procesar.
        output_dir: Carpeta de destino del sitio web estático generado.

    Returns:
        dict: Metadatos generados del pipeline con el estado final.
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    print(f"Cargando lote de referencia: {ref_path}")
    df_referencia = pd.read_csv(ref_path)

    audit_log: list[dict] = []
    last_valid_df: pd.DataFrame | None = None
    last_valid_name: str | None = None

    for candidate in candidates:
        cand_path = Path(candidate)
        nombre_del_archivo = cand_path.name
        print(f"Validando lote candidato: {nombre_del_archivo}")

        try:
            df_candidate = pd.read_csv(candidate)
            val_result = validate_batch(df_candidate)
        except Exception as err:
            audit_log.append(
                {
                    "archivo": nombre_del_archivo,
                    "es_valido": False,
                    "errores": [f"Error de lectura/procesamiento: {str(err)}"],
                    "drift": "N/A",
                }
            )
            continue

        if not val_result.is_valid:
            print(f"[RECHAZADO] {nombre_del_archivo}: {len(val_result.errors)} errores detectados.")
            audit_log.append(
                {
                    "archivo": nombre_del_archivo,
                    "es_valido": False,
                    "errores": val_result.errors,
                    "drift": "N/A",
                }
            )
        else:
            print(f"[APROBADO] {nombre_del_archivo}: lote válido.")
            audit_log.append(
                {
                    "archivo": nombre_del_archivo,
                    "es_valido": True,
                    "errores": [],
                    "drift": "Evaluado",
                }
            )
            last_valid_df = df_candidate
            last_valid_name = nombre_del_archivo

    # Procesar diagnóstico si al menos un candidato fue válido
    if last_valid_df is not None and last_valid_name is not None:
        print(f"Calculando diagnóstico operativo contra último lote válido: {last_valid_name}")
        hay_drift, metricas, df_origen, df_rutas = calcular_diagnostico_operativo(
            df_referencia, last_valid_df
        )

        # Actualizar indicador de drift en el audit log para el lote retenido
        for entry in audit_log:
            if entry["archivo"] == last_valid_name:
                entry["drift"] = "Detectado" if hay_drift else "Estable (Sin drift)"

        # Generar reporte HTML de Evidently
        reporte_html_path = out_path / "evidently_report.html"
        print(f"Generando reporte Evidently en: {reporte_html_path}")
        generate_evidently_report(df_referencia, last_valid_df, reporte_html_path)

        # Exportar metadata.json
        metadata = {
            "ultimo_lote_valido": last_valid_name,
            "drift_detectado": bool(hay_drift),
            "metricas_wasserstein": metricas,
        }
        metadata_path = out_path / "metadata.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        print(f"Metadatos guardados en: {metadata_path}")

        # Generar index.html
        print("Construyendo dashboard estático index.html...")
        generar_index_html(audit_log, last_valid_name, df_origen, df_rutas, out_path)
        print("[OK] Pipeline completado exitosamente.")
        return metadata

    print("[WARN] Ningún lote candidato superó la validación contractual.")
    metadata_vacia = {
        "ultimo_lote_valido": None,
        "drift_detectado": False,
        "metricas_wasserstein": {},
    }
    with open(out_path / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata_vacia, f, indent=2)
    return metadata_vacia


if __name__ == "__main__":
    ref = "data/batches/lote_referencia.csv"
    candidatos = [
        "data/batches/lote_control.csv",
        "data/batches/lote_nuevo.csv",
        "data/batches/lote_corrupto.csv",
    ]
    run_pipeline(ref, candidatos)
