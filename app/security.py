from passlib.context import CryptContext


pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a plaintext password using the shared CryptContext."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify that ``plain_password`` matches ``hashed_password``."""
    return pwd_context.verify(plain_password, hashed_password)
