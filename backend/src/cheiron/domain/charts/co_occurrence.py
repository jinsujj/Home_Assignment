"""CoOccurrence -> network graph, with its structure made explicit.

Raw co-occurrence counts are dominated by frequent entities, and above all by the one the
question filtered on (pembrolizumab is in 67% of pembrolizumab trials and links to almost
everything). So the graph also carries:

- anchors: the filtered entity, or any in more than half of the trials; marked, and left out
  of clustering, since they link to most nodes by construction;
- clusters: greedy modularity on shared-trial counts among the other nodes, which on real
  data separates e.g. platinum doublets, FOLFOX/FOLFIRI and other checkpoint inhibitors
  among pembrolizumab's partners;
- association: Jaccard (shared / either) per link, which ranks regimens such as
  leucovorin + oxaliplatin above merely frequent pairs;
- how two entities meet: drugs given together in one arm (combined) or only in different arms
  (compared: pembrolizumab vs docetaxel), and whether a sponsor runs the trial (lead) or
  supports it (collaborator: Merck is a collaborator on 60 of its 86 melanoma pembrolizumab
  trials).
"""

import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from itertools import combinations, product

from cheiron.domain.analysis import CoOccurrence, Entity, Link
from cheiron.domain.charts.common import ENTITY_TITLES, Bucket, cohort_suffix
from cheiron.domain.charts.communities import greedy_modularity, modularity
from cheiron.domain.facets import ARM_GROUP_INTERVENTION, ARM_GROUP_LABEL, Facet, entity_facets, normalize
from cheiron.domain.trial import Arm, Trial
from cheiron.domain.trial_filter import TrialFilter
from cheiron.domain.visualization import Channel, ChartType, Evidence, FieldType, Visualization

MAX_EDGES_PER_NODE = 4
CANDIDATES_PER_NODE = 4
ANCHOR_SHARE = 0.5
_FILTER_OF = {Entity.DRUG: "intervention", Entity.CONDITION: "condition", Entity.SPONSOR: "sponsor", Entity.COUNTRY: "country"}

# Arms list interventions as "Type: Name"; the type is not part of the drug's name.
_ARM_INTERVENTION_TYPE = re.compile(
    r"^(?:drug|biological|device|procedure|radiation|behavioral|genetic|dietary supplement|combination product"
    r"|diagnostic test|other):\s*",
    re.IGNORECASE,
)
_RELATION_OF = {Link.SAME_ARM: "combined", Link.DIFFERENT_ARMS: "compared"}
_TITLES = {Link.SAME_ARM: "Drug combination network", Link.DIFFERENT_ARMS: "Drugs compared in different arms"}

_ENTITY_NOTES = {
    Entity.DRUG: "Drugs are interventions of type DRUG or BIOLOGICAL; placebos are excluded.",
    Entity.SPONSOR: (
        "Sponsors include lead sponsors, who run the trial, and collaborators, often supplying a drug; links "
        "count both (lead_trials, collaborator_trials) and are solid where the sponsor mostly leads, dashed where it "
        "mostly collaborates. Sponsor nodes carry their class (industry, NIH, other government, other)."
    ),
    Entity.CONDITION: "Conditions are the registered condition names.",
    Entity.COUNTRY: "Countries are the countries of the trial's locations.",
    Entity.INVESTIGATOR: (
        "Investigators are the trial's overall officials (principal investigators, study chairs and "
        "directors); placeholders such as 'Medical Director' or the sponsor's name are excluded."
    ),
    Entity.SITE: (
        "Sites are identified by facility, city and country; facilities registered under generic "
        "names such as 'Research Site' cannot be told apart and are excluded."
    ),
}


