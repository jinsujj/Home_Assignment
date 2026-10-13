import pytest

from cheiron.domain.charts.communities import greedy_modularity, modularity


def test_two_dense_groups_joined_by_a_weak_link_split() -> None:
    weights = {("a", "b"): 5, ("b", "c"): 5, ("a", "c"): 5, ("x", "y"): 5, ("y", "z"): 5, ("x", "z"): 5, ("c", "x"): 1}

    clusters = greedy_modularity(["a", "b", "c", "x", "y", "z"], weights)

    assert sorted(map(sorted, clusters)) == [["a", "b", "c"], ["x", "y", "z"]]
    assert modularity(clusters, weights) == pytest.approx(0.4677, abs=1e-3)


def test_nodes_without_links_stay_alone() -> None:
    assert greedy_modularity(["a", "b", "c"], {("a", "b"): 1}) == [["a", "b"], ["c"]]
    assert greedy_modularity(["a", "b"], {}) == [["a"], ["b"]]
    assert modularity([["a"], ["b"]], {}) == 0.0


def test_results_do_not_depend_on_edge_order() -> None:
    edges = [(("a", "b"), 2), (("c", "d"), 2), (("b", "c"), 1)]

    forward = greedy_modularity(["a", "b", "c", "d"], dict(edges))
    backward = greedy_modularity(["a", "b", "c", "d"], dict(reversed(edges)))

    assert forward == backward
