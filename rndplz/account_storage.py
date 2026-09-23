"""Private account/profile persistence candidate; no public corpus or chat migration."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time
import uuid


MOLE_RULE = 'profile_first_experience'
MOLE_POLICY_VERSION = 'v1'
MOLE_AMOUNT = 1
MOLE_LIMIT = 20


def mole_time(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def mole_entry(row):
    return {'id': row['id'], 'delta': row['delta'], 'kind': row['kind'],
            'activity': '첫 경험 프로필 등록' if row['kind'] == 'grant' else '적립 정정',
            'occurred_at': row['created_at'], 'event_id': row['event_id'],
            'reverses_id': row['reverses_id']}


class AuthError(ValueError):
    def __init__(self, code, status=403):
        self.code, self.status = code, status
        super().__init__('계정 인증 또는 저장 상태를 확인해 주세요.')


def digest(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        raise AuthError('invalid_opaque_value')
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


PERSON_ID = re.compile(r'[A-Z0-9][A-Z0-9-]{0,63}')


def person_id_value(value):
    """A public corpus person id such as LOCAL-JINHO, or None when absent."""
    if value is None:
        return None
    if not isinstance(value, str) or not PERSON_ID.fullmatch(value):
        raise AuthError('person_id_invalid', 400)
    return value


def account_view(row):
    keys = row.keys()
    return {'id': row['id'], 'verified': True, 'storage_lifetime': 'account_database',
            'display_name': row['display_name'], 'email': row['email'],
            'person_id': row['person_id'] if 'person_id' in keys else None}


def email_for_person(db_path, person_id):
    """Verified Google email of the account bound to a public person; '' when none.

    Read-only lookup for outgoing mail. Explicitly revoked subjects are skipped.
    """
    try:
        person_id = person_id_value(person_id)
    except AuthError:
        return ''
    path = Path(db_path) if db_path else None
    if not person_id or path is None or not path.is_file():
        return ''
    try:
        db = sqlite3.connect('file:' + path.as_posix() + '?mode=ro', uri=True, timeout=5)
    except sqlite3.Error:
        return ''
    try:
        db.row_factory = sqlite3.Row
        columns = {row['name'] for row in db.execute('PRAGMA table_info(accounts)')}
        if 'person_id' not in columns:
            return ''
        row = db.execute('SELECT a.email FROM accounts a LEFT JOIN subject_approvals s USING(google_sub) '
                         'WHERE a.person_id=? AND COALESCE(s.revoked,0)=0 AND a.email<>\'\' '
                         'ORDER BY a.created DESC LIMIT 1', (person_id,)).fetchone()
        return row['email'] if row is not None else ''
    except sqlite3.Error:
        return ''
    finally:
        db.close()


class AccountStorage:
    def __init__(self, db_path, files_root, *, clock=time.time, allowed_subs=()):
        self.path, self.files_root, self.clock = Path(db_path), Path(files_root), clock
        self.allowed_subs = frozenset(allowed_subs)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.files_root.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS accounts(
                    id TEXT PRIMARY KEY, google_sub TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL, email TEXT NOT NULL, created INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions(
                    token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
                    csrf TEXT NOT NULL, expires INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS login_flows(
                    state_hash TEXT PRIMARY KEY, cookie_hash TEXT NOT NULL,
                    nonce TEXT NOT NULL, verifier TEXT NOT NULL, expires INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS subject_approvals(
                    google_sub TEXT PRIMARY KEY, approved INTEGER NOT NULL DEFAULT 0,
                    revoked INTEGER NOT NULL DEFAULT 0, approved_at INTEGER);
                CREATE TABLE IF NOT EXISTS invitations(
                    id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL,
                    expires INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0,
                    bound_state_hash TEXT, consumed INTEGER NOT NULL DEFAULT 0,
                    enrolled_sub TEXT);
                CREATE TABLE IF NOT EXISTS enrollment_flows(
                    state_hash TEXT PRIMARY KEY REFERENCES login_flows(state_hash) ON DELETE CASCADE,
                    invitation_hash TEXT NOT NULL REFERENCES invitations(token_hash));
                CREATE TABLE IF NOT EXISTS profile_state(
                    account_id TEXT PRIMARY KEY REFERENCES accounts(id), payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS mole_ledger(
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES accounts(id),
                    rule_key TEXT NOT NULL, policy_version TEXT NOT NULL,
                    delta INTEGER NOT NULL CHECK(typeof(delta)='integer'),
                    kind TEXT NOT NULL CHECK(kind IN ('grant','reversal')),
                    created_at TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL,
                    profile_id TEXT, profile_version INTEGER, career_id TEXT,
                    request_id TEXT, event_id TEXT,
                    reverses_id TEXT UNIQUE REFERENCES mole_ledger(id),
                    CHECK((kind='grant' AND delta=1 AND reverses_id IS NULL) OR
                          (kind='reversal' AND delta=-1 AND reverses_id IS NOT NULL)));
                CREATE UNIQUE INDEX IF NOT EXISTS mole_once_per_account_rule
                    ON mole_ledger(account_id,rule_key) WHERE kind='grant';
                CREATE INDEX IF NOT EXISTS mole_account_history
                    ON mole_ledger(account_id,created_at DESC,id DESC);
                CREATE TRIGGER IF NOT EXISTS mole_no_update BEFORE UPDATE ON mole_ledger
                    BEGIN SELECT RAISE(ABORT,'mole_ledger_append_only'); END;
                CREATE TRIGGER IF NOT EXISTS mole_no_delete BEFORE DELETE ON mole_ledger
                    BEGIN SELECT RAISE(ABORT,'mole_ledger_append_only'); END;
            ''')

            # Optional binding of an invitation/account to one public corpus person.
            for table in ('invitations', 'accounts'):
                columns = {row['name'] for row in db.execute('PRAGMA table_info(' + table + ')')}
                if 'person_id' not in columns:
                    db.execute('ALTER TABLE ' + table + ' ADD COLUMN person_id TEXT')
            db.execute('CREATE UNIQUE INDEX IF NOT EXISTS accounts_person_once '
                       'ON accounts(person_id) WHERE person_id IS NOT NULL')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA synchronous=FULL')
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                yield db
                db.execute('COMMIT')
            except BaseException:
                db.execute('ROLLBACK')
                raise

    def _authorized(self, db, sub):
        row = db.execute('SELECT * FROM subject_approvals WHERE google_sub=?', (sub,)).fetchone()
        if row is not None and row['revoked']:
            raise AuthError('account_revoked', 401)
        if sub not in self.allowed_subs and not (row is not None and row['approved']):
            raise AuthError('team_member_not_allowed', 403)

    def issue_invitation(self, ttl_seconds=600, person_id=None):
        # Trusted local administrator only; HTTP must never expose this method.
        if type(ttl_seconds) is not int or not 60 <= ttl_seconds <= 3600:
            raise AuthError('invitation_ttl_invalid', 400)
        person_id = person_id_value(person_id)
        invitation, iid = secrets.token_urlsafe(32), uuid.uuid4().hex
        expires = int(self.clock()) + ttl_seconds
        with self.transaction() as db:
            if person_id is not None and db.execute(
                    'SELECT 1 FROM accounts WHERE person_id=?', (person_id,)).fetchone() is not None:
                raise AuthError('person_already_bound', 409)
            db.execute('INSERT INTO invitations(id,token_hash,expires,person_id) VALUES(?,?,?,?)',
                       (iid, digest(invitation), expires, person_id))
        return {'invitation_id': iid, 'invitation': invitation, 'expires_at': expires, 'person_id': person_id}

    def bind_person(self, account_id, person_id):
        """Administrator binding of an existing account to one public person (None unbinds)."""
        if not isinstance(account_id, str) or not re.fullmatch('[a-f0-9]{32}', account_id):
            raise AuthError('account_id_invalid', 400)
        person_id = person_id_value(person_id)
        with self.transaction() as db:
            if db.execute('SELECT 1 FROM accounts WHERE id=?', (account_id,)).fetchone() is None:
                raise AuthError('account_not_found', 404)
            if person_id is not None and db.execute(
                    'SELECT 1 FROM accounts WHERE person_id=? AND id<>?', (person_id, account_id)).fetchone() is not None:
                raise AuthError('person_already_bound', 409)
            db.execute('UPDATE accounts SET person_id=? WHERE id=?', (person_id, account_id))
        return {'account_id': account_id, 'person_id': person_id}

    def list_accounts(self):
        """Administrator listing with masked emails; never returns subs or sessions."""
        with self.connection() as db:
            rows = db.execute('SELECT a.id, a.display_name, a.email, a.person_id, a.created, '
                              'COALESCE(s.revoked,0) AS revoked FROM accounts a '
                              'LEFT JOIN subject_approvals s USING(google_sub) ORDER BY a.created').fetchall()
        def masked(email):
            local, _, domain = email.partition('@')
            return (local[:1] + '***@' + domain) if domain else ''
        return [{'account_id': row['id'], 'display_name': row['display_name'], 'email': masked(row['email']),
                 'person_id': row['person_id'], 'created': row['created'], 'revoked': bool(row['revoked'])}
                for row in rows]

    def has_active_approvals(self):
        with self.connection() as db:
            return db.execute('SELECT 1 FROM subject_approvals JOIN accounts USING(google_sub) '
                              'WHERE approved=1 AND revoked=0 LIMIT 1').fetchone() is not None

    def has_login_members(self):
        with self.connection() as db:
            revoked = {row['google_sub'] for row in db.execute(
                'SELECT google_sub FROM subject_approvals WHERE revoked=1')}
            return bool(self.allowed_subs - revoked) or db.execute(
                'SELECT 1 FROM subject_approvals JOIN accounts USING(google_sub) '
                'WHERE approved=1 AND revoked=0 LIMIT 1').fetchone() is not None

    def invitation_status(self, invitation_id):
        if not isinstance(invitation_id, str) or not re.fullmatch('[a-f0-9]{32}', invitation_id):
            raise AuthError('invitation_id_invalid', 400)
        with self.connection() as db:
            row = db.execute('SELECT * FROM invitations WHERE id=?', (invitation_id,)).fetchone()
            if row is None:
                raise AuthError('invitation_not_found', 404)
            status = ('revoked' if row['revoked'] else 'consumed' if row['consumed'] else
                      'expired' if row['expires'] <= self.clock() else
                      'bound' if row['bound_state_hash'] is not None else 'available')
            account = db.execute('SELECT id FROM accounts WHERE google_sub=?',
                                 (row['enrolled_sub'],)).fetchone() if row['consumed'] else None
            return {'invitation_id': row['id'], 'status': status, 'expires_at': row['expires'],
                    'account_id': account['id'] if account is not None else None,
                    'person_id': row['person_id']}

    def _invitation(self, db, token_hash, state_hash=None):
        row = db.execute('SELECT * FROM invitations WHERE token_hash=?', (token_hash,)).fetchone()
        if row is None or row['expires'] <= self.clock() or row['revoked'] or row['consumed']:
            raise AuthError('invitation_unavailable')
        if row['bound_state_hash'] != state_hash:
            raise AuthError('invitation_flow_mismatch')
        return row

    def revoke_invitation(self, invitation_id):
        if not isinstance(invitation_id, str) or not re.fullmatch('[a-f0-9]{32}', invitation_id):
            raise AuthError('invitation_id_invalid', 400)
        with self.transaction() as db:
            if db.execute('SELECT id FROM invitations WHERE id=?', (invitation_id,)).fetchone() is None:
                raise AuthError('invitation_not_found', 404)
            db.execute('UPDATE invitations SET revoked=1 WHERE id=?', (invitation_id,))
        return True  # Account revocation is separate for an already consumed invitation.

    def revoke_account(self, account_id):
        if not isinstance(account_id, str) or not re.fullmatch('[a-f0-9]{32}', account_id):
            raise AuthError('account_id_invalid', 400)
        with self.transaction() as db:
            row = db.execute('SELECT google_sub FROM accounts WHERE id=?', (account_id,)).fetchone()
            if row is None:
                raise AuthError('account_not_found', 404)
            db.execute('INSERT INTO subject_approvals(google_sub,revoked) VALUES(?,1) '
                       'ON CONFLICT(google_sub) DO UPDATE SET revoked=1', (row['google_sub'],))
            db.execute('UPDATE sessions SET revoked=1 WHERE account_id=?', (account_id,))
        return True

    def add_flow(self, state, cookie, nonce, verifier, *, invitation=None):
        sh = digest(state)
        with self.transaction() as db:
            db.execute('DELETE FROM login_flows WHERE expires<=?', (int(self.clock()),))
            if db.execute('SELECT count(*) FROM login_flows').fetchone()[0] >= 256:
                raise AuthError('login_busy', 429)
            ih = None
            if invitation is not None:
                if not isinstance(invitation, str) or not re.fullmatch('[A-Za-z0-9_-]{43}', invitation):
                    raise AuthError('invitation_invalid', 400)
                ih = digest(invitation)
                self._invitation(db, ih)  # A bound invitation can never start another flow.
                db.execute('UPDATE invitations SET bound_state_hash=? WHERE token_hash=?', (sh, ih))
            db.execute('INSERT INTO login_flows VALUES(?,?,?,?,?)',
                       (sh, digest(cookie), nonce, verifier, int(self.clock()) + 600))
            if ih is not None:
                db.execute('INSERT INTO enrollment_flows VALUES(?,?)', (sh, ih))

    def _consume_flow(self, db, state, cookie):
        sh = digest(state)
        row = db.execute('SELECT * FROM login_flows WHERE state_hash=?', (sh,)).fetchone()
        if row is None or row['expires'] <= self.clock() or not hmac.compare_digest(row['cookie_hash'], digest(cookie)):
            raise AuthError('login_state_or_cookie_invalid')
        invitation = db.execute('SELECT invitation_hash FROM enrollment_flows WHERE state_hash=?', (sh,)).fetchone()
        result = dict(row)
        result['invitation_hash'] = invitation['invitation_hash'] if invitation else None
        db.execute('DELETE FROM login_flows WHERE state_hash=?', (sh,))
        return result

    def consume_flow(self, state, cookie):
        with self.transaction() as db:
            return self._consume_flow(db, state, cookie)  # One-use even if provider verification fails.

    def cancel_flow(self, state, cookie):
        with self.transaction() as db:
            flow = self._consume_flow(db, state, cookie)
            if flow['invitation_hash'] is not None:
                db.execute('UPDATE invitations SET revoked=1 WHERE token_hash=? AND bound_state_hash=?',
                           (flow['invitation_hash'], flow['state_hash']))
        return True

    def _issue_session(self, db, sub, display_name, email, previous_cookie):
        self._authorized(db, sub)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        row = db.execute('SELECT * FROM accounts WHERE google_sub=?', (sub,)).fetchone()
        if row is None:
            aid = uuid.uuid4().hex
            db.execute('INSERT INTO accounts(id,google_sub,display_name,email,created) VALUES(?,?,?,?,?)',
                       (aid, sub, display_name, email, int(self.clock())))
        else:
            aid = row['id']
            db.execute('UPDATE accounts SET display_name=?,email=? WHERE id=?', (display_name, email, aid))
        if previous_cookie:
            db.execute('UPDATE sessions SET revoked=1 WHERE token_hash=?', (digest(previous_cookie),))
        db.execute('INSERT INTO sessions(token_hash,account_id,csrf,expires) VALUES(?,?,?,?)',
                   (digest(token), aid, csrf, int(self.clock()) + 86400))
        row = db.execute('SELECT * FROM accounts WHERE id=?', (aid,)).fetchone()
        return {'session_cookie': token, 'csrf': csrf, 'account': account_view(row)}

    def issue_session(self, sub, display_name, email, previous_cookie=None, *, enrollment_flow=None):
        # Called only after signed Google token/nonce/issuer/audience/time verification.
        with self.transaction() as db:
            person_id = None
            if enrollment_flow is not None and enrollment_flow.get('invitation_hash') is not None:
                ih, sh = enrollment_flow['invitation_hash'], enrollment_flow['state_hash']
                invitation = self._invitation(db, ih, sh)
                revoked = db.execute('SELECT revoked FROM subject_approvals WHERE google_sub=?', (sub,)).fetchone()
                if revoked is not None and revoked['revoked']:
                    raise AuthError('account_revoked', 401)
                person_id = invitation['person_id']
                if person_id is not None and db.execute(
                        'SELECT 1 FROM accounts WHERE person_id=? AND google_sub<>?', (person_id, sub)).fetchone() is not None:
                    raise AuthError('person_already_bound', 409)
                db.execute('UPDATE invitations SET consumed=1,enrolled_sub=? WHERE token_hash=?', (sub, ih))
                db.execute('INSERT INTO subject_approvals(google_sub,approved,approved_at) VALUES(?,1,?) '
                           'ON CONFLICT(google_sub) DO UPDATE SET approved=1,approved_at=excluded.approved_at',
                           (sub, int(self.clock())))
            issued = self._issue_session(db, sub, display_name, email, previous_cookie)
            if person_id is not None:
                # The invitation named the public person this account represents.
                db.execute('UPDATE accounts SET person_id=? WHERE google_sub=?', (person_id, sub))
                issued['account']['person_id'] = person_id
            return issued

    def principal(self, db, cookie, account_id=None):
        row = db.execute('''SELECT accounts.*,sessions.csrf FROM sessions JOIN accounts
            ON accounts.id=sessions.account_id WHERE token_hash=? AND revoked=0 AND expires>?''',
                         (digest(cookie), self.clock())).fetchone()
        if row is None or (account_id is not None and row['id'] != account_id):
            raise AuthError('session_expired_or_revoked', 401)
        self._authorized(db, row['google_sub'])
        return row

    def authenticate(self, cookie):
        if not cookie:
            return None
        try:
            with self.connection() as db:
                row = self.principal(db, cookie)
                return {'account': account_view(row), 'csrf': row['csrf']}
        except AuthError:
            return None

    def logout(self, cookie, csrf):
        with self.transaction() as db:
            row = self.principal(db, cookie)
            if not isinstance(csrf, str) or not hmac.compare_digest(row['csrf'], csrf):
                raise AuthError('csrf_mismatch')
            db.execute('UPDATE sessions SET revoked=1 WHERE token_hash=?', (digest(cookie),))
        return True

    def profile_store(self, account_id, session_cookie=None):
        return AccountStateStore(self, account_id, session_cookie=session_cookie)

    def reverse_mole_entry(self, grant_id, reason='incorrect_award'):
        """Trusted local operator only; never expose this method over HTTP."""
        if not isinstance(grant_id, str) or not re.fullmatch('[a-f0-9]{32}', grant_id):
            raise AuthError('mole_entry_id_invalid', 400)
        if reason != 'incorrect_award':
            raise AuthError('mole_reversal_reason_invalid', 400)
        with self.transaction() as db:
            grant = db.execute('SELECT * FROM mole_ledger WHERE id=? AND kind=?',
                               (grant_id, 'grant')).fetchone()
            if grant is None:
                raise AuthError('mole_grant_not_found', 404)
            existing = db.execute('SELECT * FROM mole_ledger WHERE reverses_id=?', (grant_id,)).fetchone()
            if existing is not None:
                return {'status': 'already_reversed', 'entry': mole_entry(existing)}
            identifier = uuid.uuid4().hex
            db.execute('''INSERT INTO mole_ledger
                (id,account_id,rule_key,policy_version,delta,kind,created_at,actor,reason,reverses_id)
                VALUES(?,?,?,?,?,?,?,?,?,?)''',
                (identifier, grant['account_id'], grant['rule_key'], grant['policy_version'],
                 -grant['delta'], 'reversal', mole_time(self.clock()), 'local_operator', reason, grant_id))
            row = db.execute('SELECT * FROM mole_ledger WHERE id=?', (identifier,)).fetchone()
            return {'status': 'reversed', 'entry': mole_entry(row)}


class AccountStateStore:
    """Profiles-compatible JSON adapter. All writes remain inside one account row.

    HTTP callers MUST pass session_cookie. Omitting it is reserved for trusted
    offline server maintenance; no request-supplied account ID is accepted upstream.
    directory is separate attachment storage, not evidence of deployment durability.
    """
    def __init__(self, storage, account_id, *, session_cookie=None):
        if not isinstance(account_id, str) or not re.fullmatch('[a-f0-9]{32}', account_id):
            raise AuthError('account_id_invalid')
        self.storage, self.account_id, self.session_cookie = storage, account_id, session_cookie
        self.directory = storage.files_root / account_id
        for part in (self.directory, *self.directory.parents):
            if part.exists() and (part.is_symlink() or getattr(part.stat(), 'st_file_attributes', 0) & 0x400):
                raise AuthError('linked_account_directory', 503)
        with storage.connection() as db:
            self._guard(db)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _guard(self, db):
        if self.session_cookie is not None:
            self.storage.principal(db, self.session_cookie, self.account_id)
        else:
            row = db.execute('SELECT google_sub FROM accounts WHERE id=?', (self.account_id,)).fetchone()
            if row is None:
                raise AuthError('account_not_found', 401)
            self.storage._authorized(db, row['google_sub'])

    def _read(self, db):
        state = {'version': 1, 'sessions': [], 'proposals': [], 'idempotency': {}}
        row = db.execute('SELECT payload FROM profile_state WHERE account_id=?', (self.account_id,)).fetchone()
        if row is not None:
            state['self_profile'] = json.loads(row['payload'])
        return state

    def read(self):
        with self.storage.connection() as db:
            self._guard(db)
            return self._read(db)

    def mole_summary(self):
        # A trusted offline/import store is not an authenticated balance viewer.
        if self.session_cookie is None:
            raise AuthError('mole_account_session_required', 401)
        with self.storage.connection() as db:
            db.execute('BEGIN')
            try:
                self._guard(db)
                balance = db.execute('SELECT COALESCE(SUM(delta),0) FROM mole_ledger WHERE account_id=?',
                                     (self.account_id,)).fetchone()[0]
                if type(balance) is not int or not 0 <= balance <= 9007199254740991:
                    raise AuthError('mole_ledger_invalid', 503)
                rows = db.execute('SELECT * FROM mole_ledger WHERE account_id=? '
                                  'ORDER BY created_at DESC,id DESC LIMIT ?',
                                  (self.account_id, MOLE_LIMIT + 1)).fetchall()
                result = {'account_id': self.account_id, 'unit': 'mole', 'balance': balance,
                          'as_of': mole_time(self.storage.clock()),
                          'entries': [mole_entry(row) for row in rows[:MOLE_LIMIT]],
                          'has_more': len(rows) > MOLE_LIMIT, 'limit': MOLE_LIMIT,
                          'policy': {'first_experience_amount': MOLE_AMOUNT,
                                     'once_per_account': True, 'non_cash': True}}
                db.execute('COMMIT')
                return result
            except BaseException:
                db.execute('ROLLBACK')
                raise

    def _award_first_experience(self, db, before, state, result):
        # The callback is the existing server-side Profiles.save. No client award
        # fields enter this adapter, and imports without a session never qualify.
        if self.session_cookie is None or not isinstance(result, dict):
            return
        operation = result.get('operation', {})
        if not isinstance(operation, dict) or operation.get('action') != 'save' or operation.get('replayed') is not False:
            return
        after = state.get('self_profile', {})
        profile = after.get('profile', {})
        prior_profile = before.get('profile', {})
        version = profile.get('version')
        request_id = operation.get('request_id')
        event_ids = operation.get('event_ids')
        if (type(version) is not int or version != prior_profile.get('version', 0) + 1 or
                operation.get('version') != version or not isinstance(request_id, str) or
                request_id in before.get('requests', {}) or not isinstance(event_ids, list) or not event_ids):
            return
        request = after.get('requests', {}).get(request_id, {})
        if request.get('action') != 'save' or request.get('version') != version or request.get('event_ids') != event_ids:
            return
        previous_ids = {event.get('id') for event in before.get('history', [])}
        careers = {row['id']: row for row in profile.get('careers', [])}
        for event in after.get('history', []):
            if (event.get('id') not in event_ids or event.get('id') in previous_ids or
                    event.get('version') != version or event.get('actor') != self.account_id or
                    event.get('action') not in ('edit', 'adopt')):
                continue
            field = event.get('field', '')
            if not isinstance(field, str) or not field.startswith('career:'):
                continue
            career_id = field[7:]
            career = careers.get(career_id)
            provenance = profile.get('provenance', {}).get(field, {})
            if (not isinstance(career, dict) or event.get('after') != career or event.get('before') == career or
                    any(not isinstance(career.get(key), str) or not career[key].strip() for key in ('role', 'description')) or
                    provenance.get('reviewer') != self.account_id or
                    provenance.get('review') not in ('accepted', 'edited_accepted')):
                continue
            db.execute('''INSERT INTO mole_ledger
                (id,account_id,rule_key,policy_version,delta,kind,created_at,actor,reason,
                 profile_id,profile_version,career_id,request_id,event_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(account_id,rule_key) WHERE kind='grant' DO NOTHING''',
                (uuid.uuid4().hex, self.account_id, MOLE_RULE, MOLE_POLICY_VERSION, MOLE_AMOUNT,
                 'grant', mole_time(self.storage.clock()), self.account_id, 'first_experience',
                 profile.get('id'), version, career_id, request_id, event['id']))
            return

    def transaction(self, fn):
        with self.storage.transaction() as db:
            self._guard(db)
            state = self._read(db)
            # Preserve the pre-write evidence before the callback mutates it.
            before = json.loads(json.dumps(state.get('self_profile', {})))
            result = fn(state)
            if set(state) - {'version', 'sessions', 'proposals', 'idempotency', 'self_profile'} or state.get('version') != 1 or state.get('sessions') != [] or state.get('proposals') != [] or state.get('idempotency') != {}:
                raise AuthError('profile_only_storage_boundary', 400)
            if 'self_profile' in state:
                raw = json.dumps(state['self_profile'], ensure_ascii=False, allow_nan=False, separators=(',', ':'))
                if len(raw.encode('utf-8')) > 8 * 1024 * 1024:
                    raise AuthError('profile_state_too_large', 413)
                db.execute('INSERT INTO profile_state VALUES(?,?) ON CONFLICT(account_id) DO UPDATE SET payload=excluded.payload',
                           (self.account_id, raw))
            self._award_first_experience(db, before, state, result)
            # Logout and writes serialize through BEGIN IMMEDIATE on the same DB.
            return result
