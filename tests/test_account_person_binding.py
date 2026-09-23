"""An invitation names the public person; enrollment binds the account; mail uses its email.

Members enroll themselves with Google, so the operator never maintains an
address list: the invitation carries the person id, the enrolled account keeps
it, and outgoing mail resolves the recipient from that account's verified email.
"""
import json
import tempfile
import unittest
from pathlib import Path

from rndplz.account_storage import AccountStorage, AuthError, email_for_person
from rndplz.mail_delivery import MailDelivery


def enroll(storage, invitation, sub, name, email, state='state-' + '1' * 20, cookie='cookie-1'):
    storage.add_flow(state, cookie, 'nonce', 'verifier', invitation=invitation)
    flow = storage.consume_flow(state, cookie)
    return storage.issue_session(sub, name, email, enrollment_flow=flow)


class PersonBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.db = root / 'accounts.sqlite3'
        self.storage = AccountStorage(self.db, root / 'files', clock=lambda: 1_000_000)

    def test_invitation_person_binds_the_enrolled_account(self):
        issued = self.storage.issue_invitation(600, person_id='LOCAL-JINHO')
        self.assertEqual(issued['person_id'], 'LOCAL-JINHO')
        self.assertEqual(self.storage.invitation_status(issued['invitation_id'])['person_id'], 'LOCAL-JINHO')
        session = enroll(self.storage, issued['invitation'], 'sub-jinho', '오진호', 'jinho@example.com')
        self.assertEqual(session['account']['person_id'], 'LOCAL-JINHO')
        self.assertEqual(email_for_person(self.db, 'LOCAL-JINHO'), 'jinho@example.com')
        self.assertEqual(email_for_person(self.db, 'LOCAL-DASOL'), '')
        listed = self.storage.list_accounts()
        self.assertEqual((listed[0]['person_id'], listed[0]['email']), ('LOCAL-JINHO', 'j***@example.com'))

    def test_a_person_can_be_bound_to_only_one_account(self):
        first = self.storage.issue_invitation(600, person_id='LOCAL-HONG')
        enroll(self.storage, first['invitation'], 'sub-hong', '홍윤기', 'hong@example.com')
        with self.assertRaises(AuthError) as caught:
            self.storage.issue_invitation(600, person_id='LOCAL-HONG')
        self.assertEqual(caught.exception.code, 'person_already_bound')

    def test_invitation_without_person_and_admin_binding(self):
        issued = self.storage.issue_invitation(600)
        self.assertIsNone(issued['person_id'])
        session = enroll(self.storage, issued['invitation'], 'sub-x', 'Someone', 'x@example.com')
        self.assertIsNone(session['account']['person_id'])
        self.assertEqual(email_for_person(self.db, 'LOCAL-DASOL'), '')
        bound = self.storage.bind_person(session['account']['id'], 'LOCAL-DASOL')
        self.assertEqual(bound['person_id'], 'LOCAL-DASOL')
        self.assertEqual(email_for_person(self.db, 'LOCAL-DASOL'), 'x@example.com')
        self.storage.bind_person(session['account']['id'], None)
        self.assertEqual(email_for_person(self.db, 'LOCAL-DASOL'), '')
        with self.assertRaises(AuthError):
            self.storage.issue_invitation(600, person_id='local-bad id')

    def test_revoked_account_is_not_a_recipient(self):
        issued = self.storage.issue_invitation(600, person_id='LOCAL-MANWOO')
        session = enroll(self.storage, issued['invitation'], 'sub-mw', 'Manwoo Son', 'mw@example.com')
        self.assertEqual(email_for_person(self.db, 'LOCAL-MANWOO'), 'mw@example.com')
        self.storage.revoke_account(session['account']['id'])
        self.assertEqual(email_for_person(self.db, 'LOCAL-MANWOO'), '')
        self.assertEqual(email_for_person(Path(self.tmp.name) / 'missing.sqlite3', 'LOCAL-MANWOO'), '')

    def test_mail_delivery_prefers_the_account_directory(self):
        issued = self.storage.issue_invitation(600, person_id='LOCAL-JINHO')
        enroll(self.storage, issued['invitation'], 'sub-jinho', '오진호', 'jinho@example.com')
        recipients = Path(self.tmp.name) / 'recipients.json'
        recipients.write_text(json.dumps({'LOCAL-JINHO': 'old@example.com', 'LOCAL-DASOL': 'dasol@example.com'}), encoding='utf-8')
        sent = []
        env = {'RNDPLZ_MAIL_USERNAME': 'sender@gmail.com', 'RNDPLZ_MAIL_PASSWORD': 'app',
               'RNDPLZ_ACCOUNT_DB_PATH': str(self.db), 'RNDPLZ_MAIL_RECIPIENTS_FILE': str(recipients)}
        mail = MailDelivery(env, transport=sent.append, clock=lambda: 0)
        self.assertTrue(mail.enabled)
        self.assertTrue(mail.status()['account_directory'])
        self.assertEqual(mail.address_for('LOCAL-JINHO'), 'jinho@example.com')   # account wins over the file
        self.assertEqual(mail.address_for('LOCAL-DASOL'), 'dasol@example.com')   # file fallback
        self.assertEqual(mail.address_for('LOCAL-HONG'), '')
        only_accounts = MailDelivery({k: v for k, v in env.items() if k != 'RNDPLZ_MAIL_RECIPIENTS_FILE'}, transport=sent.append)
        self.assertTrue(only_accounts.enabled)
        self.assertEqual(only_accounts.address_for('LOCAL-DASOL'), '')


if __name__ == '__main__':
    unittest.main()
