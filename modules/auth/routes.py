from fastapi import APIRouter, Depends, HTTPException, status
from typing import Annotated

#database imports
import database
from database import get_db_connection
import psycopg

#model imports
from .models import RegisterUserModel, RegisterAsWorkerModel

#auth
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pwdlib import PasswordHash
from .token_generator import Token, TokenData, generate_access_token

password_hash = PasswordHash.recommended()

oauth2_scheme = OAuth2PasswordBearer("/token")

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)

@router.post("/register")
async def register_user(user_data : RegisterUserModel, conn = Depends(get_db_connection)):
    #if email does not exist, user can create account
    hashed_password = password_hash.hash(password=user_data.password)

    try :
        async with conn.transaction() :
            async with conn.cursor() as cur :
                await cur.execute(
                """INSERT INTO Users(full_name, email, password_hash,phone_number, role) VALUES(%s,%s,%s,%s,%s) RETURNING user_id, full_name, email""",
                (user_data.full_name, user_data.email, hashed_password, user_data.phone_number, user_data.role.value)
            )
                user = await cur.fetchone()

        return {
        "message" : "Registration Succesfull",
        "user" : user
            }
    except psycopg.errors.UniqueViolation as e:
        # PostgreSQL provides the specific constraint that was tripped
        # diag.constraint_name is populated by psycopg 3
        violated_constraint = e.diag.constraint_name

        if violated_constraint == "users_email_key":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="A user with this email already exists."
            )
        elif violated_constraint == "users_phone_number_key":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="This phone number is already in use."
            )
        else:
            # Catch-all for other unique constraints (like username if you add it)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="This account already exists."
            )
    except Exception as e:
        # Catch-all for internal server errors so the client doesn't get raw tracebacks
        # log.error(f"Unexpected error: {e}")
        raise HTTPException(
            status_code=500,
            detail="An internal error occurred"
        )
    
@router.post("/token")
async def login_for_access_token(form_data : Annotated[OAuth2PasswordRequestForm, Depends()], conn = Depends(get_db_connection)) -> Token :
    #first check if user exists in db, if not, throw error.

    async with conn.cursor() as cur :
        await cur.execute("""SELECT full_name, email, role, password_hash FROM Users WHERE email=%s""", (form_data.username,))
        user = await cur.fetchone()

        print(user)

        if not user :
            raise HTTPException(status_code=404, detail="Invalid email or password")

        if not password_hash.verify(form_data.password, user['password_hash']) :
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        token_data = {
        "sub": user["email"], # 'sub' (subject) is the standard field for user ID/email
        "full_name": user["full_name"],
        "role": user["role"]
    }
        access_token = generate_access_token(
            data=token_data
        )

        return access_token



    

    


