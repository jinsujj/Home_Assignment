"""TrialFilter -> ClinicalTrials.gov `/studies` query parameters.

Free text goes into `query.*` (Essie syntax, with the API's synonym expansion, e.g.
"Keytruda" also finds pembrolizumab). Enumerated criteria go into `filter.*`, which
match exactly. Characters that are Essie syntax are stripped from free text, since a
single stray quote makes the API reject the whole request.
"""

import re

from cheiron.domain.trial_filter import TrialFilter

_ESSIE_SYNTAX = re.compile(r'["()\[\]\\]')


def to_params(criteria: TrialFilter) -> dict[str, str]:
    params: dict[str, str] = {}
    for key, value in (
        ("query.cond", criteria.condition),
        ("query.intr", criteria.intervention),
        ("query.spons", criteria.sponsor),
    ):
        if value and (text := _clean(value)):
            params[key] = text

    if criteria.statuses:
        params["filter.overallStatus"] = "|".join(sorted(criteria.statuses))

    advanced = []
    if criteria.country and (country := _clean(criteria.country)):
        advanced.append(f'AREA[LocationCountry]"{country}"')
    if criteria.phases:
        advanced.append(f"AREA[Phase]({' OR '.join(sorted(criteria.phases))})")
    if criteria.study_type:
        advanced.append(f"AREA[StudyType]{criteria.study_type}")
    if criteria.start_year_from is not None or criteria.start_year_to is not None:
        start = f"{criteria.start_year_from}-01-01" if criteria.start_year_from is not None else "MIN"
        end = f"{criteria.start_year_to}-12-31" if criteria.start_year_to is not None else "MAX"
        advanced.append(f"AREA[StartDate]RANGE[{start},{end}]")
    if advanced:
        params["filter.advanced"] = " AND ".join(advanced)

    return params


def essie_phrase(text: str) -> str:
    """Free text made safe to place inside an Essie expression."""
    return " ".join(_ESSIE_SYNTAX.sub(" ", text).split())


_clean = essie_phrase
