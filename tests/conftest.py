import os
import random
import sys
from pathlib import Path

os.environ["BF_NO_AUTOAPP"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from server.config import load_game_data, load_limits


@pytest.fixture
def data():
    return load_game_data()


@pytest.fixture
def limits():
    return load_limits()


@pytest.fixture
def rng():
    return random.Random(1)
