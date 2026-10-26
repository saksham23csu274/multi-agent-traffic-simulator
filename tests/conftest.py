from pathlib import Path

import pytest

from trafficsim.config import RunConfig, config_from_dict
from trafficsim.engine import MesoEngine
from trafficsim.network import build_grid

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def root() -> Path:
    return ROOT


@pytest.fixture
def grid():
    return build_grid(2, 2, block_length_m=100, speed_limit_mps=10)


@pytest.fixture
def engine(grid):
    eng = MesoEngine(grid, step_length_s=1, saturation_flow_vps_per_lane=0.5, yellow_s=3, all_red_s=1)
    eng.start()
    return eng


def make_config(scenario: str = "scenarios/sample_grid.yaml", **sections) -> RunConfig:
    data = {"scenario": str(ROOT / scenario), **sections}
    data.setdefault("outputs", {"html_report": False})
    return config_from_dict(data)
