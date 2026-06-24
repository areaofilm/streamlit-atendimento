from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Iterable

import pandas as pd


ENCODINGS: tuple[str, ...] = ("utf-8", "latin1", "cp1252")
SEPARATORS: tuple[str | None, ...] = (None, ",", ";", "\t")


@dataclass(frozen=True)
class CsvReadResult:
    dataframe: pd.DataFrame
    encoding: str
    separator: str


class CsvReadError(ValueError):
    """Raised when no supported CSV format can be loaded."""


def _read_bytes(source: bytes | bytearray | object) -> bytes:
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    if hasattr(source, "getvalue"):
        return bytes(source.getvalue())
    if hasattr(source, "read"):
        current_position = source.tell() if hasattr(source, "tell") else None
        data = source.read()
        if current_position is not None and hasattr(source, "seek"):
            source.seek(current_position)
        return bytes(data)
    raise TypeError("Fonte de CSV invalida.")


def _cleanup_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = df.dropna(axis=1, how="all")
    df.columns = [str(col).strip() for col in df.columns]
    unnamed = [col for col in df.columns if str(col).lower().startswith("unnamed:")]
    if unnamed:
        df = df.drop(columns=unnamed)
    return df


def read_csv_flexible(source: bytes | bytearray | object) -> CsvReadResult:
    """Read a CSV trying common encodings and separators.

    The function keeps the candidate with the highest column count, which helps
    avoid accepting a semicolon CSV as a single-column comma CSV.
    """

    raw = _read_bytes(source)
    if not raw:
        raise CsvReadError("O arquivo esta vazio.")

    errors: list[str] = []
    candidates: list[CsvReadResult] = []

    for encoding in ENCODINGS:
        for separator in SEPARATORS:
            try:
                df = pd.read_csv(
                    BytesIO(raw),
                    encoding=encoding,
                    sep=separator,
                    engine="python",
                    dtype=str,
                    on_bad_lines="skip",
                )
                df = _cleanup_dataframe(df)
                if df.empty and len(df.columns) == 0:
                    continue
                separator_label = "automatico" if separator is None else separator
                candidates.append(CsvReadResult(df, encoding, separator_label))
            except Exception as exc:  # noqa: BLE001 - all parser errors become friendly UI text.
                errors.append(f"{encoding}/{separator or 'auto'}: {exc}")

    if not candidates:
        detail = "; ".join(errors[-3:]) if errors else "formato nao reconhecido"
        raise CsvReadError(
            "Nao foi possivel ler o CSV. Verifique se o arquivo esta valido "
            f"e tente novamente. Detalhe: {detail}"
        )

    return max(candidates, key=lambda item: (len(item.dataframe.columns), len(item.dataframe)))


def readable_column_options(columns: Iterable[str]) -> list[str]:
    return [str(col) for col in columns]

