from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "render_q3_chart.py"


def load_renderer():
    spec = importlib.util.spec_from_file_location("render_q3_chart", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_committed_extract_is_the_complete_2020_age_5_subfield_slice() -> None:
    renderer = load_renderer()

    points = renderer.load()

    assert len(points) == 11
    assert {point.publication_year for point in points} == {2020}
    assert {point.citation_age for point in points} == {5}
    assert {point.subfield_id for point in points} == {
        "1702",
        "1703",
        "1704",
        "1705",
        "1706",
        "1707",
        "1708",
        "1709",
        "1710",
        "1711",
        "1712",
    }


def test_render_is_accessible_and_identifies_the_load_bearing_points() -> None:
    renderer = load_renderer()

    svg = renderer.render(renderer.LIGHT, renderer.load())

    assert 'role="img"' in svg
    assert "2020 computer science subfields" in svg
    assert "Artificial Intelligence" in svg
    assert "Computer Vision / PR" in svg
    assert "Computer Graphics" in svg
    assert "Information Systems" in svg
    assert "more papers reached" in svg
    assert "winnings more concentrated" in svg
