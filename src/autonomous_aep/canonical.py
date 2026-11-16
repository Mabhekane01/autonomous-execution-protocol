"""RFC 8785, the JSON Canonicalization Scheme (JCS), in pure Python: the exact bytes AEP hashes and signs.

Two implementations agree on every commit hash and signature only if they agree on these bytes:
- object members sorted by their names as UTF-16 code units (not code points: an emoji sorts before U+FB33);
- strings escaped as ECMAScript's JSON.stringify does: only `"`, `\\` and the controls below U+0020, the rest UTF-8;
- numbers written as ECMAScript writes an IEEE 754 double (`1.0` is `1`, `1e30` is `1e+30`, `-0` is `0`);
- no whitespace; NaN and infinities refused (JSON has none).
Python's `repr(float)` gives the shortest digits that round-trip, as ECMAScript's Number::toString does; only the
layout differs, and `_number` applies ECMAScript's layout to them.
"""

from __future__ import annotations

import math
from typing import Any

_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


class NotCanonical(ValueError):
    """A value JSON cannot hold (NaN, infinity, a type that is not JSON)."""


def canonicalize(value: Any) -> str:
    """The canonical JSON text of a JSON value (dict, list, str, int, float, bool, None)."""
    out: list[str] = []
    _write(value, out)
    return "".join(out)


def canonical_bytes(value: Any) -> bytes:
    return canonicalize(value).encode("utf-8")


def _write(v: Any, out: list[str]) -> None:
    if v is None:
        out.append("null")
    elif v is True:
        out.append("true")
    elif v is False:
        out.append("false")
    elif isinstance(v, int):
        out.append(_number(float(v)) if abs(v) > 2**53 else str(v))
    elif isinstance(v, float):
        out.append(_number(v))
    elif isinstance(v, str):
        out.append(_string(v))
    elif isinstance(v, list | tuple):
        out.append("[")
        for i, item in enumerate(v):
            if i:
                out.append(",")
            _write(item, out)
        out.append("]")
    elif isinstance(v, dict):
        if not all(isinstance(k, str) for k in v):
            raise NotCanonical("object member names must be strings")
        out.append("{")
        for i, k in enumerate(sorted(v, key=lambda k: k.encode("utf-16-be"))):
            if i:
                out.append(",")
            out.append(_string(k))
            out.append(":")
            _write(v[k], out)
        out.append("}")
    else:
        raise NotCanonical(f"{type(v).__name__} is not a JSON value")


def _string(s: str) -> str:
    parts = ['"']
    for c in s:
        if c in _ESCAPES:
            parts.append(_ESCAPES[c])
        elif ord(c) < 0x20:
            parts.append(f"\\u{ord(c):04x}")
        else:
            parts.append(c)
    parts.append('"')
    return "".join(parts)


def _number(f: float) -> str:
    if math.isnan(f) or math.isinf(f):
        raise NotCanonical("a number that is not finite has no JSON form")
    if f == 0:
        return "0"
    sign = "-" if f < 0 else ""
    r = repr(abs(f))  # the shortest digits that round-trip
    mantissa, _, exp = r.partition("e")
    whole, _, frac = mantissa.partition(".")
    digits = (whole + frac).lstrip("0")
    # n: where the decimal point falls, counted from the first significant digit (ECMAScript's n).
    lead_zeros = len(whole + frac) - len((whole + frac).lstrip("0"))
    n = len(whole) - lead_zeros + (int(exp) if exp else 0)
    digits = digits.rstrip("0") or "0"
    k = len(digits)
    if k <= n <= 21:
        return sign + digits + "0" * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * (-n) + digits
    e = n - 1
    m = digits[0] + ("." + digits[1:] if k > 1 else "")
    return f"{sign}{m}e{'+' if e > 0 else '-'}{abs(e)}"