def build_co_occurrence(plan: CoOccurrence, trials: Sequence[Trial], max_citations: int) -> Visualization:
    source, target = plan.source, plan.target
    same_kind = source is target
    registered = [(trial, _nodes(trial, source), [] if same_kind else _nodes(trial, target)) for trial in trials]

    drug_pairs = same_kind and source is Entity.DRUG
    sponsor_side = Entity.SPONSOR if Entity.SPONSOR in (source, target) and not same_kind else None

    nodes: defaultdict[str, Bucket] = defaultdict(Bucket)
    classes: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for trial, sources, targets in registered:
        for node_id, facet in sources + targets:
            nodes[node_id].add(trial, (facet.evidence,), facet.label)
        if sponsor_side:
            for sponsor in (trial.lead_sponsor, *trial.collaborators):
                if sponsor and sponsor.sponsor_class:
                    classes[f"{Entity.SPONSOR}:{normalize(sponsor.name)}"][sponsor.sponsor_class] += 1
    ranked = sorted(nodes, key=lambda n: (-nodes[n].count, nodes[n].label))

    # A trial can list over a thousand sites, i.e. ~10^6 pairs, so links are only counted
    # between the most frequent nodes, from which the displayed ones are chosen anyway.
    candidates = _select(ranked, source, target, CANDIDATES_PER_NODE * plan.max_nodes)
    edges: defaultdict[tuple[str, str], Bucket] = defaultdict(Bucket)
    how: defaultdict[tuple[str, str], Counter[str]] = defaultdict(Counter)  # combined/compared, lead/collaborator
    without_arms = 0
    for trial, sources, targets in registered:
        sources = [node for node in sources if node[0] in candidates]
        targets = [node for node in targets if node[0] in candidates]
        arms = _drug_arms(trial) if drug_pairs else {}
        without_arms += bool(drug_pairs and len(sources) > 1 and not arms)
        lead = f"{Entity.SPONSOR}:{normalize(trial.lead_sponsor.name)}" if trial.lead_sponsor else None
        pairs = combinations(sources, 2) if same_kind else product(sources, targets)
        for (a, fa), (b, fb) in pairs:
            evidence: tuple[Evidence, ...] = (fa.evidence, fb.evidence)
            if drug_pairs:
                link, arm_evidence = _arm_link(arms.get(a, []), arms.get(b, []), trial.arms)
                evidence = arm_evidence or evidence
                if plan.link is not Link.SAME_TRIAL and link is not plan.link:
                    continue
                if link:
                    how[a, b][_RELATION_OF[link]] += 1
            elif sponsor_side:
                sponsor = a if a.startswith(f"{Entity.SPONSOR}:") else b
                how[a, b]["lead" if sponsor == lead else "collaborator"] += 1
            edges[a, b].add(trial, evidence)

    strong = {pair: b for pair, b in edges.items() if b.count >= plan.min_shared_trials}
    connected = [n for n in ranked if n in {n for pair in strong for n in pair}]
    kept = _select(connected, source, target, plan.max_nodes)
    kept_edges = sorted(
        (pair for pair in strong if pair[0] in kept and pair[1] in kept),
        key=lambda pair: (-strong[pair].count, pair),
    )[: MAX_EDGES_PER_NODE * plan.max_nodes]
    linked = {n for pair in kept_edges for n in pair}
    node_ids = [n for n in connected if n in linked]

    anchors = {n: why for n in node_ids if (why := _anchor_reason(n, nodes[n].count, len(trials), plan.cohort.filter))}
    # Clusters of a drug network follow combinations (regimens), not mere co-registration.
    by_combination = drug_pairs and plan.link is Link.SAME_TRIAL and any(how[p]["combined"] for p in kept_edges)
    weights = {
        pair: weight
        for pair in kept_edges
        if not anchors.keys() & set(pair) and (weight := how[pair]["combined"] if by_combination else strong[pair].count)
    }
    clusters = [c for c in greedy_modularity([n for n in node_ids if n not in anchors], weights) if len(c) > 1]
    cluster_names = [nodes[max(c, key=lambda n: (nodes[n].count, -node_ids.index(n)))].label for c in clusters]
    cluster_of = {n: name for c, name in zip(clusters, cluster_names) for n in c}
    partners: dict[str, int] = defaultdict(int)
    for a, b in kept_edges:
        partners[a] += 1
        partners[b] += 1

    data = {
        "nodes": [
            {
                "id": n,
                "label": nodes[n].label,
                "kind": n.split(":", 1)[0],
                "trial_count": nodes[n].count,
                "community": cluster_of.get(n),
                "anchor": n in anchors,
                "partners": partners[n],
                **({"sponsor_class": _class(classes[n])} if sponsor_side and n.startswith(f"{Entity.SPONSOR}:") else {}),
                "citations": nodes[n].citations(max_citations),
            }
            for n in node_ids
        ],
        "edges": [
            {
                "source": a,
                "target": b,
                "trial_count": strong[a, b].count,
                "association": round(strong[a, b].count / (nodes[a].count + nodes[b].count - strong[a, b].count), 3),
                **_ways(how[a, b], drug_pairs, bool(sponsor_side)),
                "citations": strong[a, b].citations(max_citations),
            }
            for a, b in kept_edges
        ],
    }

    kinds = (source,) if same_kind else (source, target)
    notes = [_ENTITY_NOTES[k] for k in kinds]
    notes.append(
        "Entities are matched by name, ignoring case and spacing; spelling variants "
        "(e.g. brand vs generic names) are not merged."
    )
    notes.append(
        "Node trial_count is the number of trials registering the entity; "
        "edge trial_count is the number of trials registering both."
    )
    if plan.min_shared_trials > 1:
        notes.append(f"Only links shared by at least {plan.min_shared_trials} trials are shown.")
    if len(node_ids) < len(nodes) or len(kept_edges) < len(strong):
        notes.append(
            f"Showing {len(node_ids)} of {len(nodes)} entities, favouring the most frequent, "
            f"and the strongest links between them ({len(kept_edges)})."
        )
    if not strong:
        notes.append("No two entities are registered on the same trial.")
    for n, why in anchors.items():
        notes.append(
            f"{nodes[n].label} is in {round(100 * nodes[n].count / len(trials))}% of the trials ({why}); as an anchor "
            "it links to most entities by construction, so it is marked and left out of clustering."
        )
    if clusters:
        notes.append(
            f"Colours mark {len(clusters)} clusters: entities linked more among themselves than to the rest "
            f"(greedy modularity on shared trials, Q = {modularity(clusters, weights):.2f}), each named after its most "
            "frequent member. Entities in no cluster are linked only through anchors or to several clusters equally."
        )
    if kept_edges:
        notes.append(
            "Edge association = shared trials / trials registering either entity (Jaccard, 0 to 1): high values mark "
            "entities that go together, such as a regimen, rather than merely frequent ones."
        )
    if drug_pairs:
        notes.append(
            "Arms tell how two drugs meet: combined = given together in one arm (an arm offering alternatives, "
            "\"pembrolizumab or nivolumab\", counts too); compared = only in different arms, e.g. pembrolizumab vs "
            "docetaxel. Links carry both counts (combined_trials, compared_trials), and their citations quote the arms."
        )
        notes.append(
            {
                Link.SAME_TRIAL: "Lines are solid where the drugs are mostly combined, dashed where mostly compared, "
                "dotted where the arms do not say"
                + ("; clusters are computed on combinations." if by_combination else "."),
                Link.SAME_ARM: "Links count only trials giving both drugs in one arm: combinations.",
                Link.DIFFERENT_ARMS: "Links count only trials giving the drugs in different arms: comparisons or alternatives.",
            }[plan.link]
        )
        if without_arms:
            notes.append(f"{without_arms} of {len(trials)} trials list no drugs per arm, so their pairs are neither combined nor compared.")

    styles = {"combined": "combined", "compared": "compared", "unknown": "arms do not say"} if drug_pairs else {}
    if sponsor_side:
        styles = {"lead": "sponsor leads", "collaborator": "sponsor collaborates"}
    encoding = {
        "node_id": Channel("id", FieldType.NOMINAL, "Entity"),
        "node_label": Channel("label", FieldType.NOMINAL, " / ".join(ENTITY_TITLES[k] for k in kinds)),
        "node_size": Channel("trial_count", FieldType.QUANTITATIVE, "Trials registering the entity", unit="trials"),
        "node_color": Channel("community", FieldType.NOMINAL, "Cluster", order=tuple(cluster_names)),
        "node_shape": Channel("kind", FieldType.NOMINAL, "Entity type", order=tuple(k.value for k in kinds)),
        "edge_source": Channel("source", FieldType.NOMINAL, "From"),
        "edge_target": Channel("target", FieldType.NOMINAL, "To"),
        "edge_weight": Channel("trial_count", FieldType.QUANTITATIVE, "Shared trials", unit="trials"),
        "edge_strength": Channel("association", FieldType.QUANTITATIVE, "Association (Jaccard)"),
    }
    if styles:
        present = {e["relation"] for e in data["edges"]}
        order = tuple(s for s in styles if s in present)  # a combination network has only combined links
        encoding["edge_style"] = Channel("relation", FieldType.NOMINAL, "How they meet", order=order)
    if sponsor_side:
        present = sorted({c for n in data["nodes"] if (c := n.get("sponsor_class"))})
        encoding["node_category"] = Channel("sponsor_class", FieldType.NOMINAL, "Sponsor class", order=tuple(present))
    if not same_kind:
        what = f"{ENTITY_TITLES[source]}–{ENTITY_TITLES[target].lower()} network"
    else:
        what = _TITLES.get(plan.link, f"{ENTITY_TITLES[source]} co-occurrence network")
    return Visualization(ChartType.NETWORK, what + cohort_suffix(plan.cohorts), encoding, data, tuple(notes))


