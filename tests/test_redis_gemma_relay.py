"""Eight shared-relay boundaries; real CAS Lua in local fakeredis/Lupa.

No live Redis/HTTP/model/worker process. Test-only dependencies are reused from
the existing workspace; no product dependency or package installation is added.
"""
import concurrent.futures
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import types
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve()
DEPS = Path(os.environ.get('RNDPLZ_REDIS_TESTDEPS',
    str(HERE.parents[3] / 'vercel-shared-state-20260922' / 'testdeps')))
sys.path[:0] = [str(HERE.parents[1]), str(DEPS)]
import fakeredis
from rndplz import redis_gemma_relay as relay


class Messages(list):
    def __init__(self):
        super().__init__([{'role': 'user', 'content': 'synthetic request only'}])
        self.provider_dispatched = False
        self.runtime_dispatch_observation = {'dispatched': False}


class Consumer:
    def __init__(self, owner, **kwargs):
        self.messages = kwargs.pop('messages', Messages())
        self.generator = owner.stream(self.messages, **kwargs)
        self.chunks, self.errors = [], []
        self.done = threading.Event()
        def consume():
            try:
                self.chunks.extend(self.generator)
            except Exception as error:
                self.errors.append(error)
            finally:
                self.done.set()
        self.thread = threading.Thread(target=consume, daemon=True)
        self.thread.start()

    def finish(self, test):
        test.assertTrue(self.done.wait(3), 'synthetic stream did not stop')
        self.thread.join()


