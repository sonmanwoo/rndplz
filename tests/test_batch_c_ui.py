"""필수 pytest 실행에 C4/C5의 합성 JS 단위 검사를 포함한다."""
import subprocess
from pathlib import Path


def test_batch_c_dialog_focus_and_touch_targets():
    result = subprocess.run(
        ['node', 'tests/test_batch_c_ui.cjs'],
        cwd=Path(__file__).resolve().parents[1], capture_output=True,
        text=True, encoding='utf-8',
    )
    assert result.returncode == 0, result.stdout + result.stderr
