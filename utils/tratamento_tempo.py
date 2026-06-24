from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd


def duration_to_seconds(value: Any) -> int:
    """Convert duration-like values to seconds.

    Supported examples: HH:MM:SS, DD HH:MM:SS, "1h 5min 6s",
    "7 minutos 13 segundos", numeric seconds, empty values.
    """

    if value is None:
        return 0
    if isinstance(value, float) and math.isnan(value):
        return 0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(int(value), 0)

    text = str(value).strip().lower()
    if not text or text in {"nan", "none", "null", "-"}:
        return 0

    text = text.replace(",", ".")
    text = re.sub(r"\s+", " ", text)

    colon_match = re.fullmatch(r"(?:(\d+)\s+)?(\d{1,3}):(\d{2})(?::(\d{2}))?", text)
    if colon_match:
        days_or_hours, first, second, third = colon_match.groups()
        if third is None:
            hours = int(days_or_hours or 0)
            minutes = int(first)
            seconds = int(second)
            return hours * 3600 + minutes * 60 + seconds
        days = int(days_or_hours or 0)
        hours = int(first)
        minutes = int(second)
        seconds = int(third)
        return days * 86400 + hours * 3600 + minutes * 60 + seconds

    timedelta = pd.to_timedelta(text, errors="coerce")
    if not pd.isna(timedelta):
        return max(int(timedelta.total_seconds()), 0)

    total = 0.0
    units = {
        "d": 86400,
        "dia": 86400,
        "dias": 86400,
        "h": 3600,
        "hr": 3600,
        "hrs": 3600,
        "hora": 3600,
        "horas": 3600,
        "m": 60,
        "min": 60,
        "mins": 60,
        "minuto": 60,
        "minutos": 60,
        "s": 1,
        "seg": 1,
        "segs": 1,
        "segundo": 1,
        "segundos": 1,
    }
    for number, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([a-z]+)", text):
        multiplier = units.get(unit)
        if multiplier:
            total += float(number) * multiplier

    return max(int(total), 0)


def series_to_seconds(series: pd.Series | None) -> pd.Series:
    if series is None:
        return pd.Series(dtype="int64")
    return series.apply(duration_to_seconds).astype("int64")


def format_seconds(seconds: Any) -> str:
    try:
        total = max(int(round(float(seconds))), 0)
    except (TypeError, ValueError):
        total = 0
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}min{secs:02d}s"
    return f"{minutes}min{secs:02d}s"

