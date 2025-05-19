from argon2 import PasswordHasher, exceptions as argon2_exceptions 
from jose import jwt 
from datetime import datetime, timedelta

#Password Hasher setup
ph = PasswordHasher()


#JWT Configuration
SECRET_KEY = "your_secret_key"
ALGORITHM = "HS256"
EXPIRE_MINUTES = 60

#Password Hashing Fuction
def get_password_hash(password: str) -> str:
    return ph.hash(password)

#Password Verification
def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return ph.verify(hashed_password, plain_password)
    except argon2_exceptions.VerifyMismatchError:
        return False
    except Exception as e:
        return False
    
#JWT Token Creation
def create_access_token(data: dict) -> str:
        expire = datetime.utcnow() + timedelta(minutes=EXPIRE_MINUTES)
        data.update({"exp": expire})
        return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)