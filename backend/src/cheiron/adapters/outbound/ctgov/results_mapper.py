"""Anti-corruption layer for single-trial lookups: candidates by name, and posted results."""

import re
from typing import Any

from cheiron.adapters.outbound.ctgov.params import essie_phrase
from cheiron.application.ports import TrialCandidate
from cheiron.domain.results import AdverseEvent, Comparison, GroupValue, Outcome, OutcomeType, PostedResults

CANDIDATE_FIELDS = "NCTId,Acronym,OrgStudyId,SecondaryId,BriefTitle,OfficialTitle,HasResults,EnrollmentCount"
NAME_AREAS = ("Acronym", "OrgStudyId", "SecondaryId", "OfficialTitle", "BriefTitle")


def name_variants(name: str) -> tuple[str, ...]:
    """The name as given, and hyphenated between letters and digits: "KEYNOTE 189" -> "KEYNOTE-189"."""
    phrase = essie_phrase(name)
    hyphenated = re.sub(r"(?<=[A-Za-z])[\s_]+(?=\d)", "-", phrase)
    return tuple(dict.fromkeys(p for p in (phrase, hyphenated) if p))


def to_candidate(study: dict[str, Any], name: str) -> TrialCandidate:
    protocol = study.get("protocolSection", {})
    ident = protocol.get("identificationModule", {})
    wanted = _fold(name)
    ids = {_fold(ident.get("orgStudyIdInfo", {}).get("id", ""))}
    ids |= {_fold(s.get("id", "")) for s in ident.get("secondaryIdInfos", [])}
    whole_word = re.compile(rf"(?<![a-z0-9]){re.escape(wanted)}(?![a-z0-9])")
    titles = (_fold(ident.get("officialTitle", "")), _fold(ident.get("briefTitle", "")))
    if ident.get("acronym") and _fold(ident["acronym"]) == wanted:
        matched_by = "acronym"
    elif wanted in ids:
        matched_by = "study_id"
    elif any(whole_word.search(t) for t in titles):
        matched_by = "title"
    else:
        matched_by = None
    return TrialCandidate(
        nct_id=ident["nctId"],
        title=ident.get("briefTitle", ""),
        acronym=ident.get("acronym"),
        has_results=bool(study.get("hasResults")),
        enrollment=protocol.get("designModule", {}).get("enrollmentInfo", {}).get("count"),
        matched_by=matched_by,
    )


def to_results(study: dict[str, Any]) -> PostedResults:
    ident = study.get("protocolSection", {}).get("identificationModule", {})
    section = study.get("resultsSection", {})
    return PostedResults(
        nct_id=ident["nctId"],
        title=ident.get("briefTitle", ""),
        acronym=ident.get("acronym"),
        outcomes=tuple(o for m in section.get("outcomeMeasuresModule", {}).get("outcomeMeasures", []) for o in _outcomes(m)),
        adverse_events=_adverse_events(section.get("adverseEventsModule", {})),
    )


def _outcomes(measure: dict[str, Any]) -> list[Outcome]:
    groups = _group_titles(measure.get("groups", []))
    comparisons = tuple(
        Comparison(
            groups=tuple(groups.get(g, g) for g in a.get("groupIds", [])),
            statistic=a.get("paramType") or a.get("statisticalMethod") or "Comparison",
            value=a.get("paramValue", ""),
            ci_percent=a.get("ciPctValue"),
            ci_lower=a.get("ciLowerLimit"),
            ci_upper=a.get("ciUpperLimit"),
            p_value=a.get("pValue"),
        )
        for a in measure.get("analyses", [])
        if a.get("paramValue")
    )
    classes = measure.get("classes", [])
    split = len(classes) > 1 or any(len(c.get("categories", [])) > 1 for c in classes)
    outcomes = []
    for cls in classes:
        for category in cls.get("categories", []):
            row = " / ".join(t for t in (cls.get("title"), category.get("title")) if t) if split else None
            values = tuple(
                GroupValue(groups.get(m["groupId"], m["groupId"]), m.get("value", ""), m.get("lowerLimit"), m.get("upperLimit"), m.get("spread"))
                for m in category.get("measurements", [])
            )
            outcomes.append(
                Outcome(
                    type=_outcome_type(measure.get("type")),
                    title=measure.get("title", ""),
                    row=row or None,
                    measure=measure.get("paramType", ""),
                    dispersion=measure.get("dispersionType"),
                    unit=measure.get("unitOfMeasure", ""),
                    time_frame=measure.get("timeFrame", ""),
                    values=values,
                    comparisons=comparisons,
                )
            )
    return outcomes


def _adverse_events(module: dict[str, Any]) -> tuple[AdverseEvent, ...]:
    groups = _group_titles(module.get("eventGroups", []))
    return tuple(
        AdverseEvent(
            term=event.get("term", ""),
            organ_system=event.get("organSystem", ""),
            serious=serious,
            group=groups.get(stat["groupId"], stat["groupId"]),
            affected=stat["numAffected"],
            at_risk=stat["numAtRisk"],
        )
        for serious, key in ((True, "seriousEvents"), (False, "otherEvents"))
        for event in module.get(key, [])
        for stat in event.get("stats", [])
        if stat.get("numAffected") is not None and stat.get("numAtRisk") is not None
    )


def _group_titles(groups: list[dict[str, Any]]) -> dict[str, str]:
    """Group id -> title, made unique: two groups may share a title."""
    titles: dict[str, str] = {}
    seen: set[str] = set()
    for group in groups:
        title = (group.get("title") or group["id"]).strip()
        titles[group["id"]] = f"{title} ({group['id']})" if title in seen else title
        seen.add(title)
    return titles


def _outcome_type(raw: str | None) -> OutcomeType | None:
    try:
        return OutcomeType(raw) if raw else None
    except ValueError:
        return None


def _fold(text: str) -> str:
    """Case-insensitive, with hyphens, underscores and spacing treated alike: "KEYNOTE 189" = "keynote-189"."""
    return " ".join(re.sub(r"[-_‐–]", " ", text).casefold().split())
