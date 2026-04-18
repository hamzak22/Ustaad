import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from pydantic import BaseModel
from datetime import timezone, timedelta, datetime
import secrets

from core.config import get_settings

settings = get_settings()

password_hash = PasswordHash.recommended()

SECRET_KEY=settings.SECRET_KEY
ALGORITHM=settings.ALGORITHM
TOKEN_EXPIRATION_MINUTES=settings.TOKEN_EXPIRATION_MINUTES

class Token(BaseModel) :
    access_token : str
    token_type : str = "Bearer"

class TokenData(BaseModel) :
    full_name : str
    email : str 
    role : str 




#token generation flow 
# users logs in -> get user from db, if user exists -> generate jwt token from payload (email, role) -> return token

def generate_access_token(data : dict, expiresIn : timedelta | None=None) :
    to_encode = data.copy()

    if expiresIn :
        expirationTime = datetime.now(timezone.utc) + expiresIn
    else :
        expirationTime = datetime.now(timezone.utc) + timedelta(minutes=30)

    to_encode.update({"exp" : expirationTime})

    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    return encoded_jwt

def generate_refresh_token() :
    return secrets.token_urlsafe(64)