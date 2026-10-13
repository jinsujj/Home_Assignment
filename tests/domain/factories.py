from cheiron.domain.trial import Intervention, InterventionType, PartialDate, Sponsor, SponsorClass, Trial


def trial(nct_id: str, **overrides) -> Trial:
    """A Trial with every attribute empty unless given; dates accept registry strings."""
    for key in ("start_date", "completion_date"):
        if isinstance(overrides.get(key), str):
            overrides[key] = PartialDate.parse(overrides[key])
    defaults = dict(
        title=f"Title of {nct_id}",
        status=None,
        study_type=None,
        phases=(),
        start_date=None,
        completion_date=None,
        enrollment=None,
        conditions=(),
        interventions=(),
        lead_sponsor=None,
        collaborators=(),
        countries=(),
        investigators=(),
        sites=(),
    )
    return Trial(nct_id=nct_id, **(defaults | overrides))


def drug(name: str, type: InterventionType = InterventionType.DRUG) -> Intervention:
    return Intervention(name, type)


def sponsor(name: str, sponsor_class: SponsorClass = SponsorClass.INDUSTRY) -> Sponsor:
    return Sponsor(name, sponsor_class)
