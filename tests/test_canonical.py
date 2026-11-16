"""RFC 8785: the RFC's own examples, then properties over many numbers."""

import json
import math
import random

import pytest
from autonomous_aep.canonical import NotCanonical, canonicalize


def test_rfc_8785_section_3_2_2_sample():
    data = json.loads(r"""{"numbers": [333333333.33333329, 1E30, 4.50, 2e-3, 0.000000000000000000000000001],
        "string": "\u20ac$\u000F\u000aA'\u0042\u0022\u005c\\\"\/", "literals": [null, true, false]}""")
    assert canonicalize(data) == (
        '{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],'
        '"string":"€$\\u000f\\nA\'B\\"\\\\\\\\\\"/"}'
    )


def test_rfc_8785_section_3_2_3_sorting_by_utf16():
    data = {"€": 1, "\r": 2, "דּ": 3, "1": 4, "\U0001f600": 5, "\u0080": 6, "ö": 7}
    got = json.loads(canonicalize(data), object_pairs_hook=list)
    assert [k for k, _ in got] == ["\r", "1", "\u0080", "ö", "€", "\U0001f600", "דּ"]


@pytest.mark.parametrize("value, want", [
    (0.0, "0"), (-0.0, "0"), (1.0, "1"), (-1, "-1"), (1e21, "1e+21"), (1e20, "100000000000000000000"),
    (0.000001, "0.000001"), (1e-7, "1e-7"), (9007199254740991, "9007199254740991"),
    (295147905179352830000, "295147905179352830000"), (4.4501477170144023e-308, "4.4501477170144023e-308"),
    (1.7976931348623157e308, "1.7976931348623157e+308"), (123456789012345680000.0, "123456789012345680000"),
    (0.1, "0.1"), (100.0, "100"), (-5e-324, "-5e-324"),
])  # fmt: skip
def test_rfc_8785_numbers(value, want):
    assert canonicalize(value) == want


def test_numbers_round_trip_exactly():
    rnd = random.Random(8785)
    for _ in range(20000):
        f = rnd.uniform(-1, 1) * 10 ** rnd.randint(-320, 308)
        if math.isfinite(f):
            assert float(canonicalize(f)) == f


def test_what_json_cannot_hold_is_refused():
    for bad in (float("nan"), float("inf"), {1: "x"}, {"a": object()}):
        with pytest.raises(NotCanonical):
            canonicalize(bad)
