"""Optional SMTP delivery of saved proposals.

Unit tests inject a fake transport; the service test writes a visitor state
with one proposable candidate and saves a "sent" proposal through the actual
Service so the delivery record lands on the stored proposal.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rndplz.domain import Contribution, Person, Record
from rndplz.engine import Engine
from rndplz.mail_delivery import MailDelivery, mask
from rndplz.models import ExternalModel
from rndplz.service import Service


def env_for(tmp, **extra):
    recipients = Path(tmp) / 'recipients.json'
    recipients.write_text(json.dumps({'P-MW': 'manwoo@example.com', 'P-BAD': 'not-an-address'}), encoding='utf-8')
    return {'RNDPLZ_MAIL_USERNAME': 'sender@gmail.com', 'RNDPLZ_MAIL_PASSWORD': 'app-password',
            'RNDPLZ_MAIL_RECIPIENTS_FILE': str(recipients), 'RNDPLZ_PUBLIC_ORIGIN': 'https://example.test:8443', **extra}


class FakeTransport:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def __call__(self, message):
        if self.fail:
            raise ConnectionRefusedError('smtp down')
        self.sent.append(message)


def proposal(pid='P-MW', body='손만우님께,\n\n[목적]\n증류 자문'):
    return {'id': 'p1', 'recipient_id': pid, 'recipient_name': 'Manwoo Son', 'request_kind': 'advice', 'body': body}


class MailDeliveryUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_disabled_without_credentials_or_recipients_file(self):
        self.assertFalse(MailDelivery({}).enabled)
        self.assertEqual(MailDelivery({}).send(proposal())['status'], 'not_configured')
        partial = env_for(self.tmp.name)
        partial.pop('RNDPLZ_MAIL_PASSWORD')
        self.assertFalse(MailDelivery(partial).enabled)
        self.assertEqual(MailDelivery(env_for(self.tmp.name)).status(), {'enabled': True, 'recipients_file_present': True})

    def test_sends_to_the_registered_address_with_copy_and_footer(self):
        transport = FakeTransport()
        mail = MailDelivery(env_for(self.tmp.name, RNDPLZ_MAIL_COPY_TO='me@gmail.com'), transport=transport, clock=lambda: 0)
        result = mail.send(proposal())
        self.assertEqual(result['status'], 'sent')
        self.assertEqual(result['to'], 'm***@example.com')
        self.assertEqual(result['copy_to'], 'm***@gmail.com')
        self.assertEqual(result['at'], '1970-01-01T00:00:00+00:00')
        message = transport.sent[0]
        self.assertEqual(message['To'], 'manwoo@example.com')
        self.assertEqual(message['Cc'], 'me@gmail.com')
        self.assertEqual(message['From'], 'sender@gmail.com')
        self.assertEqual(message['Subject'], '[수소문] Manwoo Son님께 드리는 자문 요청')
        content = message.get_content()
        self.assertIn('[목적]', content)
        self.assertIn('https://example.test:8443', content)
        self.assertNotIn('app-password', content)

    def test_skips_unknown_or_invalid_addresses_and_records_failures(self):
        transport = FakeTransport()
        mail = MailDelivery(env_for(self.tmp.name), transport=transport)
        self.assertEqual(mail.send(proposal('P-NONE'))['status'], 'skipped_no_address')
        self.assertEqual(mail.send(proposal('P-BAD'))['status'], 'skipped_no_address')
        self.assertEqual(transport.sent, [])
        failing = MailDelivery(env_for(self.tmp.name), transport=FakeTransport(fail=True))
        result = failing.send(proposal())
        self.assertEqual((result['status'], result['error_kind']), ('failed', 'ConnectionRefusedError'))
        self.assertEqual(mail.send(proposal(body=''))['status'], 'failed')

    def test_mask_never_reveals_the_local_part(self):
        self.assertEqual(mask('manwoo@example.com'), 'm***@example.com')
        self.assertEqual(mask('broken'), '***')


def record(rid, pid, title, text):
    return Record(id=rid, kind='career_record', title=title, text=text, date='2020',
                  people=[Contribution(person_id=pid, name='Manwoo Son', role='recorded_role')], tags=[],
                  field='process_engineering', scope='self_reported', source_system='user_provided_resume',
                  source_id=rid, source_url='', checked_at='2026-09-23', evidence_kind='career_experience')


class SaveProposalDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        people = {'P-MW': Person(id='P-MW', name='Manwoo Son', org='GS')}
        records = {'R-MONO': record('R-MONO', 'P-MW', '모노머 공정 증류 실험', '증류 및 추출 실험 수행.')}
        corpus = SimpleNamespace(people=people, records=records, by_person={'P-MW': list(records.values())},
                                 topics=[], topic_by_id={}, questions=[], errors=[])
        state_dir = Path(self.tmp.name) / 'state'
        state_dir.mkdir()
        evidence = [{'id': 'R-MONO', 'title': '모노머 공정 증류 실험', 'date': '2020', 'virtual': False}]
        session = {'id': 's1', 'kind': 'chat', 'created': 't', 'updated': 't', 'original': '증류 전문가를 찾고 있어',
                   'turns': 1, 'mode': 'advice', 'asker': 'lab', 'messages': [], 'ready': True, 'can_propose': True,
                   'slots': {'target': '', 'conditions': '', 'resources': '', 'deadline': '', 'goal': '증류 자문'},
                   'proposal_context': '원료 내 이취 물질 제거',
                   'result': {'topic_ids': [], 'claims': [], 'candidates': [
                       {'id': 'P-MW', 'name': 'Manwoo Son', 'virtual': False, 'lookup_only': False,
                        'proposal_allowed': True, 'evidence': evidence}]}}
        (state_dir / 'state.json').write_text(json.dumps(
            {'version': 1, 'sessions': [session], 'proposals': [], 'idempotency': {}}, ensure_ascii=False), encoding='utf-8')
        self.transport = FakeTransport()
        self.service = Service(Engine(corpus), state_dir,
                               ExternalModel({'RNDPLZ_PROVIDER': 'none', 'RNDPLZ_MODEL_CALL_LIMIT': '0'}),
                               state_env={**env_for(self.tmp.name), 'RNDPLZ_STATE_BACKEND': 'file'})
        self.service.mail = MailDelivery(env_for(self.tmp.name), transport=self.transport, clock=lambda: 0)

    def payload(self, state='sent', key='k1'):
        return {'session_id': 's1', 'candidate_ids': ['P-MW'], 'state': state, 'idempotency_key': key, 'bodies': {}}

    def test_sent_proposal_is_mailed_once_and_annotated(self):
        created = self.service.save_proposal(self.payload())
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]['delivery']['status'], 'sent')
        self.assertEqual(created[0]['delivery']['to'], 'm***@example.com')
        self.assertEqual(len(self.transport.sent), 1)
        stored = self.service.store.read()['proposals'][0]
        self.assertEqual(stored['delivery']['status'], 'sent')
        replay = self.service.save_proposal(self.payload())
        self.assertEqual([p['id'] for p in replay], [created[0]['id']])
        self.assertEqual(len(self.transport.sent), 1)

    def test_draft_is_not_mailed_and_a_failure_keeps_the_proposal(self):
        self.service.save_proposal(self.payload(state='draft', key='k-draft'))
        self.assertEqual(self.transport.sent, [])
        self.assertNotIn('delivery', self.service.store.read()['proposals'][0])
        self.service.mail = MailDelivery(env_for(self.tmp.name), transport=FakeTransport(fail=True))
        created = self.service.save_proposal(self.payload(key='k-fail'))
        self.assertEqual(created[0]['delivery']['status'], 'failed')
        self.assertEqual(len(self.service.store.read()['proposals']), 2)

    def test_not_configured_leaves_proposals_unannotated(self):
        self.service.mail = MailDelivery({})
        created = self.service.save_proposal(self.payload(key='k-off'))
        self.assertNotIn('delivery', created[0])


if __name__ == '__main__':
    unittest.main()
