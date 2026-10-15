import os

os.environ.setdefault("AUTOPILOT_DELAY_S", "0")  # before sentinel.config is imported

import pytest  # noqa: E402

from sentinel.db import get_graph  # noqa: E402
from sentinel.seed.generator import wipe  # noqa: E402

TEST_GRAPH = "sentinel_test"


@pytest.fixture(scope="session")
def graph():
    """A throwaway graph so tests never touch the demo graph."""
    g = get_graph(TEST_GRAPH)
    yield g
    wipe(g)
