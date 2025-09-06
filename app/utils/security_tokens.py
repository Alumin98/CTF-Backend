import base64, secrets, hashlib, hmac

def generate_reset_token(nbytes: int = 32) -> str:
    # URL-safe, no padding, human-pasteable
    token = base64.urlsafe_b64encode(secrets.token_bytes(nbytes)).rstrip(b'=')
    return token.decode('ascii')

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

def constant_time_equals(a: str | None, b: str | None) -> bool:
    a = a or ""
    b = b or ""
    return hmac.compare_digest(a, b)