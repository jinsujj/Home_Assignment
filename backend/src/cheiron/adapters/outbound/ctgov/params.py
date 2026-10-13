"""TrialFilter -> ClinicalTrials.gov `/studies` query parameters.

Free text goes into `query.*` (Essie syntax, with the API's synonym expansion, e.g.
"Keytruda" also finds pembrolizumab). Enumerated criteria go into `filter.*`, which
match exactly. Characters that are Essie syntax are stripped from free text, since a
single stray quote makes the API reject the whole request.
"""

import re

from cheiron.domain.analysis import Dimension
from cheiron.domain.trial_filter import TrialFilter

_ESSIE_SYNTAX = re.compile(r'["()\[\]\\]')

# Phones and word processors type typographic quotes, which the registry does not match:
# "Alzheimer's disease" finds 4,269 trials, "Alzheimer’s disease" none.
_TYPOGRAPHIC_QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})

# Search areas whose values are the domain's category keys. Verified live: for all 4,269
# Alzheimer's disease trials, the registry's count of every category (38 in all) equals
# our own aggregation.
COUNTABLE_AREAS = {
    Dimension.PHASE: "Phase",
    Dimension.STATUS: "OverallStatus",
    Dimension.STUDY_TYPE: "StudyType",
    Dimension.LEAD_SPONSOR_CLASS: "LeadSponsorClass",
    Dimension.INTERVENTION_TYPE: "InterventionType",
}

# Registered fields per free-text criterion. The registry applies its synonyms within them:
# "pembrolizumab", "Keytruda" and "MK-3475" each find the same 2,639 of the 2,974 trials that
# the intervention search returns; the other 335 only mention the drug, e.g. in a description.
REGISTERED_AREAS = {
    "intervention": ("InterventionName", "InterventionOtherName"),
    "condition": ("Condition",),
    "sponsor": ("LeadSponsorName", "CollaboratorName"),
}


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


def category_params(criteria: TrialFilter, dimension: Dimension, key: str) -> dict[str, str]:
    """Trials matching `criteria` that also register `key` under `dimension` (a COUNTABLE_AREAS key)."""
    return _with_clause(to_params(criteria), f"AREA[{COUNTABLE_AREAS[dimension]}]{essie_phrase(key)}")


def mentioned_only_params(criteria: TrialFilter, criterion: str) -> dict[str, str]:
    """Trials matching `criteria` whose registered fields for the free-text `criterion` (a
    REGISTERED_AREAS key) do not match it. Words, not a phrase: "Cancer of the Breast" is a
    registered match for "breast cancer"."""
    words = essie_phrase(getattr(criteria, criterion))
    registered = " OR ".join(f"AREA[{area}]({words})" for area in REGISTERED_AREAS[criterion])
    return _with_clause(to_params(criteria), f"NOT ({registered})")


def _with_clause(params: dict[str, str], clause: str) -> dict[str, str]:
    params["filter.advanced"] = f"{params['filter.advanced']} AND {clause}" if "filter.advanced" in params else clause
    return params


def essie_phrase(text: str) -> str:
    """Free text made safe to place inside an Essie expression."""
    return " ".join(_ESSIE_SYNTAX.sub(" ", text.translate(_TYPOGRAPHIC_QUOTES)).split())


_clean = essie_phrase
