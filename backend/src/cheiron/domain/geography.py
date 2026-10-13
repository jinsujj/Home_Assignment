"""Registry country names -> ISO 3166-1 numeric codes, for drawing countries on a map.

country_codes.json covers the registry's 226 location countries (as of API v2.0.5),
generated with pycountry and checked by hand: 14 names needed manual codes (e.g. "Burma",
"Turkey (Türkiye)") and one fuzzy match was wrong ("Kosovo" -> Serbia). Four have no
current code and are left out: Kosovo, Serbia and Montenegro, Federal Republic of
Yugoslavia, Netherlands Antilles.
"""

import json
from functools import cache
from importlib import resources


@cache
def _codes() -> dict[str, str]:
    return json.loads(resources.files("cheiron.domain").joinpath("country_codes.json").read_text())


def iso_numeric(country: str) -> str | None:
    """Three-digit code such as "410" for "South Korea"; None when the country has none."""
    return _codes().get(country)
