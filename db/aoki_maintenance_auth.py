import hashlib
import hmac
import ipaddress
import os


ROLES = {"MAINTENANCE_VALIDATOR", "MAINTENANCE_ADMIN"}


def token_hash(token):
    if not isinstance(token, str) or not token:
        raise ValueError("El token es obligatorio")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def authenticate_bearer(store, authorization):
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:].strip()
    if not token:
        return None
    candidate = token_hash(token)
    for actor in store.list_active_actors():
        if hmac.compare_digest(actor["tokenHash"], candidate):
            return actor
    return None


def writes_are_allowed(debug, remote_addr, headers, environ=None):
    environ = environ or os.environ
    if str(environ.get("MAINTENANCE_WRITES_ENABLED", "")).lower() != "true":
        return False, "MAINTENANCE_WRITES_DISABLED"
    if debug:
        return False, "DEBUG_MODE_NOT_ALLOWED"
    try:
        if ipaddress.ip_address(remote_addr or "").is_loopback:
            return True, None
    except ValueError:
        pass
    trusted_proxy = str(
        environ.get("MAINTENANCE_TRUSTED_PROXY_TLS", "")
    ).lower() == "true"
    if trusted_proxy and headers.get("X-Forwarded-Proto", "").lower() == "https":
        return True, None
    return False, "LOCAL_OR_TRUSTED_TLS_REQUIRED"
