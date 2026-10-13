"""TrialResults -> grouped bar chart of one trial's posted outcomes or adverse events.

Every value is the posted one; citations quote it with its interval. Posted analyses
(hazard ratios, p-values) become notes rather than computed statistics.
"""

from cheiron.domain.analysis import ResultFocus, TrialResults
from cheiron.domain.facets import label, normalize
from cheiron.domain.results import Outcome, OutcomeType, PostedResults
from cheiron.domain.visualization import Channel, ChartType, Citation, Citations, Evidence, FieldType, Visualization

MIN_AT_RISK = 10
TOP_EVENTS = 15

_MEASUREMENT = "resultsSection.outcomeMeasuresModule.outcomeMeasures.classes.categories.measurements"
_OUTCOME_TITLE = "resultsSection.outcomeMeasuresModule.outcomeMeasures.title"
_EVENTS = {True: "resultsSection.adverseEventsModule.seriousEvents", False: "resultsSection.adverseEventsModule.otherEvents"}


def build_trial_results(plan: TrialResults, results: PostedResults) -> Visualization:
    name = trial_name(plan, results)
    if plan.focus is ResultFocus.ADVERSE_EVENTS:
        return _adverse_events(results, name)
    return _outcomes(plan, results, name)


def trial_name(plan: TrialResults, results: PostedResults) -> str:
    """"KEYNOTE-189 (NCT02578680)": the registered acronym, else the name asked for."""
    named = results.acronym or (None if plan.nct_id else plan.trial.strip())
    return f"{named} ({results.nct_id})" if named else results.nct_id


def _outcomes(plan: TrialResults, results: PostedResults, name: str) -> Visualization:
    if plan.outcome:
        wanted = normalize(plan.outcome)
        selected = [o for o in results.outcomes if wanted in normalize(o.label)]
        what, scope = f"Outcomes matching '{plan.outcome}'", f"outcome measures whose title contains '{plan.outcome}'"
    else:
        selected = [o for o in results.outcomes if o.type is OutcomeType.PRIMARY] or list(results.outcomes[:1])
        what, scope = "Primary outcomes", "the primary outcome measures"
    notes = [f"Results as posted on ClinicalTrials.gov for {results.nct_id}; showing {scope}."]
    if not selected:
        titles = "; ".join(dict.fromkeys(o.title for o in results.outcomes))
        notes.append(f"No posted outcome measure matches. Posted measures: {titles}.")
        return Visualization(ChartType.GROUPED_BAR, f"{what} — {name}", {}, [], tuple(notes))

    # One chart has one value scale: keep the measures sharing the first one's kind and unit.
    first = selected[0]
    shown = [o for o in selected if (o.measure, o.unit) == (first.measure, first.unit)]
    other_units = [o.label for o in selected if o not in shown]

    rows, groups = [], {}
    for outcome in shown:
        for value in outcome.values:
            groups.setdefault(value.group, None)
            lower, upper = value.interval
            evidence = [Evidence(_OUTCOME_TITLE, outcome.title), Evidence(f"{_MEASUREMENT}.value", value.raw)]
            if value.lower is not None:
                evidence.append(Evidence(f"{_MEASUREMENT}.lowerLimit", value.lower))
            if value.upper is not None:
                evidence.append(Evidence(f"{_MEASUREMENT}.upperLimit", value.upper))
            if value.spread is not None:
                evidence.append(Evidence(f"{_MEASUREMENT}.spread", value.spread))
            rows.append(
                {
                    "outcome": outcome.label,
                    "group": value.group,
                    "value": value.value,
                    "lower": lower,
                    "upper": upper,
                    "citations": Citations(1, (Citation.of(results.nct_id, results.title, tuple(evidence)),)),
                }
            )
            if value.value is None:
                notes.append(f"{value.group}: '{outcome.label}' was posted as '{value.raw}' (not estimable); no bar is drawn.")

    for outcome in shown:
        for c in outcome.comparisons:
            interval = f" ({c.ci_percent}% CI {c.ci_lower} to {c.ci_upper})" if c.ci_lower and c.ci_upper else ""
            p_value = f", p {c.p_value if c.p_value.startswith(('<', '>', '=')) else '= ' + c.p_value}" if c.p_value else ""
            notes.append(f"{outcome.label}: {c.statistic} {c.value}{interval}{p_value}; {' vs '.join(c.groups)}.")
    if len(shown) <= 3:
        notes += [f"{o.label}: time frame '{o.time_frame}'." for o in shown if o.time_frame]
    if first.dispersion and any(r["lower"] is not None for r in rows):
        spread = any(v.spread is not None and v.lower is None for o in shown for v in o.values)
        notes.append(f"Error bars show {'± ' if spread else ''}the posted {first.dispersion.lower()}.")
    if other_units:
        notes.append(f"Also matching, in other units and not shown: {'; '.join(other_units)}.")

    value_title = label(first.measure)  # the unit travels in Channel.unit, not in the title
    encoding = {
        "x": Channel("outcome", FieldType.NOMINAL, "Outcome", order=tuple(o.label for o in shown)),
        "y": Channel("value", FieldType.QUANTITATIVE, value_title, unit=first.unit),
        "series": Channel("group", FieldType.NOMINAL, "Group", order=tuple(groups)),
    }
    if any(r["lower"] is not None or r["upper"] is not None for r in rows):
        encoding["y_lower"] = Channel("lower", FieldType.QUANTITATIVE, first.dispersion or "Lower limit", unit=first.unit)
        encoding["y_upper"] = Channel("upper", FieldType.QUANTITATIVE, first.dispersion or "Upper limit", unit=first.unit)
    return Visualization(ChartType.GROUPED_BAR, f"{what} — {name}", encoding, rows, tuple(notes))


