import json
import time
import unittest
from unittest.mock import patch

from rndplz import chat_models
from rndplz.chat_models import OLLAMA_KEEP_ALIVE, OLLAMA_NO_THINK_CONTRACTS, OLLAMA_NUM_CTX, ChatModels


class Captured(Exception):
    pass


class CapturingOpener:
    def __init__(self, sink):
        self.sink = sink

    def open(self, request, timeout=None):
        self.sink.append(json.loads(request.data.decode('utf-8')))
        raise Captured()


class OllamaRequestTuningTests(unittest.TestCase):
    def payload(self, contract, messages=None):
        models = ChatModels({})
        models.local = [{'id': 'ollama:gemma4:e4b', 'name': 'gemma4:e4b', 'provider': 'ollama',
                         'enabled': True, 'local': True, 'vision': False}]
        models.refreshed = time.monotonic()
        sink = []
        with patch.object(chat_models.urllib.request, 'build_opener', return_value=CapturingOpener(sink)):
            with self.assertRaises(Exception):
                list(models.stream('ollama:gemma4:e4b', messages or [{'role': 'user', 'content': '안녕하세요'}], contract=contract))
        self.assertEqual(len(sink), 1)
        return sink[0]

    def test_consultation_answer_disables_thinking(self):
        # The intent label also runs without thinking: with it, 2.3 s instead of 0.1 s and no better (2026-09-28).
        # A profile request sentence too: its values are checked against the user's own words.
        self.assertEqual(OLLAMA_NO_THINK_CONTRACTS, {'dialogue_answer.v1', 'request_intent.v1', 'profile_request.v1',
                                                     'dialogue_plan.v2', 'dialogue_refine.v1'})
        self.assertIs(self.payload('dialogue_answer.v1')['think'], False)
        intent = self.payload('request_intent.v1')
        self.assertEqual((intent['think'], intent['options']['temperature']), (False, 0))

    def test_plan_thinks_only_when_repairing(self):
        # Thinking was 5 s of an 8 s plan (2026-10-02); a plan repair after a failed validation keeps it.
        for contract in ('dialogue_plan.v2', 'dialogue_refine.v1'):
            with self.subTest(contract=contract):
                self.assertIs(self.payload(contract)['think'], False)
        repair = self.payload('dialogue_plan.v2+think')
        self.assertNotIn('think', repair)
        self.assertEqual(repair['format'], self.payload('dialogue_plan.v2')['format'])  # same schema

    def test_assessment_keeps_model_default_reasoning(self):
        # Without it one assessment in nine failed its quote and coverage checks twice (2026-10-02).
        self.assertNotIn('think', self.payload('dialogue_response.v1'))

    def test_plain_chat_still_disables_thinking(self):
        self.assertIs(self.payload(None)['think'], False)

    def test_model_stays_loaded_between_visitors(self):
        for contract in (None, 'dialogue_plan.v2', 'dialogue_response.v1'):
            with self.subTest(contract=contract):
                payload = self.payload(contract)
                self.assertEqual(payload['keep_alive'], OLLAMA_KEEP_ALIVE)
                self.assertEqual(payload['options']['num_ctx'], OLLAMA_NUM_CTX)
        self.assertEqual(OLLAMA_KEEP_ALIVE, '24h')
        self.assertEqual(OLLAMA_NUM_CTX, 32768)


if __name__ == '__main__':
    unittest.main()
