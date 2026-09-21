"""Private account/profile persistence candidate; no public corpus or chat migration."""
from contextlib import contextmanager
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time
import uuid


class AuthError(ValueError):
    def __init__(self, code, status=403):
        self.code, self.status = code, status
        super().__init__('계정 인증 또는 저장 상태를 확인해 주세요.')


def digest(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        raise AuthError('invalid_opaque_value')
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def account_view(row):
    return {'id': row['id'], 'verified': True, 'storage_lifetime': 'account_database',
            'display_name': row['display_name'], 'email': row['email']}


class AccountStorage:
    def __init__(self, db_path, files_root, *, clock=time.time):
        self.path, self.files_root, self.clock = Path(db_path), Path(files_root), clock
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
                CREATE TABLE IF NOT EXISTS profile_state(
                    account_id TEXT PRIMARY KEY REFERENCES accounts(id), payload TEXT NOT NULL);
            ''')

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

    def add_flow(self, state, cookie, nonce, verifier):
        with self.transaction() as db:
            db.execute('DELETE FROM login_flows WHERE expires<=?', (int(self.clock()),))
            if db.execute('SELECT count(*) FROM login_flows').fetchone()[0] >= 256:
                raise AuthError('login_busy', 429)
            db.execute('INSERT INTO login_flows VALUES(?,?,?,?,?)',
                       (digest(state), digest(cookie), nonce, verifier, int(self.clock()) + 600))

    def consume_flow(self, state, cookie):
        with self.transaction() as db:
            row = db.execute('SELECT * FROM login_flows WHERE state_hash=?', (digest(state),)).fetchone()
            if row is None or row['expires'] <= self.clock() or not hmac.compare_digest(row['cookie_hash'], digest(cookie)):
                raise AuthError('login_state_or_cookie_invalid')
            db.execute('DELETE FROM login_flows WHERE state_hash=?', (digest(state),))
            return dict(row)  # One-use even if later provider exchange/verification fails.

    def issue_session(self, sub, display_name, email, previous_cookie=None):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.transaction() as db:
            row = db.execute('SELECT * FROM accounts WHERE google_sub=?', (sub,)).fetchone()
            if row is None:
                aid = uuid.uuid4().hex
                db.execute('INSERT INTO accounts VALUES(?,?,?,?,?)',
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

    def principal(self, db, cookie, account_id=None):
        row = db.execute('''SELECT accounts.*,sessions.csrf FROM sessions JOIN accounts
            ON accounts.id=sessions.account_id WHERE token_hash=? AND revoked=0 AND expires>?''',
                         (digest(cookie), self.clock())).fetchone()
        if row is None or (account_id is not None and row['id'] != account_id):
            raise AuthError('session_expired_or_revoked', 401)
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
        elif db.execute('SELECT id FROM accounts WHERE id=?', (self.account_id,)).fetchone() is None:
            raise AuthError('account_not_found', 401)

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

    def transaction(self, fn):
        with self.storage.transaction() as db:
            self._guard(db)
            state = self._read(db)
            result = fn(state)
            if set(state) - {'version', 'sessions', 'proposals', 'idempotency', 'self_profile'} or state.get('version') != 1 or state.get('sessions') != [] or state.get('proposals') != [] or state.get('idempotency') != {}:
                raise AuthError('profile_only_storage_boundary', 400)
            if 'self_profile' in state:
                raw = json.dumps(state['self_profile'], ensure_ascii=False, allow_nan=False, separators=(',', ':'))
                if len(raw.encode('utf-8')) > 8 * 1024 * 1024:
                    raise AuthError('profile_state_too_large', 413)
                db.execute('INSERT INTO profile_state VALUES(?,?) ON CONFLICT(account_id) DO UPDATE SET payload=excluded.payload',
                           (self.account_id, raw))
            # Logout and writes serialize through BEGIN IMMEDIATE on the same DB.
            return result
