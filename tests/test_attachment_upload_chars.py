"""A chunked (large-file) upload publishes an attachment whose extracted text uses the full MAX_TEXT.

Reported 2026-10-04: after MAX_TEXT grew from 16,000 to 40,000 characters, a 5.9 MB PDF sent from
the phone failed at the end of its chunked upload with "전송한 파일의 크기나 지문이 일치하지 않습니다",
because the publication check still capped `characters` at the old 16,000.
"""
import base64
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rndplz.attachment_uploads import AttachmentUploads, CHUNK_BYTES, _public_result, AttachmentUploadError
from rndplz.attachments import MAX_TEXT


class UploadCharactersTests(unittest.TestCase):
    def test_publication_admits_the_full_extraction_limit(self):
        meta = {'size': 100}
        value = {'id': 'a' * 32, 'name': 'long.txt', 'size': 100, 'truncated': True, 'kind': 'document', 'characters': MAX_TEXT}
        self.assertIs(_public_result(value, meta), value)
        with self.assertRaises(AttachmentUploadError):
            _public_result({**value, 'characters': MAX_TEXT + 1}, meta)

    def test_a_chunked_text_longer_than_the_old_cap_completes(self):
        from rndplz.attachments import Attachments
        from rndplz.storage import StateStore
        directory = tempfile.TemporaryDirectory(prefix='rndplz-upload-')
        self.addCleanup(directory.cleanup)
        store = StateStore(Path(directory.name), env={})
        attachments = Attachments(Path(directory.name))  # keeps its files under <store>/attachments
        uploads = AttachmentUploads(store, attachments)
        raw = ('가나다라 ' * 7000).encode('utf-8')  # 35,000 characters, two chunks
        begin = uploads.begin({'name': 'report.txt', 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
        for index in range(begin['chunk_count']):
            piece = raw[index * CHUNK_BYTES:(index + 1) * CHUNK_BYTES]
            uploads.chunk({'upload_id': begin['upload_id'], 'index': index, 'data': base64.b64encode(piece).decode('ascii')})
        result = uploads.complete({'upload_id': begin['upload_id']})
        self.assertEqual((result['size'], result['kind']), (len(raw), 'document'))
        self.assertGreater(result['characters'], 16000)
        self.assertLessEqual(result['characters'], MAX_TEXT)


if __name__ == '__main__':
    unittest.main()
