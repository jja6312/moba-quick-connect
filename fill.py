"""Spreadsheet copy/series operations, independent of the view and clipboard."""
from __future__ import annotations

import copy
import ipaddress
import re


def increment(text: str, delta: int) -> str:
    if not text or not delta:
        return text
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        address = None
    if address is not None:
        try:
            return str(address + delta)
        except ValueError:
            raise ValueError("IP 번호 범위를 벗어났습니다.") from None
    if re.fullmatch(r"[+-]?\d+", text):
        value = int(text) + delta
        width = len(text.lstrip("+-"))
        digits = str(abs(value)).zfill(width)
        return ("-" if value < 0 else "+" if text.startswith("+") else "") + digits
    match = re.search(r"(\d+)$", text)
    if not match:
        return text
    value = int(match.group()) + delta
    if value < 0:
        return text[:match.start()] + str(value)
    return text[:match.start()] + str(value).zfill(len(match.group()))


def fill(rows, fields, seed, target, *, series=False):
    """Tile a seed rectangle, or extend its edge by exactly one per new cell.

    Rectangles are (top, left, bottom, right), inclusive. The original seed is
    never changed. A vertical extension increments each selected column; a
    horizontal extension increments each selected row. Non-number strings tile.
    """
    top, left, bottom, right = seed
    ttop, tleft, tbottom, tright = target
    if not (0 <= ttop <= top <= bottom <= tbottom < len(rows) and
            0 <= tleft <= left <= right <= tright < len(fields)):
        raise ValueError("채우기 범위를 확인하세요.")
    if (ttop != top or tbottom != bottom) and (tleft != left or tright != right):
        raise ValueError("한 방향으로 드래그하세요.")
    result = copy.deepcopy(rows)
    height, width = bottom - top + 1, right - left + 1
    for r in range(ttop, tbottom + 1):
        for c in range(tleft, tright + 1):
            if top <= r <= bottom and left <= c <= right:
                continue
            source_r = top + (r - top) % height
            source_c = left + (c - left) % width
            value = rows[source_r][fields[source_c]]
            if series:
                if r > bottom:
                    edge = rows[bottom][fields[source_c]]
                    extended = increment(edge, r - bottom)
                    value = extended if extended != edge else value
                elif r < top:
                    edge = rows[top][fields[source_c]]
                    extended = increment(edge, r - top)
                    value = extended if extended != edge else value
                elif c > right:
                    edge = rows[source_r][fields[right]]
                    extended = increment(edge, c - right)
                    value = extended if extended != edge else value
                elif c < left:
                    edge = rows[source_r][fields[left]]
                    extended = increment(edge, c - left)
                    value = extended if extended != edge else value
            result[r][fields[c]] = value
    return result
