"""소개 구역의 지연 로딩, 공개 데이터, 기존 동작 재사용 계약."""
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_landing_ui_dom_contract():
    result = subprocess.run(
        ['node', 'tests/test_landing_ui.cjs'], cwd=ROOT,
        capture_output=True, text=True, encoding='utf-8', timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