def _drug_arms(trial: Trial) -> dict[str, list[tuple[int, str]]]:
    """Per drug node id, the arms that give it: (arm index, name as registered in the arm)."""
    found: defaultdict[str, list[tuple[int, str]]] = defaultdict(list)
    for i, arm in enumerate(trial.arms):
        for name in arm.intervention_names:
            found[f"{Entity.DRUG}:{normalize(_ARM_INTERVENTION_TYPE.sub('', name, count=1))}"].append((i, name))
    return found


def _arm_link(
    arms_a: list[tuple[int, str]], arms_b: list[tuple[int, str]], arms: tuple[Arm, ...]
) -> tuple[Link | None, tuple[Evidence, ...]]:
    """How two drugs meet in one trial, with the arms that show it; None when the arms do not say."""
    in_a = dict(arms_a)
    in_b = dict(arms_b)
    if shared := sorted(in_a.keys() & in_b.keys()):
        i = shared[0]
        return Link.SAME_ARM, (
            Evidence(ARM_GROUP_LABEL, arms[i].label),
            Evidence(ARM_GROUP_INTERVENTION, in_a[i]),
            Evidence(ARM_GROUP_INTERVENTION, in_b[i]),
        )
    if arms_a and arms_b:
        (i, name_a), (j, name_b) = arms_a[0], arms_b[0]
        return Link.DIFFERENT_ARMS, (
            Evidence(ARM_GROUP_LABEL, arms[i].label),
            Evidence(ARM_GROUP_INTERVENTION, name_a),
            Evidence(ARM_GROUP_LABEL, arms[j].label),
            Evidence(ARM_GROUP_INTERVENTION, name_b),
        )
    return None, ()