def _adverse_events(results: PostedResults, name: str) -> Visualization:
    serious = [e for e in results.adverse_events if e.serious]
    events = serious or [e for e in results.adverse_events if not e.serious]
    kind = "Serious adverse events" if serious else "Adverse events"
    notes = [f"Adverse events as posted on ClinicalTrials.gov for {results.nct_id}; percent of participants at risk who were affected."]
    if not events:
        notes.append("No adverse events are posted.")
        return Visualization(ChartType.GROUPED_BAR, f"{kind} — {name}", {}, [], tuple(notes))

    at_risk: dict[str, int] = {}
    for e in events:
        at_risk[e.group] = max(at_risk.get(e.group, 0), e.at_risk)
    kept = [g for g, n in at_risk.items() if n >= MIN_AT_RISK]
    dropped = [f"{g} ({n} at risk)" for g, n in at_risk.items() if n < MIN_AT_RISK]
    if dropped:
        notes.append(f"Groups with fewer than {MIN_AT_RISK} participants at risk are not shown: {'; '.join(dropped)}.")

    by_term: dict[str, dict] = {}
    for e in events:
        if e.group in kept and e.at_risk:
            by_term.setdefault(e.term, {})[e.group] = e
    ranked = sorted(by_term, key=lambda t: (-max(x.affected / x.at_risk for x in by_term[t].values()), t))
    terms = ranked[:TOP_EVENTS]
    if len(ranked) > len(terms):
        notes.append(f"Showing the {len(terms)} most frequent of {len(ranked)} {kind.lower()} terms.")
    notes.append("Participants at risk: " + "; ".join(f"{g}: {at_risk[g]}" for g in kept) + ".")

    path = _EVENTS[bool(serious)]
    rows = []
    for term in terms:
        for group in kept:
            e = by_term[term].get(group)
            if e is None:
                continue
            evidence = (
                Evidence(f"{path}.term", e.term),
                Evidence(f"{path}.stats.numAffected", str(e.affected)),
                Evidence(f"{path}.stats.numAtRisk", str(e.at_risk)),
            )
            rows.append(
                {
                    "event": term,
                    "group": group,
                    "percent": round(100 * e.affected / e.at_risk, 1),
                    "affected": e.affected,
                    "at_risk": e.at_risk,
                    "citations": Citations(1, (Citation.of(results.nct_id, results.title, evidence),)),
                }
            )
    encoding = {
        "x": Channel("event", FieldType.NOMINAL, "Adverse event", order=tuple(terms)),
        "y": Channel("percent", FieldType.QUANTITATIVE, "Participants affected", unit="%"),
        "series": Channel("group", FieldType.NOMINAL, "Group", order=tuple(kept)),
    }
    return Visualization(ChartType.GROUPED_BAR, f"{kind} — {name}", encoding, rows, tuple(notes))
