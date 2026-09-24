import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from rndplz import diagnostics
from rndplz.diagnostics import Diagnostics


class Clock:
    def __init__(self):
        self.now = 1_790_000_000.0

    def __call__(self):
        return self.now


class DiagnosticsPruneThrottleTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.prunes = []
        original = Diagnostics._prune

        def counting(instance, **kwargs):
            self.prunes.append(kwargs)
            return original(instance, **kwargs)

        patcher = patch.object(Diagnostics, '_prune', counting)
        patcher.start()
        self.addCleanup(patcher.stop)

    def store(self, **limits):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        return directory, Diagnostics(directory, clock=self.clock, limits=limits or None)

    def test_retention_prune_runs_once_per_interval(self):
        _, diag = self.store()
        for _ in range(40):
            self.assertTrue(diag.record({'event_type': 'request_received'}))
            self.clock.now += 1
        self.assertEqual(len(self.prunes), 1)
        self.clock.now += diagnostics._PRUNE_INTERVAL_SECONDS
        self.assertTrue(diag.record({'event_type': 'request_received'}))
        self.assertEqual(len(self.prunes), 2)

    def test_expired_events_are_still_removed(self):
        directory, diag = self.store()
        self.assertTrue(diag.record({'event_type': 'request_received', 'event_id': 'a' * 32}))
        self.clock.now += 8 * 86400
        self.assertTrue(diag.record({'event_type': 'request_received', 'event_id': 'b' * 32}))
        with open(os.path.join(directory, 'events-active.jsonl'), encoding='utf-8') as handle:
            stored = handle.read()
        self.assertNotIn('a' * 32, stored)
        self.assertIn('b' * 32, stored)

    def test_size_cap_still_prunes_immediately(self):
        directory, diag = self.store(max_total_event_bytes=2048)
        for _ in range(30):
            self.assertTrue(diag.record({'event_type': 'request_received'}))
            self.clock.now += 1
        self.assertGreater(len(self.prunes), 1)
        self.assertLessEqual(os.path.getsize(os.path.join(directory, 'events-active.jsonl')), 2048)
        self.assertEqual(diag.health()['write_errors'], 0)


if __name__ == '__main__':
    unittest.main()