def _ways(counts: Counter[str], drug_pairs: bool, sponsor_side: bool) -> dict[str, int | str]:
    """Edge fields saying how the two entities meet, and which way dominates."""
    if drug_pairs:
        combined, compared = counts["combined"], counts["compared"]
        relation = "combined" if combined and combined >= compared else "compared" if compared else "unknown"
        return {"combined_trials": combined, "compared_trials": compared, "relation": relation}
    if sponsor_side:
        lead, collaborator = counts["lead"], counts["collaborator"]
        return {"lead_trials": lead, "collaborator_trials": collaborator, "relation": "lead" if lead >= collaborator else "collaborator"}
    return {}


def _class(counts: Counter[str]) -> str | None:
    return counts.most_common(1)[0][0] if counts else None


def _nodes(trial: Trial, entity: Entity) -> list[tuple[str, Facet]]:
    """(node id, facet) pairs, sorted by id so undirected edges get one canonical key."""
    return sorted(((f"{entity}:{f.key}", f) for f in entity_facets(trial, entity)), key=lambda p: p[0])


def _anchor_reason(node_id: str, count: int, trials: int, criteria: TrialFilter) -> str | None:
    kind, key = node_id.split(":", 1)
    field = _FILTER_OF.get(Entity(kind))
    if field and getattr(criteria, field) and normalize(getattr(criteria, field)) == key:
        return "the question's own filter"
    if trials and count > ANCHOR_SHARE * trials:
        return "more than half of them"
    return None


def _select(ranked: list[str], source: Entity, target: Entity, max_nodes: int) -> set[str]:
    """Most frequent nodes; a bipartite network shares the budget between both kinds."""
    if source is target:
        return set(ranked[:max_nodes])
    sources = [n for n in ranked if n.startswith(f"{source}:")]
    targets = [n for n in ranked if n.startswith(f"{target}:")]
    n_targets = min(len(targets), max(max_nodes // 2, max_nodes - len(sources)))
    n_sources = min(len(sources), max_nodes - n_targets)
    return set(sources[:n_sources] + targets[:n_targets])
