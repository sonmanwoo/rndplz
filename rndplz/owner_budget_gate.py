"""Offline owner ledger. No provider client, key loader, or network operations."""
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from hashlib import sha256
from pathlib import Path
import argparse
import json
import re
import sqlite3
import uuid

LIMIT_MICRO_USD = 30_000_000
SCALE = Decimal(1_000_000)
COVERAGE = 'all_openai_usage_in_user_30_usd_scope'


class Blocked(Exception):
    pass


def require(condition, code):
    if not condition:
        raise Blocked(code)


def decimal(value):
    require(isinstance(value, str), 'money_must_be_decimal_string')
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise Blocked('invalid_money') from None
    require(number.is_finite() and 0 <= number <= Decimal('1000000000000') and len(value) <= 40, 'invalid_money')
    return number


def micros(value):
    return int((decimal(value) * SCALE).to_integral_value(rounding=ROUND_CEILING))


def valid_hash(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def instant(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        raise Blocked('invalid_timestamp') from None
    require(result.tzinfo is not None, 'timezone_required')
    return result


def evidence(path, expected):
    require(valid_hash(expected), 'evidence_sha_required')
    raw = Path(path).read_bytes()
    require(len(raw) <= 65536 and sha256(raw).hexdigest() == expected, 'evidence_pin_mismatch')
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise Blocked('invalid_evidence_json') from None
    require(isinstance(value, dict) and value.get('verified') is True, 'evidence_unverified')
    return value


@contextmanager
def transaction(path):
    # mode=rw prevents a wrong path from silently creating a replacement ledger.
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=rw', uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('BEGIN IMMEDIATE')
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize(path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation; there is intentionally no reset or limit edit operation.
    with target.open('xb'):
        pass
    connection = sqlite3.connect(target)
    try:
        connection.executescript('''
          PRAGMA journal_mode=DELETE;
          PRAGMA synchronous=FULL;
          CREATE TABLE budget(id INTEGER PRIMARY KEY CHECK(id=1),
            limit_micro INTEGER NOT NULL CHECK(limit_micro=30000000),
            baseline_micro INTEGER, baseline_evidence TEXT,
            state TEXT NOT NULL CHECK(state IN ('UNKNOWN','READY','FROZEN')));
          INSERT INTO budget VALUES(1,30000000,NULL,NULL,'UNKNOWN');
          CREATE TABLE reservations(id TEXT PRIMARY KEY, operation_id TEXT UNIQUE NOT NULL,
            request_sha256 TEXT, maximum_micro INTEGER NOT NULL CHECK(maximum_micro>=0),
            actual_micro INTEGER, state TEXT NOT NULL,
            price_evidence TEXT, valid_until TEXT, settlement_evidence TEXT);
        ''')
        connection.commit()
    finally:
        connection.close()
    return status(path)


def totals(db):
    budget = db.execute('SELECT * FROM budget WHERE id=1').fetchone()
    require(budget is not None and budget['limit_micro'] == LIMIT_MICRO_USD, 'ledger_invalid')
    amounts = db.execute('SELECT COALESCE(SUM(COALESCE(actual_micro,maximum_micro)),0) FROM reservations').fetchone()[0]
    committed = None if budget['baseline_micro'] is None else budget['baseline_micro'] + amounts
    return {'state': budget['state'], 'limit_micro_usd': LIMIT_MICRO_USD,
            'committed_micro_usd': committed,
            'remaining_micro_usd': None if committed is None else max(0, LIMIT_MICRO_USD - committed),
            'unresolved_reservations': None if committed is None else db.execute('SELECT COUNT(*) FROM reservations WHERE actual_micro IS NULL').fetchone()[0],
            'initial_spend_known': budget['baseline_micro'] is not None}


def status(path):
    with transaction(path) as db:
        return totals(db)


def confirm_baseline(path, proof_path, proof_sha):
    proof = evidence(proof_path, proof_sha)
    require(proof.get('kind') == 'initial_usage_reconciliation' and proof.get('coverage') == COVERAGE,
            'baseline_scope_mismatch')
    require(proof.get('all_sessions_tests_retries_included') is True
            and proof.get('all_outstanding_accounted_for') is True
            and proof.get('all_future_writers_use_this_ledger') is True, 'usage_coverage_unknown')
    require(isinstance(proof.get('unresolved_reservations'), list), 'unresolved_usage_unknown')
    instant(proof.get('as_of_utc'))
    spent = micros(proof.get('spent_usd'))
    outstanding = []
    for item in proof['unresolved_reservations']:
        require(isinstance(item, dict) and isinstance(item.get('id'), str) and 1 <= len(item['id']) <= 120,
                'invalid_outstanding_reservation')
        outstanding.append((item['id'], micros(item.get('maximum_cost_usd'))))
    require(len({item[0] for item in outstanding}) == len(outstanding), 'duplicate_outstanding_reservation')
    with transaction(path) as db:
        before = totals(db)
        require(before['state'] == 'UNKNOWN' and not before['initial_spend_known'], 'baseline_already_bound')
        db.execute('UPDATE budget SET baseline_micro=?,baseline_evidence=?,state=? WHERE id=1',
                   (spent, proof_sha, 'FROZEN' if spent + sum(v for _, v in outstanding) > LIMIT_MICRO_USD else 'READY'))
        for original_id, amount in outstanding:
            db.execute('INSERT INTO reservations VALUES(?,?,?,?,?,?,?,?,?)',
                       ('external:' + original_id, 'external:' + original_id, None, amount, None,
                        'UNCERTAIN', None, None, None))
        return totals(db)


def reserve(path, *, operation_id, request_sha256, model, endpoint,
            input_token_upper_bound, output_token_cap, proof_path, proof_sha, now=None):
    require(isinstance(operation_id, str) and 1 <= len(operation_id) <= 160, 'invalid_operation_id')
    require(valid_hash(request_sha256), 'request_sha_required')
    for count in (input_token_upper_bound, output_token_cap):
        require(type(count) is int and 0 <= count <= 1_000_000_000, 'token_bound_required')
    require(output_token_cap > 0, 'output_cap_required')
    proof = evidence(proof_path, proof_sha)
    require(proof.get('kind') == 'text_price_and_bound_verification'
            and proof.get('model') == model and proof.get('endpoint') == endpoint, 'price_scope_mismatch')
    require(proof.get('currency') == 'USD' and proof.get('all_other_charges_excluded') is True
            and proof.get('uncached_input_upper_rate') is True
            and proof.get('output_includes_reasoning') is True
            and proof.get('request_sha256') == request_sha256
            and proof.get('input_token_upper_bound') == input_token_upper_bound
            and proof.get('output_token_cap') == output_token_cap, 'cost_bound_unverified')
    require(isinstance(proof.get('official_pricing_source'), str)
            and proof['official_pricing_source'].startswith(('https://openai.com/', 'https://developers.openai.com/', 'https://platform.openai.com/')),
            'official_price_reference_required')
    at = datetime.now(timezone.utc) if now is None else now
    require(instant(proof.get('verified_at_utc')) <= at < instant(proof.get('valid_until_utc')), 'price_evidence_expired')
    input_rate = decimal(proof.get('input_usd_per_million'))
    output_rate = decimal(proof.get('output_usd_per_million'))
    require(input_rate > 0 and output_rate > 0, 'nonzero_verified_rates_required')
    # USD/million tokens times count is micro-USD; always round the total up.
    maximum = int((input_rate * input_token_upper_bound + output_rate * output_token_cap).to_integral_value(rounding=ROUND_CEILING))
    reservation_id = uuid.uuid4().hex
    with transaction(path) as db:
        state = totals(db)
        require(state['state'] == 'READY', 'initial_usage_unknown_or_ledger_frozen')
        require(db.execute('SELECT 1 FROM reservations WHERE operation_id=?', (operation_id,)).fetchone() is None,
                'operation_already_reserved_retry_needs_new_reservation')
        require(maximum <= state['remaining_micro_usd'], 'budget_exhausted')
        db.execute('INSERT INTO reservations VALUES(?,?,?,?,?,?,?,?,?)',
                   (reservation_id, operation_id, request_sha256, maximum, None, 'RESERVED', proof_sha,
                    proof['valid_until_utc'], None))
    return {'reservation_id': reservation_id, 'maximum_micro_usd': maximum,
            'request_sha256': request_sha256, 'network_performed': False}


def begin_dispatch(path, reservation_id, request_sha256, now=None):
    # Must be called immediately before exactly one transport attempt, including retries.
    at = datetime.now(timezone.utc) if now is None else now
    with transaction(path) as db:
        require(totals(db)['state'] == 'READY', 'ledger_not_ready')
        row = db.execute('SELECT * FROM reservations WHERE id=?', (reservation_id,)).fetchone()
        require(row is not None and row['state'] == 'RESERVED', 'dispatch_not_permitted')
        require(row['request_sha256'] == request_sha256, 'request_bytes_changed')
        require(at < instant(row['valid_until']), 'price_evidence_expired')
        db.execute("UPDATE reservations SET state='IN_FLIGHT' WHERE id=?", (reservation_id,))
    return {'dispatch_permitted_once': True, 'network_performed': False}


def mark_uncertain(path, reservation_id):
    with transaction(path) as db:
        row = db.execute('SELECT * FROM reservations WHERE id=?', (reservation_id,)).fetchone()
        require(row is not None and row['actual_micro'] is None, 'reservation_not_open')
        db.execute("UPDATE reservations SET state='UNCERTAIN' WHERE id=?", (reservation_id,))
        return totals(db)


def settle(path, reservation_id, proof_path, proof_sha):
    proof = evidence(proof_path, proof_sha)
    require(proof.get('kind') == 'final_charge_reconciliation'
            and proof.get('reservation_id') == reservation_id
            and proof.get('billing_final') is True, 'final_charge_unknown')
    actual = micros(proof.get('actual_cost_usd'))
    with transaction(path) as db:
        row = db.execute('SELECT * FROM reservations WHERE id=?', (reservation_id,)).fetchone()
        require(row is not None and row['actual_micro'] is None, 'reservation_not_open')
        db.execute("UPDATE reservations SET actual_micro=?,state='SETTLED',settlement_evidence=? WHERE id=?",
                   (actual, proof_sha, reservation_id))
        if actual > row['maximum_micro'] or totals(db)['committed_micro_usd'] > LIMIT_MICRO_USD:
            db.execute("UPDATE budget SET state='FROZEN' WHERE id=1")
        return totals(db)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['init', 'status'])
    parser.add_argument('--ledger', required=True)
    args = parser.parse_args()
    try:
        result = initialize(args.ledger) if args.command == 'init' else status(args.ledger)
        print(json.dumps(result, ensure_ascii=False))
    except (Blocked, sqlite3.Error, OSError) as error:
        # No evidence contents or provider values printed.
        print(json.dumps({'status': 'BLOCKED', 'reason': str(error) if isinstance(error, Blocked) else type(error).__name__}))
        raise SystemExit(2)


if __name__ == '__main__':
    main()
