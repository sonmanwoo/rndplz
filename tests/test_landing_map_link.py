"""소개 구역의 역량 주소를 기존 연구 맵 선택 동작에 연결한다."""
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_landing_capability_link_dom_contract():
    result = subprocess.run(
        ['node', 'tests/test_landing_map_link.cjs'], cwd=ROOT,
        capture_output=True, text=True, encoding='utf-8', timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_landing_map_preview_uses_canonical_graph():
    result = subprocess.run(
        ['node', 'tests/test_landing_map_preview.cjs'], cwd=ROOT,
        capture_output=True, text=True, encoding='utf-8', timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
