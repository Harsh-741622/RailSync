from __future__ import annotations
import base64, binascii, hashlib, hmac, json, os, time
from contextvars import ContextVar
from dataclasses import dataclass
from fastapi import HTTPException

@dataclass(frozen=True)
class Principal:
    subject: str
    role: str

current_actor: ContextVar[str | None] = ContextVar("railsync_actor", default=None)

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

def validate_auth_configuration() -> None:
    mode = os.getenv("RAILSYNC_AUTH_MODE", "production").lower()
    if mode not in {"demo", "production"}:
        raise RuntimeError("RAILSYNC_AUTH_MODE must be demo or production")
    if mode == "production" and len(os.getenv("RAILSYNC_AUTH_SECRET", "")) < 32:
        raise RuntimeError("Production mode requires a RAILSYNC_AUTH_SECRET of at least 32 characters")

def create_access_token(subject: str, role: str, expires_in_seconds: int = 3600, *, secret: str | None = None) -> str:
    """Create a signed token for a trusted identity-provisioning service.

    This deliberately has no HTTP endpoint: issuing operational credentials is an
    administrative concern and must not be exposed by the simulator itself.
    """
    if not subject or role not in {"operator", "approver"}:
        raise ValueError("A non-empty subject and supported role are required")
    signing_secret = secret if secret is not None else os.getenv("RAILSYNC_AUTH_SECRET", "")
    if len(signing_secret) < 32:
        raise RuntimeError("A 32+ character signing secret is required to issue access tokens")
    payload = {"sub": subject, "role": role, "exp": int(time.time()) + expires_in_seconds}
    payload_part = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = _b64(hmac.new(signing_secret.encode(), payload_part.encode(), hashlib.sha256).digest())
    return f"{payload_part}.{signature}"

def authenticate(authorization: str | None) -> Principal:
    mode = os.getenv("RAILSYNC_AUTH_MODE", "production").lower()
    if mode == "demo":
        return Principal("Demo Station Master", "approver")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Bearer authentication is required")
    try:
        payload_part, signature = authorization[7:].split(".", 1)
        secret = os.environ["RAILSYNC_AUTH_SECRET"].encode()
        expected = _b64(hmac.new(secret, payload_part.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected): raise ValueError()
        payload = json.loads(_unb64(payload_part))
        if int(payload["exp"]) <= time.time(): raise ValueError()
        if payload["role"] not in {"operator", "approver"}: raise ValueError()
        return Principal(str(payload["sub"]), str(payload["role"]))
    except (KeyError, ValueError, TypeError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
        raise HTTPException(401, "Invalid or expired access token")

def require_approver(principal: Principal) -> None:
    if principal.role != "approver":
        raise HTTPException(403, "Approval requires approver role")
