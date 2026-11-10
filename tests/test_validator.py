"""Suite de pruebas unitarias y de integración para el motor de validación contractual.

Prueba exhaustivamente las 6 reglas contractuales, validación de lotes generados
y resistencia ante datos atípicos o corruptos.
"""

from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from src.prepare_batches import prepare_batches
from src.validator import (
    EXPECTED_COLUMNS,
    EXPECTED_ROW_COUNT,
    ValidationResult,
    validate_batch,
)


@pytest.fixture(scope="session", autouse=True)
def setup_batches():
    """Garantiza la disponibilidad de los lotes particionados en data/batches/."""
    batches_dir = Path("data/batches")
    required = [
        "lote_referencia.csv",
        "lote_control.csv",
        "lote_nuevo.csv",
        "lote_corrupto.csv",
    ]
    if not all((batches_dir / f).is_file() for f in required):
        prepare_batches()


@pytest.fixture
def valid_batch_df() -> pd.DataFrame:
    """Genera en memoria un DataFrame sintético 100% válido de 12.000 filas.

    Cumple estrictamente todas las reglas del contrato contractual.
    """
    n = EXPECTED_ROW_COUNT
    origenes = (["JFK", "LGA", "EWR"] * (n // 3 + 1))[:n]
    destinos = (["ORD", "LAX", "MIA", "ATL"] * (n // 4 + 1))[:n]
    fechas = ["2013-01-15"] * n

    df = pd.DataFrame(
        {
            "vuelo_id": list(range(1, n + 1)),
            "fecha": fechas,
            "origen": origenes,
            "destino": destinos,
            "demora_salida_min": [5.0] * n,
            "demora_llegada_min": [-2.0] * n,
            "distancia_millas": [1000.0] * n,
            "lote": ["referencia"] * n,
        }
    )
    return df


# =====================================================================
# PRUEBAS DE INTEGRACIÓN
# =====================================================================


def test_integration_lote_referencia_valido():
    """Verifica que data/batches/lote_referencia.csv apruebe y detecte 2013-01."""
    path = Path("data/batches/lote_referencia.csv")
    assert path.is_file(), f"No existe el archivo {path}"
    df = pd.read_csv(path)

    result = validate_batch(df, expected_batch_name="referencia")
    assert isinstance(result, ValidationResult)
    assert result.is_valid is True, f"Errores encontrados: {result.errors}"
    assert result.period == "2013-01"
    assert result.row_count == 12000
    assert len(result.errors) == 0


def test_integration_lote_control_valido():
    """Verifica que data/batches/lote_control.csv apruebe y detecte 2013-02."""
    path = Path("data/batches/lote_control.csv")
    assert path.is_file(), f"No existe el archivo {path}"
    df = pd.read_csv(path)

    result = validate_batch(df, expected_batch_name="control")
    assert isinstance(result, ValidationResult)
    assert result.is_valid is True, f"Errores encontrados: {result.errors}"
    assert result.period == "2013-02"
    assert result.row_count == 12000
    assert len(result.errors) == 0


def test_integration_lote_nuevo_valido():
    """Verifica que data/batches/lote_nuevo.csv apruebe y detecte 2013-07."""
    path = Path("data/batches/lote_nuevo.csv")
    assert path.is_file(), f"No existe el archivo {path}"
    df = pd.read_csv(path)

    result = validate_batch(df, expected_batch_name="nuevo")
    assert isinstance(result, ValidationResult)
    assert result.is_valid is True, f"Errores encontrados: {result.errors}"
    assert result.period == "2013-07"
    assert result.row_count == 12000
    assert len(result.errors) == 0


def test_integration_lote_corrupto_rechazado():
    """Verifica que data/batches/lote_corrupto.csv sea rechazado por tamaño y origen."""
    path = Path("data/batches/lote_corrupto.csv")
    assert path.is_file(), f"No existe el archivo {path}"
    df = pd.read_csv(path)

    result = validate_batch(df)
    assert isinstance(result, ValidationResult)
    assert result.is_valid is False
    assert result.row_count == 11500
    assert len(result.errors) >= 2
    # Debe señalar error de volumen y origen inválido
    joined_errors = " ".join(result.errors)
    assert "11500" in joined_errors or "volumen" in joined_errors.lower()
    assert "MIA" in joined_errors or "origen" in joined_errors.lower()


# =====================================================================
# PRUEBAS UNITARIAS AISLADAS
# =====================================================================


def test_unit_base_fixture_valida(valid_batch_df):
    """Verifica que el fixture base cumpla con todas las reglas."""
    res = validate_batch(valid_batch_df, expected_batch_name="referencia")
    assert res.is_valid is True
    assert res.period == "2013-01"
    assert res.row_count == 12000
    assert res.errors == []


def test_unit_schema_missing_column(valid_batch_df):
    """(a) Falla cuando faltan columnas y retorna de forma inmediata."""
    df_missing = valid_batch_df.drop(columns=["distancia_millas"])
    res = validate_batch(df_missing)
    assert res.is_valid is False
    assert res.period is None
    assert any("distancia_millas" in err for err in res.errors)


def test_unit_schema_unexpected_or_reordered_column(valid_batch_df):
    """(a) Falla cuando hay columnas adicionales o el orden está alterado."""
    # Columna adicional
    df_extra = valid_batch_df.copy()
    df_extra["columna_extra"] = 1
    res_extra = validate_batch(df_extra)
    assert res_extra.is_valid is False
    assert any("columna_extra" in err for err in res_extra.errors)

    # Orden alterado
    reversed_cols = list(reversed(EXPECTED_COLUMNS))
    df_reordered = valid_batch_df[reversed_cols]
    res_reordered = validate_batch(df_reordered)
    assert res_reordered.is_valid is False
    assert any("orden" in err.lower() for err in res_reordered.errors)


def test_unit_sample_volume_not_12000(valid_batch_df):
    """(b) Falla cuando el conteo de filas difiere estrictamente de 12.000."""
    # Menos filas (11.999)
    res_short = validate_batch(valid_batch_df.iloc[:11999])
    assert res_short.is_valid is False
    assert any("11999" in err for err in res_short.errors)

    # Más filas (12.001)
    extra_row = valid_batch_df.iloc[0:1].copy()
    extra_row["vuelo_id"] = 999999
    df_long = pd.concat([valid_batch_df, extra_row], ignore_index=True)
    res_long = validate_batch(df_long)
    assert res_long.is_valid is False
    assert any("12001" in err for err in res_long.errors)


@pytest.mark.parametrize(
    "col",
    [
        "vuelo_id",
        "fecha",
        "origen",
        "destino",
        "demora_salida_min",
        "demora_llegada_min",
        "distancia_millas",
        "lote",
    ],
)
def test_unit_integrity_null_value(valid_batch_df, col):
    """(c) Falla cuando existe al menos un valor nulo en cualquier columna."""
    df_null = valid_batch_df.copy()
    df_null.loc[10, col] = np.nan
    res = validate_batch(df_null)
    assert res.is_valid is False
    assert any("nulo" in err.lower() for err in res.errors)


def test_unit_uniqueness_duplicate_vuelo_id(valid_batch_df):
    """(d) Falla cuando hay vuelo_id duplicado."""
    df_dup = valid_batch_df.copy()
    df_dup.loc[5, "vuelo_id"] = df_dup.loc[0, "vuelo_id"]
    res = validate_batch(df_dup)
    assert res.is_valid is False
    assert any("duplicado" in err.lower() for err in res.errors)


def test_unit_airport_domain_invalid_origin(valid_batch_df):
    """(e) Falla cuando el origen no pertenece a {'JFK', 'LGA', 'EWR'}."""
    df_invalid_orig = valid_batch_df.copy()
    df_invalid_orig.loc[0, "origen"] = "MIA"
    res = validate_batch(df_invalid_orig)
    assert res.is_valid is False
    assert any("MIA" in err for err in res.errors)


def test_unit_airport_domain_origin_equals_destination(valid_batch_df):
    """(f) Falla cuando alguna fila tiene origen == destino."""
    df_same = valid_batch_df.copy()
    df_same.loc[0, "origen"] = "JFK"
    df_same.loc[0, "destino"] = "JFK"
    res = validate_batch(df_same)
    assert res.is_valid is False
    assert any("idéntico" in err or "coherencia de ruta" in err for err in res.errors)


@pytest.mark.parametrize(
    "col,bad_value,expected_keyword",
    [
        ("distancia_millas", 9.0, "rango"),      # Menor a 10
        ("distancia_millas", 6001.0, "rango"),   # Mayor a 6000
        ("demora_salida_min", -121.0, "rango"),  # Menor a -120
        ("demora_salida_min", 1501.0, "rango"),  # Mayor a 1500
        ("demora_llegada_min", -121.0, "rango"), # Menor a -120
        ("demora_llegada_min", 1501.0, "rango"), # Mayor a 1500
        ("distancia_millas", "diez", "tipo"),    # No numérico
        ("demora_salida_min", "tarde", "tipo"),  # No numérico
    ],
)
def test_unit_physical_ranges_and_types(valid_batch_df, col, bad_value, expected_keyword):
    """(g) Falla cuando una demora o distancia sale de rango o no es numérica."""
    df_bad = valid_batch_df.copy()
    if isinstance(bad_value, str):
        df_bad[col] = df_bad[col].astype(object)
    df_bad.loc[0, col] = bad_value
    res = validate_batch(df_bad)
    assert res.is_valid is False
    assert any(expected_keyword in err.lower() for err in res.errors)


def test_unit_temporal_coherence_mixed_months(valid_batch_df):
    """(h) Falla cuando se mezclan dos meses distintos en un mismo lote."""
    df_mixed = valid_batch_df.copy()
    # Mitad en enero y mitad en febrero
    df_mixed.loc[:5999, "fecha"] = "2013-01-10"
    df_mixed.loc[6000:, "fecha"] = "2013-02-10"
    res = validate_batch(df_mixed)
    assert res.is_valid is False
    assert res.period is None
    assert any("múltiples meses" in err.lower() for err in res.errors)


def test_unit_temporal_coherence_invalid_year(valid_batch_df):
    """(h) Falla cuando las fechas no pertenecen al año 2013."""
    df_year = valid_batch_df.copy()
    df_year["fecha"] = "2014-01-15"
    res = validate_batch(df_year)
    assert res.is_valid is False
    assert res.period is None
    assert any("2013" in err for err in res.errors)


def test_unit_temporal_coherence_malformed_date(valid_batch_df):
    """(h) Falla cuando la fecha no cumple el formato YYYY-MM-DD o es inválida."""
    df_malformed = valid_batch_df.copy()
    df_malformed.loc[0, "fecha"] = "15/01/2013"
    res = validate_batch(df_malformed)
    assert res.is_valid is False
    assert res.period is None
    assert any("formato" in err.lower() or "inválida" in err.lower() for err in res.errors)


def test_unit_seasonal_destination_allowed(valid_batch_df):
    """Confirma que un destino estacional nuevo de 3 letras (ej. 'MVY' o 'ANC') es aceptado."""
    df_seasonal = valid_batch_df.copy()
    df_seasonal.loc[0, "destino"] = "MVY"  # Martha's Vineyard
    df_seasonal.loc[1, "destino"] = "ANC"  # Anchorage
    res = validate_batch(df_seasonal, expected_batch_name="referencia")
    assert res.is_valid is True
    assert res.errors == []


@pytest.mark.parametrize("invalid_dest", ["LA", "MIAMI", "123", "mvy", "B@N"])
def test_unit_destination_invalid_iata_rejected(valid_batch_df, invalid_dest):
    """Verifica que destinos que no cumplan ^[A-Z]{3}$ sean rechazados."""
    df_bad_dest = valid_batch_df.copy()
    df_bad_dest.loc[0, "destino"] = invalid_dest
    res = validate_batch(df_bad_dest)
    assert res.is_valid is False
    assert any("destino" in err.lower() for err in res.errors)


def test_unit_lote_name_mismatch(valid_batch_df):
    """Falla si la etiqueta lote no coincide con expected_batch_name."""
    res = validate_batch(valid_batch_df, expected_batch_name="control")
    assert res.is_valid is False
    assert any("no coincide" in err.lower() for err in res.errors)


def test_unit_multiple_lote_values(valid_batch_df):
    """Falla si la columna 'lote' contiene más de un valor único."""
    df_multi_lote = valid_batch_df.copy()
    df_multi_lote.loc[0, "lote"] = "control"
    res = validate_batch(df_multi_lote)
    assert res.is_valid is False
    assert any("múltiples valores en 'lote'" in err.lower() for err in res.errors)
