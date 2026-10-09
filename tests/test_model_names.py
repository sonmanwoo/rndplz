"""Model menu names are English with their version (사용자 요청 2026-10-09: '제미나이 플래시' 대신 영어·버전)."""
import unittest

from rndplz.gemma_bridge import gemma_display_name
from rndplz.public_web import PublicModels


class ModelNameTests(unittest.TestCase):
    def test_gemma_ids_read_as_english_names_with_version(self):
        self.assertEqual(gemma_display_name('gemma4:e4b'), 'Gemma 4 E4B')
        self.assertEqual(gemma_display_name('gemma4:e2b'), 'Gemma 4 E2B')
        self.assertEqual(gemma_display_name('gemma4:26b'), 'Gemma 4 26B')
        self.assertEqual(gemma_display_name('gemma4'), 'Gemma 4')

    def test_other_ids_are_left_as_they_are(self):
        self.assertEqual(gemma_display_name('other:x'), 'other:x')

    def test_operator_gemma_options_lead_with_local(self):
        # '로컬' leads a Gemma on the operator PC (chat.js colours it); the status still follows the name.
        models = PublicModels({'RNDPLZ_PUBLIC_MODEL': 'bridge', 'RNDPLZ_BRIDGE_TOKEN': 'fixture-secret',
                               'RNDPLZ_BRIDGE_MODELS': 'gemma4:e4b,gemma4:26b'})
        names = [m['name'] for m in models.catalog()['models'] if m['provider'] == 'bridge']
        self.assertEqual(names, ['로컬 Gemma 4 E4B · 연결 대기', '로컬 Gemma 4 26B · 연결 대기'])


if __name__ == '__main__':
    unittest.main()