class RedisGemmaRelayTests(unittest.TestCase):
    def setUp(self):
        self.client = fakeredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)
        self.env = {'KV_REST_API_URL': 'https://synthetic.invalid',
                    'KV_REST_API_TOKEN': 'synthetic-redis-only',
                    'RNDPLZ_STATE_NAMESPACE': 'synthetic-gemma',
                    'RNDPLZ_BRIDGE_TOKEN': 'synthetic-worker-only'}
        self.commands, self.events, self.consumers = [], [], []
        self.mutex = threading.Lock()
        self.conflicts = 0
        self.lose_reply = False
        self.clock = time.time()
        def command(store, args, timeout=5.0):
            with self.mutex:
                self.commands.append(args[0])
                if args[0] == 'EVAL' and self.conflicts:
                    self.conflicts -= 1
                    return 0  # Explicit conflict only; never a response-loss retry.
                result = self.client.execute_command(*args)
                if args[0] == 'EVAL' and self.lose_reply:
                    self.lose_reply = False
                    raise ValueError('synthetic lost response')
                return result
        for replacement in (
            patch.object(relay.RedisStateStore, '_command', command),
            patch.object(relay, '_POLL_SECONDS', 0),
            patch.object(relay, '_INTERVAL', .005),
            patch.object(relay, 'time', types.SimpleNamespace(
                time=lambda: self.clock, monotonic=time.monotonic, sleep=time.sleep)),
            patch.object(relay, '_capture_relay_scope', return_value=None),
            patch.object(relay, '_relay_event', side_effect=lambda scope, kind, **data: self.events.append((kind, data))),
            patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('external HTTP forbidden')),
            patch('subprocess.Popen', side_effect=AssertionError('child process forbidden')),
            patch('socket.create_connection', side_effect=AssertionError('network forbidden')),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)
        self.a = relay.RedisGemmaRelay(self.env)
        self.b = relay.RedisGemmaRelay(self.env)
        self.b.poll(['gemma4:e4b'], capabilities=['dialogue_plan.v2'])
        self.addCleanup(self.shutdown)

    def start(self, owner, **kwargs):
        consumer = Consumer(owner, **kwargs)
        self.consumers.append(consumer)
        return consumer

    def shutdown(self):
        # Finish synthetic threads before removing the no-network command stub.
        self.client.delete(self.a._key)
        for consumer in self.consumers:
            consumer.thread.join(3)
            self.assertFalse(consumer.thread.is_alive())
        self.client.close()

    def wait_jobs(self, count):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            state = self.a._snapshot()
            if len(state['jobs']) == count:
                return state
            time.sleep(.005)
        self.fail('synthetic queue did not reach expected count')

    def packet(self, job, sequence=0, text='synthetic answer', done=True, observed=True):
        packet = {'id': job['id'], 'lease': job['lease'], 'trace_id': job['trace_id'],
                  'sequence': sequence, 'text': text, 'done': done}
        if observed:
            packet['diagnostics'] = {
                'version': 1, 'worker_instance': 'a' * 32,
                'worker_source_fingerprint': 'b' * 64, 'prompt_sha256': 'c' * 64,
                'worker_input_fingerprint': 'd' * 64, 'model_job': job['model']}
        return packet

    def test_01_two_instances_stream_snapshots_and_dispatch_evidence(self):
        consumer = self.start(self.a, contract='dialogue_plan.v2')
        self.wait_jobs(1)
        job = self.b.poll(['gemma4:e4b'], capabilities=['dialogue_plan.v2'])
        self.assertEqual(job['messages'], consumer.messages)
        self.assertEqual(job['contract'], 'dialogue_plan.v2')
        self.assertFalse(consumer.messages.provider_dispatched)
        self.assertFalse(consumer.messages.runtime_dispatch_observation['dispatched'])
        first = self.packet(job, text='part one', done=False)
        self.b.deliver(first)
        self.b.deliver(copy.deepcopy(first))
        self.b.deliver(self.packet(job, 1, text=' / part two'))
        consumer.finish(self)
        self.assertFalse(consumer.errors)
        self.assertEqual(''.join(consumer.chunks), 'part one / part two')
        self.assertTrue(consumer.messages.provider_dispatched)
        self.assertTrue(consumer.messages.runtime_dispatch_observation['dispatched'])
        self.assertEqual(self.a.control('status')['active_jobs'], 0)
        kinds = [kind for kind, data in self.events]
        for kind in ('relay_queued', 'relay_claimed', 'relay_first_delta', 'relay_done'):
            self.assertEqual(kinds.count(kind), 1)
        logged = json.dumps(self.events)
        self.assertNotIn('synthetic request only', logged)
        self.assertNotIn('part one', logged)

    def test_02_two_claimants_capacity_and_single_claim(self):
        first, second = self.start(self.a), self.start(self.b)
        self.wait_jobs(2)
        with self.assertRaises(ValueError):
            next(self.a.stream(Messages()))
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            jobs = list(pool.map(lambda r: r.poll(['gemma4:e4b']), (self.a, self.b)))
        self.assertEqual(len({job['id'] for job in jobs}), 2)
        self.assertIsNone(self.b.poll(['gemma4:e4b']))
        for job in jobs:
            self.b.deliver(self.packet(job))
        for consumer in (first, second):
            consumer.finish(self)
            self.assertFalse(consumer.errors)

    def test_03_lease_order_duplicate_bounds_and_stable_metadata(self):
        consumer = self.start(self.a)
        self.wait_jobs(1)
        job = self.b.poll(['gemma4:e4b'])
        original = self.packet(job, text='a', done=False)
        for change in ({'lease': 'f' * 48}, {'sequence': 1}, {'sequence': True}, {'text': 'x' * 24001}):
            with self.assertRaises(ValueError):
                self.b.deliver({**original, **change})
        self.b.deliver(original)
        self.b.deliver(copy.deepcopy(original))
        with self.assertRaises(ValueError):
            self.b.deliver({**original, 'text': 'changed duplicate'})
        changed = self.packet(job, 1, text='b', done=False)
        changed['diagnostics']['worker_input_fingerprint'] = 'e' * 64
        with self.assertRaises(ValueError):
            self.b.deliver(changed)
        self.b.deliver(self.packet(job, 1, text='b'))
        consumer.finish(self)
        self.assertEqual(''.join(consumer.chunks), 'ab')
        self.assertFalse(consumer.errors)
        with self.assertRaises(ValueError):
            self.b.deliver(self.packet(job, 2))

    def test_04_generator_cancel_and_job_expiry_reject_late_results(self):
        generator = self.a.stream(Messages())
        returned = []
        thread = threading.Thread(target=lambda: returned.append(next(generator)), daemon=True)
        thread.start()
        self.wait_jobs(1)
        job = self.b.poll(['gemma4:e4b'])
        self.b.deliver(self.packet(job, text='partial', done=False))
        thread.join(2)
        self.assertEqual(returned, ['partial'])
        generator.close()
        self.assertEqual(self.b.control('status')['active_jobs'], 0)
        with self.assertRaises(ValueError):
            self.b.deliver(self.packet(job, 1))
        expired = self.start(self.a)
        self.wait_jobs(1)
        old = self.b.poll(['gemma4:e4b'])
        self.clock += 151
        self.assertEqual(self.b.control('status')['active_jobs'], 0)
        expired.finish(self)
        self.assertEqual(len(expired.errors), 1)
        with self.assertRaises(ValueError):
            self.b.deliver(self.packet(old))
        self.assertFalse(self.a.online)
        self.assertGreater(self.client.ttl(self.a._key), 0)
        self.assertLessEqual(self.client.ttl(self.a._key), 300)

    def test_05_control_contract_identity_and_corruption_fail_closed(self):
        self.assertTrue(self.a.authorized(self.env['RNDPLZ_BRIDGE_TOKEN']))
        self.assertFalse(self.a.authorized('wrong'))
        self.assertFalse(self.a.authorized(None))
        self.assertEqual(self.a.available_models, {'gemma4:e4b'})
        self.assertIn('dialogue_plan.v2', self.a.available_capabilities)
        self.a.control('drain')
        self.assertTrue(self.b.control('status')['draining'])
        with self.assertRaises(ValueError):
            next(self.b.stream(Messages()))
        self.b.control('resume')
        with self.assertRaises(ValueError):
            next(self.a.stream(Messages(), contract='dialogue_response.v1'))
        other = relay.RedisGemmaRelay({**self.env, 'RNDPLZ_BRIDGE_TOKEN': 'other'})
        namespace = relay.RedisGemmaRelay({**self.env, 'RNDPLZ_STATE_NAMESPACE': 'other'})
        self.assertEqual(len({self.a._key, other._key, namespace._key, self.a._store._state_key}), 4)
        self.assertFalse(other.online)
        self.assertFalse(namespace.online)
        before = len(self.commands)
        self.assertEqual(other.control('status')['active_jobs'], 0)
        self.assertEqual(self.commands[before:], ['GET'])
        self.assertIsNone(self.client.get(other._key))
        self.client.set(self.a._key, '{corrupt')
        with self.assertRaises(ValueError):
            self.a.control('status')
        self.assertEqual(self.client.get(self.a._key), '{corrupt')
        with self.assertRaises(ValueError):
            relay.RedisGemmaRelay({**self.env, 'KV_REST_API_URL': 'http://synthetic.invalid'})

    def test_06_explicit_cas_conflicts_bounded_and_ambiguous_claim_not_replayed(self):
        self.conflicts = 2
        self.a.control('drain')
        self.assertEqual(self.conflicts, 0)
        self.a.control('resume')
        consumer = self.start(self.a)
        self.wait_jobs(1)
        self.lose_reply = True
        with self.assertRaisesRegex(ValueError, 'lost response'):
            self.b.poll(['gemma4:e4b'])
        state = self.a._snapshot()
        identifier, stored = next(iter(state['jobs'].items()))
        self.assertTrue(stored['claimed'])
        self.assertIsNone(self.b.poll(['gemma4:e4b']))
        self.b.deliver(self.packet({'id': identifier, **stored}))
        consumer.finish(self)
        self.assertFalse(consumer.errors)
        self.conflicts = 99
        before = len(self.commands)
        with self.assertRaises(ValueError):
            self.a.control('drain')
        self.assertEqual(self.commands[before:].count('EVAL'), relay._CONFLICTS)

    def test_07_response_loss_duplicate_delivery_and_unobserved_legacy(self):
        consumer = self.start(self.a)
        self.wait_jobs(1)
        job = self.b.poll(['gemma4:e4b'])
        payload = self.packet(job, text='legacy fragment', done=False, observed=False)
        self.lose_reply = True
        with self.assertRaisesRegex(ValueError, 'lost response'):
            self.b.deliver(payload)
        self.b.deliver(payload)
        self.assertEqual(self.a._snapshot()['jobs'][job['id']]['sequence'], 1)
        self.b.deliver(self.packet(job, 1, text='', observed=False))
        consumer.finish(self)
        self.assertEqual(''.join(consumer.chunks), 'legacy fragment')
        self.assertFalse(consumer.messages.provider_dispatched)
        self.assertFalse(consumer.messages.runtime_dispatch_observation['dispatched'])

    def test_08_deadline_input_limit_worker_error_and_no_transport_fallback(self):
        messages = Messages()
        messages.generation_deadline = time.monotonic() - 1
        with self.assertRaises(ValueError):
            next(self.a.stream(messages))
        before = len(self.commands)
        with self.assertRaises(ValueError):
            next(self.a.stream([{'role': 'user', 'content': 'x' * 42001}], contract='dialogue_plan.v2'))
        self.assertEqual(len(self.commands), before)
        short = relay.RedisGemmaRelay(self.env, timeout=.08)
        consumer = self.start(short)
        consumer.finish(self)
        self.assertEqual(len(consumer.errors), 1)
        self.assertEqual(self.a.control('status')['active_jobs'], 0)
        with patch.object(self.a, '_remove', side_effect=ValueError('synthetic cleanup unavailable')):
            failed = self.start(self.a)
            self.wait_jobs(1)
            job = self.b.poll(['gemma4:e4b'])
            self.b.deliver({**self.packet(job, text=''), 'error': True})
            failed.finish(self)
        self.assertEqual(len(failed.errors), 1)
        self.assertIn('PC의 Gemma 응답이 중단', str(failed.errors[0]))
        self.assertTrue(failed.messages.provider_dispatched)
        self.assertEqual(self.a.control('status')['active_jobs'], 1)
        self.b._remove(job['id'])
        with patch.object(self.a, '_remove', side_effect=ValueError('synthetic cleanup unavailable')):
            complete = self.start(self.a)
            self.wait_jobs(1)
            job = self.b.poll(['gemma4:e4b'])
            self.b.deliver(self.packet(job))
            complete.finish(self)
        self.assertFalse(complete.errors)
        self.assertEqual(''.join(complete.chunks), 'synthetic answer')
        self.assertEqual([kind for kind, _ in self.events].count('relay_cleanup_unconfirmed'), 2)
        self.b._remove(job['id'])
        safe_job = {'trace_id': 'synthetic-trace', 'model': 'gemma4:e4b', 'contract': None,
                    'worker_observation': {'error_kind': 'provider_error', 'failure_stage': 'generation'}}
        self.a._event(None, 'a' * 32, safe_job, 'relay_error', error_kind='worker_error', failure_stage='worker')
        self.assertEqual(self.events[-1][1]['error_kind'], 'worker_error')
        with patch.object(relay, '_relay_event', side_effect=RuntimeError('synthetic diagnostics unavailable')):
            self.a._event(None, 'a' * 32, safe_job, 'relay_error')
        with patch.object(relay.RedisStateStore, '_command', side_effect=ValueError('synthetic unavailable')) as command:
            with self.assertRaises(ValueError):
                self.a.control('status')
            self.assertEqual(command.call_count, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
