"""Shared validation helpers for user-entered fund data."""

from __future__ import annotations

import math
import re


_FUND_CODE_RE = re.compile(r"^\d{1,6}$")


def normalize_fund_code(value: object) -> str:
    code = str(value).strip()
    if not _FUND_CODE_RE.fullmatch(code):
        raise ValueError("基金代码必须是 1 到 6 位数字。")
    return code.zfill(6)


def positive_number(value: object, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name}必须是数字。") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field_name}必须是大于 0 的有限数字。")
    return number


def non_negative_number(value: object, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name}必须是数字。") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field_name}不能小于 0。")
    return number
