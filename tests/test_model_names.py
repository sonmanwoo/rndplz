"""Model menu names are English with their version (사용자 요청 2026-10-09: '제미나이 플래시' 대신 영어·버전)."""
import unittest

from rndplz.gemma_bridge import gemma_display_name


class ModelNameTests(unittest.TestCase):
    def test_gemma_ids_read_as_english_names_with_version(self):
        self.assertEqual(gemma_display_name('gemma4:e4b'), 'Gemma 4 E4B')
        self.assertEqual(gemma_display_name('gemma4:e2b'), 'Gemma 4 E2B')
        self.assertEqual(gemma_display_name('gemma4:26b'), 'Gemma 4 26B')
        self.assertEqual(gemma_display_name('gemma4'), 'Gemma 4')

    def test_other_ids_are_left_as_they_are(self):
        self.assertEqual(gemma_display_name('other:x'), 'other:x')


if __name__ == '__main__':
    unittest.main()
