"""Motor de validación contractual para lotes de vuelos NYC 2013.

Implementa las reglas de calidad, integridad, dominio, coherencia física y temporal
sin dependencias externas pesadas.
"""

from dataclasses import dataclass
import re
import pandas as pd


EXPECTED_COLUMNS: list[str] = [
    "vuelo_id",
    "fecha",
    "origen",
    "destino",
    "demora_salida_min",
    "demora_llegada_min",
    "distancia_millas",
    "lote",
]

ALLOWED_ORIGINS: set[str] = {"LGA", "EWR"}
IATA_REGEX: str = r"^[A-Z]{3}$"
DATE_REGEX: str = r"^\d{4}-\d{2}-\d{2}$"
EXPECTED_ROW_COUNT: int = 12000

MIN_DISTANCIA: float = 10.0
MAX_DISTANCIA: float = 6000.0
MIN_DEMORA: float = -120.0
MAX_DEMORA: float = 1500.0


@dataclass
class ValidationResult:
    """Resultado estructurado de la validación contractual de un lote."""

    batch_name: str
    is_valid: bool
    errors: list[str]
    row_count: int
    period: str | None = None


def validate_batch(
    df: pd.DataFrame, expected_batch_name: str | None = None
) -> ValidationResult:
    """Ejecuta la validación contractual de un lote de vuelos contra 6 reglas estrictas.

    La función nunca aborta con excepciones no controladas ante datos sucios.
    Captura cualquier violación en `errors`.

    Reglas evaluadas:
    1. Esquema exacto: Las columnas deben coincidir en nombre y orden con EXPECTED_COLUMNS.
       Si falla, retorna inmediatamente is_valid=False.
    2. Volumen de muestra fijo: Exactamente 12.000 filas.
    3. Integridad y unicidad: 0 nulos en todas las columnas y 0 duplicados en vuelo_id.
    4. Dominio de aeropuertos: origen in {"JFK", "LGA", "EWR"}, destino regex ^[A-Z]{3}$,
       y origen != destino.
    5. Tipos y rangos físicos: distancia_millas [10, 6000], demoras [-120, 1500].
    6. Coherencia temporal y etiqueta de lote: fecha YYYY-MM-DD en año 2013, un único
       mes calendario por lote, y columna 'lote' consistente con expected_batch_name.

    Args:
        df: DataFrame del lote a validar.
        expected_batch_name: Nombre esperado del lote (ej. 'referencia', 'control', 'nuevo').

    Returns:
        ValidationResult: Objeto con el resultado del contrato y detalle de errores.
    """
    errors: list[str] = []
    row_count = len(df) if isinstance(df, pd.DataFrame) else 0

    # Determinar nombre preliminar del lote
    batch_name = expected_batch_name if expected_batch_name is not None else "desconocido"
    if isinstance(df, pd.DataFrame) and "lote" in df.columns and len(df) > 0:
        non_null_lotes = df["lote"].dropna().unique()
        if len(non_null_lotes) == 1:
            batch_name = str(non_null_lotes[0]) if expected_batch_name is None else expected_batch_name
        elif len(non_null_lotes) > 1 and expected_batch_name is None:
            batch_name = f"mixto({','.join(map(str, non_null_lotes[:2]))})"

    try:
        if not isinstance(df, pd.DataFrame):
            errors.append(f"El objeto recibido no es un DataFrame de pandas: {type(df)}.")
            return ValidationResult(
                batch_name=batch_name,
                is_valid=False,
                errors=errors,
                row_count=row_count,
                period=None,
            )

        # -------------------------------------------------------------
        # Regla 1: Esquema exacto
        # -------------------------------------------------------------
        actual_cols = list(df.columns)
        if actual_cols != EXPECTED_COLUMNS:
            missing_cols = [c for c in EXPECTED_COLUMNS if c not in actual_cols]
            extra_cols = [c for c in actual_cols if c not in EXPECTED_COLUMNS]
            detalles = []
            if missing_cols:
                detalles.append(f"columnas faltantes: {missing_cols}")
            if extra_cols:
                detalles.append(f"columnas adicionales no permitidas: {extra_cols}")
            if not missing_cols and not extra_cols:
                detalles.append(
                    f"orden incorrecto de columnas (esperado: {EXPECTED_COLUMNS}, recibido: {actual_cols})"
                )
            errors.append(f"Violación de esquema exacto: {', '.join(detalles)}.")
            # Si el esquema falla, retorna inmediatamente is_valid=False
            return ValidationResult(
                batch_name=batch_name,
                is_valid=False,
                errors=errors,
                row_count=row_count,
                period=None,
            )

        # -------------------------------------------------------------
        # Regla 2: Volumen de muestra fijo (12.000 filas)
        # -------------------------------------------------------------
        if row_count != EXPECTED_ROW_COUNT:
            errors.append(
                f"Violación de volumen de muestra: se esperaban exactamente {EXPECTED_ROW_COUNT} filas, pero se recibieron {row_count}."
            )

        # -------------------------------------------------------------
        # Regla 3: Integridad y unicidad
        # -------------------------------------------------------------
        null_counts = df.isna().sum()
        if null_counts.any():
            null_cols = null_counts[null_counts > 0].to_dict()
            errors.append(
                f"Violación de integridad: se detectaron valores nulos en columnas: {null_cols}."
            )

        dup_vuelo_id = int(df["vuelo_id"].duplicated().sum())
        if dup_vuelo_id > 0:
            errors.append(
                f"Violación de unicidad: se encontraron {dup_vuelo_id} registros con 'vuelo_id' duplicado."
            )

        # -------------------------------------------------------------
        # Regla 4: Dominio de aeropuertos
        # -------------------------------------------------------------
        invalid_origen_mask = ~df["origen"].astype(str).isin(ALLOWED_ORIGINS)
        if invalid_origen_mask.any():
            invalid_origins = df.loc[invalid_origen_mask, "origen"].dropna().unique().tolist()
            errors.append(
                f"Violación de dominio en 'origen': {invalid_origen_mask.sum()} filas tienen aeropuertos no autorizados: {invalid_origins}. Permitidos: {ALLOWED_ORIGINS}."
            )

        dest_str = df["destino"].astype(str)
        invalid_dest_mask = ~dest_str.str.match(IATA_REGEX, na=False)
        if invalid_dest_mask.any():
            invalid_destinations = df.loc[invalid_dest_mask, "destino"].dropna().unique().tolist()
            errors.append(
                f"Violación de dominio en 'destino': {invalid_dest_mask.sum()} filas no cumplen con el código IATA de 3 letras mayúsculas: {invalid_destinations}."
            )

        same_origin_dest_mask = (df["origen"] == df["destino"])
        if same_origin_dest_mask.any():
            errors.append(
                f"Violación de coherencia de ruta: {same_origin_dest_mask.sum()} filas presentan 'origen' idéntico a 'destino'."
            )

        # -------------------------------------------------------------
        # Regla 5: Tipos y rangos físicos
        # -------------------------------------------------------------
        # distancia_millas
        dist_numeric = pd.to_numeric(df["distancia_millas"], errors="coerce")
        non_num_dist = dist_numeric.isna() & df["distancia_millas"].notna()
        if non_num_dist.any():
            errors.append(
                f"Violación de tipo de dato: {non_num_dist.sum()} filas en 'distancia_millas' no son numéricas."
            )
        valid_dist = dist_numeric.dropna()
        out_dist = (valid_dist < MIN_DISTANCIA) | (valid_dist > MAX_DISTANCIA)
        if out_dist.any():
            errors.append(
                f"Violación de rango físico: {out_dist.sum()} filas con 'distancia_millas' fuera de [{MIN_DISTANCIA}, {MAX_DISTANCIA}]."
            )

        # demora_salida_min
        dep_numeric = pd.to_numeric(df["demora_salida_min"], errors="coerce")
        non_num_dep = dep_numeric.isna() & df["demora_salida_min"].notna()
        if non_num_dep.any():
            errors.append(
                f"Violación de tipo de dato: {non_num_dep.sum()} filas en 'demora_salida_min' no son numéricas."
            )
        valid_dep = dep_numeric.dropna()
        out_dep = (valid_dep < MIN_DEMORA) | (valid_dep > MAX_DEMORA)
        if out_dep.any():
            errors.append(
                f"Violación de rango físico: {out_dep.sum()} filas con 'demora_salida_min' fuera de [{MIN_DEMORA}, {MAX_DEMORA}]."
            )

        # demora_llegada_min
        arr_numeric = pd.to_numeric(df["demora_llegada_min"], errors="coerce")
        non_num_arr = arr_numeric.isna() & df["demora_llegada_min"].notna()
        if non_num_arr.any():
            errors.append(
                f"Violación de tipo de dato: {non_num_arr.sum()} filas en 'demora_llegada_min' no son numéricas."
            )
        valid_arr = arr_numeric.dropna()
        out_arr = (valid_arr < MIN_DEMORA) | (valid_arr > MAX_DEMORA)
        if out_arr.any():
            errors.append(
                f"Violación de rango físico: {out_arr.sum()} filas con 'demora_llegada_min' fuera de [{MIN_DEMORA}, {MAX_DEMORA}]."
            )

        # -------------------------------------------------------------
        # Regla 6: Coherencia temporal y etiqueta de lote
        # -------------------------------------------------------------
        period: str | None = None
        date_series = df["fecha"].astype(str)
        format_valid = date_series.str.match(DATE_REGEX, na=False)
        parsed_dates = pd.to_datetime(df["fecha"], format="%Y-%m-%d", errors="coerce")
        invalid_dates_mask = (~format_valid) | (parsed_dates.isna() & df["fecha"].notna())

        if invalid_dates_mask.any():
            errors.append(
                f"Violación temporal: {invalid_dates_mask.sum()} filas contienen fechas inválidas o que no cumplen el formato YYYY-MM-DD."
            )
        else:
            # Pertenecer al año 2013
            year_mask = parsed_dates.dt.year != 2013
            if year_mask.any():
                invalid_years = parsed_dates.loc[year_mask].dt.year.unique().tolist()
                errors.append(
                    f"Violación temporal: {year_mask.sum()} filas no corresponden al año 2013 (años detectados: {invalid_years})."
                )

            # Un único mes calendario
            unique_months = parsed_dates.dt.month.unique()
            if len(unique_months) != 1:
                errors.append(
                    f"Violación temporal: el lote contiene múltiples meses calendario: {sorted(unique_months.tolist())}. Se requiere un único mes calendario."
                )
            elif not year_mask.any():
                detected_month = int(unique_months[0])
                period = f"2013-{detected_month:02d}"

        # Etiqueta de lote
        unique_lotes = df["lote"].dropna().unique()
        if len(unique_lotes) == 0:
            errors.append("Violación de etiqueta de lote: la columna 'lote' no contiene ningún valor no nulo.")
            actual_lote = "desconocido"
        elif len(unique_lotes) > 1:
            errors.append(
                f"Violación de etiqueta de lote: se detectaron múltiples valores en 'lote': {unique_lotes.tolist()}. Se requiere un único valor por lote."
            )
            actual_lote = str(unique_lotes[0])
        else:
            actual_lote = str(unique_lotes[0])

        if expected_batch_name is not None:
            # Acepta coincidencia exacta o normalización transparente de prefijo 'lote_'
            matches = (actual_lote == expected_batch_name) or (
                expected_batch_name.startswith("lote_") and actual_lote == expected_batch_name[5:]
            ) or (
                actual_lote.startswith("lote_") and expected_batch_name == actual_lote[5:]
            )
            if not matches:
                errors.append(
                    f"Violación de etiqueta de lote: el valor '{actual_lote}' no coincide con el esperado '{expected_batch_name}'."
                )

        is_valid = (len(errors) == 0)
        return ValidationResult(
            batch_name=batch_name,
            is_valid=is_valid,
            errors=errors,
            row_count=row_count,
            period=period,
        )

    except Exception as exc:
        errors.append(f"Excepción inesperada durante la validación: {type(exc).__name__}: {str(exc)}")
        return ValidationResult(
            batch_name=batch_name,
            is_valid=False,
            errors=errors,
            row_count=row_count,
            period=None,
        )
