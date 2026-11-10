"""Módulo de particionamiento y preparación de lotes de datos de vuelos NYC 2013.

Localiza el dataset maestro en data/raw/vuelos_nyc_2013.csv (o en ./vuelos_nyc_2013.csv),
crea el directorio data/batches/ si no existe, y exporta 4 archivos CSV:
- data/batches/lote_referencia.csv (12.000 filas)
- data/batches/lote_control.csv (12.000 filas)
- data/batches/lote_nuevo.csv (12.000 filas)
- data/batches/lote_corrupto.csv (11.500 filas sintéticas inválidas)
"""

from pathlib import Path
import pandas as pd


def get_raw_data_path() -> Path:
    """Localiza el archivo maestro vuelos_nyc_2013.csv.

    Prioridad de búsqueda:
    1. data/raw/vuelos_nyc_2013.csv
    2. ./vuelos_nyc_2013.csv
    3. datos/raw/vuelos_nyc_2013.csv (fallback de compatibilidad local)

    Returns:
        Path: Ruta existente al archivo maestro CSV.

    Raises:
        FileNotFoundError: Si el archivo maestro no existe en ninguna ruta candidata.
    """
    candidate_rel_paths = [
        Path("data/raw/vuelos_nyc_2013.csv"),
        Path("vuelos_nyc_2013.csv"),
        Path("datos/raw/vuelos_nyc_2013.csv"),
    ]

    # Búsqueda directa desde el directorio de trabajo actual
    for candidate in candidate_rel_paths:
        if candidate.is_file():
            return candidate

    # Búsqueda relativa a la raíz del proyecto (un nivel arriba de src/)
    project_root = Path(__file__).resolve().parent.parent
    for candidate in candidate_rel_paths:
        resolved = project_root / candidate
        if resolved.is_file():
            return resolved

    raise FileNotFoundError(
        "No se pudo localizar el archivo maestro 'vuelos_nyc_2013.csv'. "
        "Verifique que exista en 'data/raw/vuelos_nyc_2013.csv' o en la raíz del proyecto."
    )


def prepare_batches(output_dir: Path | str = "data/batches") -> dict[str, Path]:
    """Lee el dataset maestro y genera los 4 lotes requeridos en output_dir.

    Args:
        output_dir: Directorio de destino para los lotes CSV.

    Returns:
        dict[str, Path]: Mapeo con las rutas de los 4 archivos generados.
    """
    raw_path = get_raw_data_path()
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"Cargando dataset maestro desde: {raw_path}")
    df = pd.read_csv(raw_path)

    # 1. Lote referencia (12.000 filas, Enero 2013)
    df_referencia = df[df["lote"] == "referencia"].copy()
    path_referencia = output_path / "lote_referencia.csv"
    df_referencia.to_csv(path_referencia, index=False)
    print(f"[OK] Lote referencia exportado: {path_referencia} ({len(df_referencia)} filas)")

    # 2. Lote control (12.000 filas, Febrero 2013)
    df_control = df[df["lote"] == "control"].copy()
    path_control = output_path / "lote_control.csv"
    df_control.to_csv(path_control, index=False)
    print(f"[OK] Lote control exportado: {path_control} ({len(df_control)} filas)")

    # 3. Lote nuevo (12.000 filas, Julio 2013)
    df_nuevo = df[df["lote"] == "nuevo"].copy()
    path_nuevo = output_path / "lote_nuevo.csv"
    df_nuevo.to_csv(path_nuevo, index=False)
    print(f"[OK] Lote nuevo exportado: {path_nuevo} ({len(df_nuevo)} filas)")

    # 4. Lote corrupto (11.500 filas sintéticas inválidas para pruebas)
    # Toma las primeras 11.500 filas del lote nuevo, cambia origen en fila 0 a 'MIA'
    # y asigna 'corrupto' a toda la columna lote.
    df_corrupto = df_nuevo.iloc[:11500].copy()
    df_corrupto.iloc[0, df_corrupto.columns.get_loc("origen")] = "MIA"
    df_corrupto["lote"] = "corrupto"
    path_corrupto = output_path / "lote_corrupto.csv"
    df_corrupto.to_csv(path_corrupto, index=False)
    print(f"[OK] Lote corrupto exportado: {path_corrupto} ({len(df_corrupto)} filas)")

    return {
        "referencia": path_referencia,
        "control": path_control,
        "nuevo": path_nuevo,
        "corrupto": path_corrupto,
    }


if __name__ == "__main__":
    prepare_batches()
