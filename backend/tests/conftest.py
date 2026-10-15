import pytest

from sentinel.db import get_graph
from sentinel.seed.generator import wipe

TEST_GRAPH = "sentinel_test"


@pytest.fixture(scope="session")
def graph():
    """A throwaway graph so tests never touch the demo graph."""
    g = get_graph(TEST_GRAPH)
    yield g
    wipe(g)
