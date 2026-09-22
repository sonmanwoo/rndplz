import unittest
from types import SimpleNamespace
from unittest.mock import patch

from rndplz.hosted_gemma import HostedGemmaModels
from rndplz.model_conversation import RuntimeMessages


class Relay:
    model = 'gemma4:e4b'

    def __init__(self):
        self.ready = True
        self.fail = False
        self.received = []

    def control(self, command):
        if self.fail:
            raise ValueError('store unavailable')
        return {'models': [self.model] if self.ready else [], 'draining': False}

    def stream(self, messages, model=None, contract=None):
        self.received.append((model, contract, list(messages)))
        messages.provider_dispatched = True
        if messages.runtime_dispatch_observation is not None:
            messages.runtime_dispatch_observation['dispatched'] = True
        yield '연결 확인'


class HostedGemmaTests(unittest.TestCase):
    def setUp(self):
        self.relay = Relay()
        config = SimpleNamespace(provider='codex_oauth', model='gpt-5.5', runtime='hosted_public', max_calls=20)
        self.models = HostedGemmaModels(runtime=SimpleNamespace(config=config), bridge=self.relay)

    def test_catalog_default_and_accurate_local_route(self):
        catalog = self.models.catalog()
        self.assertEqual(catalog['default'], 'runtime')
        self.assertEqual([m['id'] for m in catalog['models']], ['runtime', 'bridge'])
        option = self.models.get('bridge')
        self.assertEqual(option['model'], 'gemma4:e4b')
        self.assertEqual(option['provider'], 'bridge')
        self.assertTrue(option['public_scope'])
        self.assertFalse(option['vision'])
        self.assertFalse(option['local'])

    def test_redis_failure_preserves_runtime_and_never_falls_back(self):
        self.relay.fail = True
        self.assertTrue(self.models.get('runtime')['enabled'])
        self.assertFalse(self.models.catalog()['models'][1]['enabled'])
        with self.assertRaises(ValueError):
            list(self.models.stream('bridge', [{'role': 'user', 'content': 'hello'}]))
        self.assertEqual(self.relay.received, [])
        with self.assertRaises(ValueError):
            self.models.get('bridge:gemma4:26b')

    def test_selected_gemma_dispatch_does_not_consume_gpt_capacity(self):
        self.models.calls['runtime'] = 20
        messages = RuntimeMessages([{'role': 'user', 'content': 'hello'}])
        messages.runtime_dispatch_observation = {}
        messages.generation_deadline = 12345
        self.assertTrue(self.models.has_call_capacity('bridge', provider='bridge', required_calls=2))
        self.assertFalse(self.models.has_call_capacity('bridge', provider='codex_oauth'))
        self.assertEqual(list(self.models.stream('bridge', messages, contract='bounded-contract')), ['연결 확인'])
        self.assertEqual(self.relay.received[0][:2], ('gemma4:e4b', 'bounded-contract'))
        self.assertEqual(self.models.calls['runtime'], 20)
        self.assertTrue(messages.provider_dispatched)
        self.assertTrue(messages.runtime_dispatch_observation['dispatched'])
        self.assertEqual(messages.generation_deadline, 12345)

    def test_runtime_delegates_to_original_observed_adapter(self):
        messages = [{'role': 'user', 'content': 'hello'}]
        with patch('rndplz.hosted_gemma.ObservedRuntimeChatModels.stream', return_value=iter(['existing'])) as original:
            self.assertEqual(list(self.models.stream('runtime', messages, contract='original')), ['existing'])
        original.assert_called_once_with('runtime', messages, contract='original')
        self.assertEqual(self.relay.received, [])


if __name__ == '__main__':
    unittest.main()
