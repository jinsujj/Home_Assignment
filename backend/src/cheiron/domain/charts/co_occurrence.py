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
  leucovorin + oxaliplatin above merely frequent pairs.
"""

from collections import defaultdict
from collections.abc import Sequence
from itertools import combinations, product

from cheiron.domain.analysis import CoOccurrence, Entity
from cheiron.domain.charts.common import ENTITY_TITLES, Bucket, cohort_suffix
from cheiron.domain.charts.communities import greedy_modularity, modularity
from cheiron.domain.facets import Facet, entity_facets, normalize
from cheiron.domain.trial import Trial
from cheiron.domain.trial_filter import TrialFilter
from cheiron.domain.visualization import Channel, ChartType, FieldType, Visualization

MAX_EDGES_PER_NODE = 4
CANDIDATES_PER_NODE = 4
ANCHOR_SHARE = 0.5
_FILTER_OF = {Entity.DRUG: "intervention", Entity.CONDITION: "condition", Entity.SPONSOR: "sponsor", Entity.COUNTRY: "country"}

_ENTITY_NOTES = {
    Entity.DRUG: "Drugs are interventions of type DRUG or BIOLOGICAL; placebos are excluded.",
    Entity.SPONSOR: "Sponsors include lead sponsors and collaborators.",
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

    nodes: defaultdict[str, Bucket] = defaultdict(Bucket)
    for trial, sources, targets in registered:
        for node_id, facet in sources + targets:
            nodes[node_id].add(trial, (facet.evidence,), facet.label)
    ranked = sorted(nodes, key=lambda n: (-nodes[n].count, nodes[n].label))

    # A trial can list over a thousand sites, i.e. ~10^6 pairs, so links are only counted
    # between the most frequent nodes, from which the displayed ones are chosen anyway.
    candidates = _select(ranked, source, target, CANDIDATES_PER_NODE * plan.max_nodes)
    edges: defaultdict[tuple[str, str], Bucket] = defaultdict(Bucket)
    for trial, sources, targets in registered:
        sources = [node for node in sources if node[0] in candidates]
        targets = [node for node in targets if node[0] in candidates]
        pairs = combinations(sources, 2) if same_kind else product(sources, targets)
        for (a, fa), (b, fb) in pairs:
            edges[a, b].add(trial, (fa.evidence, fb.evidence))

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
    weights = {pair: strong[pair].count for pair in kept_edges if not anchors.keys() & set(pair)}
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
    what = (
        f"{ENTITY_TITLES[source]} co-occurrence network"
        if same_kind
        else f"{ENTITY_TITLES[source]}–{ENTITY_TITLES[target].lower()} network"
    )
    return Visualization(ChartType.NETWORK, what + cohort_suffix(plan.cohorts), encoding, data, tuple(notes))


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
