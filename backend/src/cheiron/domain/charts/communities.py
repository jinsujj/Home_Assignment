"""Clusters in a weighted network: greedy modularity maximisation (Clauset–Newman–Moore).

Starting from one cluster per node, the two linked clusters whose merge raises modularity
most are merged until no merge raises it. Ties break by node order, so results are
deterministic. Networks here have at most 200 nodes, so the plain quadratic version is
enough and keeps the domain free of graph libraries.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence

type Edge = tuple[str, str]


def greedy_modularity(nodes: Sequence[str], weights: Mapping[Edge, float]) -> list[list[str]]:
    """Clusters of `nodes`, largest first; nodes without links stay alone."""
    total = sum(weights.values())
    if not total:
        return [[n] for n in nodes]
    degree: dict[str, float] = defaultdict(float)
    for (a, b), w in weights.items():
        degree[a] += w
        degree[b] += w

    members = {i: [n] for i, n in enumerate(nodes)}
    index = {n: i for i, n in enumerate(nodes)}
    share = {i: degree[n] / (2 * total) for i, n in enumerate(nodes)}  # fraction of edge ends
    between: dict[tuple[int, int], float] = defaultdict(float)  # fraction of edge weight, both directions
    for (a, b), w in weights.items():
        between[index[a], index[b]] += w / (2 * total)
        between[index[b], index[a]] += w / (2 * total)

    while True:
        gains = [(2 * (e - share[i] * share[j]), -i, -j) for (i, j), e in between.items() if i < j]
        best = max(gains, default=None)
        if best is None or best[0] <= 1e-12:
            break
        i, j = -best[1], -best[2]
        members[i] += members.pop(j)
        share[i] += share.pop(j)
        merged: dict[tuple[int, int], float] = defaultdict(float)
        for (x, y), e in between.items():
            x, y = (i if x == j else x), (i if y == j else y)
            if x != y:
                merged[x, y] += e
        between = merged

    return sorted(members.values(), key=lambda m: (-len(m), nodes.index(m[0])))


def modularity(clusters: Sequence[Sequence[str]], weights: Mapping[Edge, float]) -> float:
    """Q = sum over clusters of (inner weight / total) - (cluster degree / 2 total)^2."""
    total = sum(weights.values())
    if not total:
        return 0.0
    cluster_of = {n: c for c, members in enumerate(clusters) for n in members}
    inner: dict[int, float] = defaultdict(float)
    degree: dict[int, float] = defaultdict(float)
    for (a, b), w in weights.items():
        degree[cluster_of[a]] += w
        degree[cluster_of[b]] += w
        if cluster_of[a] == cluster_of[b]:
            inner[cluster_of[a]] += w
    return sum(inner[c] / total - (degree[c] / (2 * total)) ** 2 for c in degree)
