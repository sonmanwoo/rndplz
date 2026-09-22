"""Bridge an explicitly supplied Vercel server secret to the existing file loader."""
import json
import os
from pathlib import Path
import tempfile

SECRET_KEY = "RNDPLZ_VERCEL_CODEX_AUTH_JSON"
MAX_SECRET_BYTES = 64 * 1024
_SCRATCH_ROOT = "/tmp"


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("invalid_constant")


def _minimal_auth(raw):
    if not isinstance(raw, str) or not raw or len(raw) > MAX_SECRET_BYTES:
        raise ValueError("invalid_secret")
    if len(raw.encode("utf-8")) > MAX_SECRET_BYTES:
        raise ValueError("invalid_secret")
    document = json.loads(raw, object_pairs_hook=_unique_object,
                          parse_constant=_invalid_constant)
    if (not isinstance(document, dict) or set(document) != {"auth_mode", "tokens"}
            or document["auth_mode"] != "chatgpt"):
        raise ValueError("invalid_secret")
    tokens = document["tokens"]
    if not isinstance(tokens, dict) or set(tokens) != {"access_token", "account_id"}:
        raise ValueError("invalid_secret")
    for value in tokens.values():
        if (not isinstance(value, str) or not value or len(value) > 20000
                or any(ord(char) < 33 or ord(char) > 126 for char in value)):
            raise ValueError("invalid_secret")
    return {"auth_mode": "chatgpt", "tokens": {
        "access_token": tokens["access_token"], "account_id": tokens["account_id"]}}


def configure_vercel_auth(env=None):
    """Return whether a private auth file was installed; never refresh or call a provider."""
    env = os.environ if env is None else env
    if (env.get("VERCEL") != "1" or env.get("APP_RUNTIME") != "hosted_public"
            or env.get("LLM_PROVIDER") != "codex_oauth"):
        return False
    # Even an invalid explicit value belongs to the existing RuntimeConfig validator.
    if "CODEX_AUTH_FILE" in env:
        return False
    if SECRET_KEY not in env:
        return False
    directory = None
    path = None
    try:
        document = _minimal_auth(env[SECRET_KEY])
        body = json.dumps(document, ensure_ascii=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
        directory = Path(tempfile.mkdtemp(prefix="rndplz-vercel-auth-", dir=_SCRATCH_ROOT))
        os.chmod(directory, 0o700)
        path = directory / "codex-auth.json"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as target:
            os.chmod(path, 0o600)
            target.write(body)
            target.flush()
            os.fsync(target.fileno())
        env["CODEX_AUTH_FILE"] = str(path)
        return True
    except Exception:
        # Do not propagate JSON fragments, paths, token values, or underlying errors.
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        if directory is not None:
            try:
                directory.rmdir()
            except OSError:
                pass
        raise RuntimeError("vercel_oauth_secret_invalid") from None
