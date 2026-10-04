"""Duplicate deliveries in a chunked upload are acknowledged, not refused as conflicts.

Reported 2026-10-04 from the phone: a 5.9 MB PDF ended with "이미 처리 중이거나 처리한 파일 전송입니다"
although the browser sends every piece once; a resent request (lost answer on a mobile network or
through the proxy) hit the server as a second delivery of the same piece.
"""
import base64
import hashlib
import tempfile
import threading
import unittest
from pathlib import Path

from rndplz import attachment_uploads
from rndplz.attachment_uploads import AttachmentUploads, CHUNK_BYTES, AttachmentUploadError
from rndplz.attachments import Attachments
from rndplz.storage import StateStore


class DuplicateDeliveryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='rndplz-dup-')
        self.addCleanup(directory.cleanup)
        store = StateStore(Path(directory.name), env={})
        self.uploads = AttachmentUploads(store, Attachments(Path(directory.name)))
        self.raw = ('가나다 ' * 200000).encode('utf-8')[:CHUNK_BYTES * 2 + 1000]
        self.begin = self.uploads.begin({'name': 'report.txt', 'size': len(self.raw), 'sha256': hashlib.sha256(self.raw).hexdigest()})

    def piece(self, index):
        return {'upload_id': self.begin['upload_id'], 'index': index,
                'data': base64.b64encode(self.raw[index * CHUNK_BYTES:(index + 1) * CHUNK_BYTES]).decode('ascii')}

    def test_a_piece_delivered_twice_is_acknowledged_once_stored(self):
        first = self.uploads.chunk(self.piece(0))
        again = self.uploads.chunk(self.piece(0))
        self.assertEqual(first, again)
        with self.assertRaises(AttachmentUploadError):  # a different piece out of order is still refused
            self.uploads.chunk(self.piece(2))
        for index in (1, 2):
            self.uploads.chunk(self.piece(index))
        result = self.uploads.complete({'upload_id': self.begin['upload_id']})
        self.assertEqual(result['size'], len(self.raw))

    def test_a_second_completion_waits_for_the_first(self):
        for index in range(3):
            self.uploads.chunk(self.piece(index))
        results, errors = [], []

        def finish():
            try:
                results.append(self.uploads.complete({'upload_id': self.begin['upload_id']}))
            except Exception as exc:  # noqa: BLE001 - recorded for the assertion
                errors.append(exc)
        threads = [threading.Thread(target=finish) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(30)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['id'], results[1]['id'])


if __name__ == '__main__':
    unittest.main()
