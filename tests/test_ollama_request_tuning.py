import json
import time
import unittest
from unittest.mock import patch

from rndplz import chat_models
from rndplz.chat_models import OLLAMA_KEEP_ALIVE, OLLAMA_NO_THINK_CONTRACTS, ChatModels


class Captured(Exception):
    pass


class CapturingOpener:
    def __init__(self, sink):
        self.sink = sink

    def open(self, request, timeout=None):
        self.sink.append(json.loads(request.data.decode('utf-8')))
        raise Captured()


class OllamaRequestTuningTests(unittest.TestCase):
    def payload(self, contract):
        models = ChatModels({})
        models.local = [{'id': 'ollama:gemma4:e4b', 'name': 'gemma4:e4b', 'provider': 'ollama',
                         'enabled': True, 'local': True, 'vision': False}]
        models.refreshed = time.monotonic()
        sink = []
        with patch.object(chat_models.urllib.request, 'build_opener', return_value=CapturingOpener(sink)):
            with self.assertRaises(Exception):
                list(models.stream('ollama:gemma4:e4b', [{'role': 'user', 'content': '안녕하세요'}], contract=contract))
        self.assertEqual(len(sink), 1)
        return sink[0]

    def test_conversation_contracts_disable_thinking(self):
        self.assertEqual(OLLAMA_NO_THINK_CONTRACTS, {'dialogue_plan.v2', 'dialogue_answer.v1'})
        for contract in sorted(OLLAMA_NO_THINK_CONTRACTS):
            with self.subTest(contract=contract):
                self.assertIs(self.payload(contract)['think'], False)

    def test_assessment_response_keeps_model_default_reasoning(self):
        self.assertNotIn('think', self.payload('dialogue_response.v1'))

    def test_plain_chat_still_disables_thinking(self):
        self.assertIs(self.payload(None)['think'], False)

    def test_model_stays_loaded_between_visitors(self):
        for contract in (None, 'dialogue_plan.v2', 'dialogue_response.v1'):
            with self.subTest(contract=contract):
                self.assertEqual(self.payload(contract)['keep_alive'], OLLAMA_KEEP_ALIVE)
        self.assertEqual(OLLAMA_KEEP_ALIVE, '24h')


if __name__ == '__main__':
    unittest.main()
