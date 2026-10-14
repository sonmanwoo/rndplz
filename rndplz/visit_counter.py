"""Daily visit counts for the operator's connection page (2026-10-14).

A page view of a site document is counted per day (KST) with the visitor's cookie key run through the server's
secret (16 hex characters; a signed-in person counts by account, so two logins are one person). No IP, no user
agent, no conversation is kept. Automated browsers (the headless checks) and bots are not counted.

  <state>/visits/YYYY-MM-DD.json  {"views": n, "visitors": [key, ...], "accounts": [key, ...], "pages": {"/": n}}
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
AUTOMATED = re.compile(r'HeadlessChrome|bot\b|bot/|crawl|spider|slurp|curl/|wget|python-requests|python-urllib|'
                       r'Go-http-client|okhttp|Lighthouse|facebookexternalhit|Prerender', re.I)
DAY = re.compile(r'\d{4}-\d{2}-\d{2}')


class VisitCounter:
    def __init__(self, directory, secret):
        self.directory = Path(directory)
        self.secret = secret
        self.lock = threading.Lock()

    def record(self, context, path, user_agent, now=None):
        """Count one page view; False when it is not a person's (no user agent, an automated browser, no visitor)."""
        if not user_agent or AUTOMATED.search(user_agent) or not isinstance(context, dict):
            return False
        account = context.get('account') or {}
        source = ('account:' + account['id']) if account.get('id') else ('visitor:' + str(context.get('sid') or ''))
        if source == 'visitor:':
            return False
        key = hmac.new(self.secret, source.encode(), hashlib.sha256).hexdigest()[:16]
        day = (now or datetime.now(timezone.utc)).astimezone(KST).date().isoformat()
        target = self.directory / (day + '.json')
        with self.lock:
            try:
                data = json.loads(target.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                data = {}
            visitors, accounts, pages = set(data.get('visitors') or []), set(data.get('accounts') or []), dict(data.get('pages') or {})
            visitors.add(key)
            if account.get('id'):
                accounts.add(key)
            pages[path] = int(pages.get(path, 0)) + 1
            data = {'views': int(data.get('views', 0)) + 1, 'visitors': sorted(visitors), 'accounts': sorted(accounts), 'pages': pages}
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix('.tmp')
            temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            os.replace(temporary, target)
        return True


def visit_counts(directory, since):
    """{'today'|'week'|'all': {visitors, accounts, views}} over the daily files, and the first counted day."""
    days = {}
    for path in sorted(Path(directory).glob('*.json')) if Path(directory).is_dir() else ():
        if not DAY.fullmatch(path.stem):
            continue
        try:
            days[path.stem] = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
    rows = {}
    for name, start in since.items():
        chosen = [data for day, data in days.items() if start is None or day >= start.date().isoformat()]
        visitors = set().union(*(set(d.get('visitors') or []) for d in chosen)) if chosen else set()
        accounts = set().union(*(set(d.get('accounts') or []) for d in chosen)) if chosen else set()
        rows[name] = {'visitors': len(visitors), 'accounts': len(accounts), 'views': sum(int(d.get('views', 0)) for d in chosen)}
    return rows, (min(days) if days else None)
