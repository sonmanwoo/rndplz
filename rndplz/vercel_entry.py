"""Vercel WSGI entrypoint; temporary state is not persistent storage."""
import os
import re


os.environ.setdefault("RNDPLZ_STATE_DIR", "/tmp/rndplz-public-state")
# Restore the four previously published cards and their existing linked records.
# The broad personal-data flag and provider scope stay separate.
os.environ.setdefault("RNDPLZ_PUBLIC_PERSON_IDS", "LOCAL-MANWOO,LOCAL-JINHO,LOCAL-DASOL,LOCAL-HONG")
_hosts = set(filter(None, os.environ.get("RNDPLZ_ALLOWED_HOSTS", "").split(",")))
for _key in ("VERCEL_URL", "VERCEL_BRANCH_URL", "VERCEL_PROJECT_PRODUCTION_URL"):
    _host = os.environ.get(_key, "").lower()
    if re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+", _host):
        _hosts.add(_host)
os.environ["RNDPLZ_ALLOWED_HOSTS"] = ",".join(sorted(_hosts))

# Configure writable state and platform-provided hosts before app construction.
from .vercel_auth import configure_vercel_auth
configure_vercel_auth()

from .public_web import application
