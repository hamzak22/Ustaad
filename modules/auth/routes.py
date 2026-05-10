from fastapi import APIRouter, Depends, HTTPException, status
from typing import Annotated
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel

#database imports
import database
from database import get_db_connection
import psycopg
from psycopg.errors import UniqueViolation

#model imports
from .models import RegisterUserModel, RegisterAsWorkerModel

#auth
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pwdlib import PasswordHash
from .token_generator import Token, TokenData, generate_access_token, generate_refresh_token, SECRET_KEY, ALGORITHM
import jwt
from jwt.exceptions import InvalidTokenError
from modules.notifications.models import NotificationCreate
from modules.notifications.service import persist_notification, broadcast_notification

password_hash = PasswordHash.recommended()

oauth2_scheme = OAuth2PasswordBearer("/api/auth/token")

INVALID_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid email or password",
    headers={"WWW-Authenticate": "Bearer"},
)

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)

async def require_active_worker(token:Annotated[str, Depends(oauth2_scheme)], conn=Depends(get_db_connection)) :
    try :
        payload = jwt.decode(token, SECRET_KEY, algorithms=ALGORITHM)
    except InvalidTokenError :
        raise INVALID_CREDENTIALS_EXCEPTION
    
    email = payload.get("sub")

    if not email :
        raise INVALID_CREDENTIALS_EXCEPTION
    
    async with conn.cursor() as cur :
        await cur.execute("SELECT w.worker_id, u.user_id, u.is_active, u.role FROM worker_profile w JOIN Users u ON u.user_id = w.worker_id WHERE u.email = %s", (email,))

        worker = await cur.fetchone()

        if not worker : raise HTTPException(status_code=403, detail="Please complete your worker profile")

        if not worker.is_active : raise HTTPException(status_code=403, detail="Please complete your worker profile")

        if worker.role != 'Worker':
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="Unauthorized access. Worker account required."
            )

        return worker
    

async def get_current_user_id(token:Annotated[str, Depends(oauth2_scheme)], conn=Depends(get_db_connection)) :
    try :
        payload = jwt.decode(token, SECRET_KEY, algorithms=ALGORITHM)
    except InvalidTokenError :
        raise INVALID_CREDENTIALS_EXCEPTION
    
    user_id = payload.get("sub")

    if not user_id :
        raise INVALID_CREDENTIALS_EXCEPTION
    
    return user_id



class RefreshTokenRequest(BaseModel):
    refresh_token: str

@router.post("/register")
async def register_user(user_data : RegisterUserModel, conn = Depends(get_db_connection)):
    #if email does not exist, user can create account
    hashed_password = password_hash.hash(password=user_data.password)
    print("hello")

    try :
        async with conn.transaction() :
            async with conn.cursor() as cur :
                await cur.execute(
                """INSERT INTO Users(full_name, email, password_hash,phone_number, city, role) VALUES(%s,%s,%s,%s,%s, %s) RETURNING user_id, full_name, email""",
                (user_data.full_name, user_data.email, hashed_password, user_data.phone_number, user_data.city ,user_data.role.value)
            )
                user = await cur.fetchone()

                print(user)

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
async def login_for_access_token(form_data : Annotated[OAuth2PasswordRequestForm, Depends()], conn = Depends(get_db_connection)) :
    #first check if user exists in db, if not, throw error.

    async with conn.cursor() as cur :
        await cur.execute("""SELECT user_id, full_name, email, role, password_hash FROM Users WHERE email=%s""", (form_data.username,))
        user = await cur.fetchone()

        if not user :
            raise INVALID_CREDENTIALS_EXCEPTION

        if not password_hash.verify(form_data.password, user['password_hash']) :
            raise INVALID_CREDENTIALS_EXCEPTION
        
        json_userid = str(user["user_id"])
        
        token_data = {
        "sub": json_userid, 
        "email" : user["email"],
        "full_name": user["full_name"],
        "role": user["role"]
    }
        access_token = generate_access_token(
            data=token_data
        )

        refresh_token_text = generate_refresh_token()
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        await cur.execute("""INSERT INTO RefreshTokens(user_id, token_text, expires_at) VALUES(%s,%s,%s)""",
                          (user["user_id"], refresh_token_text, expires_at))

        return {
        "access_token": access_token,
        "refresh_token": refresh_token_text, # Or set this as an HttpOnly cookie
        "token_type": "bearer"
    }

@router.post("/refresh")
async def get_new_access_token(refresh_data: RefreshTokenRequest, conn = Depends(get_db_connection)) :
    async with conn.cursor() as cur :
        await cur.execute(
            """SELECT u.user_id, u.full_name, u.email, u.role, u.is_active, rt.expires_at FROM RefreshTokens rt JOIN Users u ON rt.user_id = u.user_id WHERE rt.token_text=%s""",
            (refresh_data.refresh_token,),
        )

        data = await cur.fetchone()

    
    if not data or data['expires_at'] < datetime.now(timezone.utc) :
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not data["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is disabled, please contact administrator",
        )
    
    token_data = {
        "sub" : str(data['user_id']),
        "email" : data["email"],
        "role" : data['role'],
        "full_name" : data['full_name']
    }

    new_access_token = generate_access_token(data=token_data)
    new_refresh_token = generate_refresh_token()
    new_expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    async with conn.transaction():
        async with conn.cursor() as cur:
            await cur.execute(
                """DELETE FROM RefreshTokens WHERE token_text=%s""",
                (refresh_data.refresh_token,),
            )
            await cur.execute(
                """INSERT INTO RefreshTokens(user_id, token_text, expires_at) VALUES(%s,%s,%s)""",
                (data["user_id"], new_refresh_token, new_expires_at),
            )

    return {
        "access_token" : new_access_token,
        "refresh_token": new_refresh_token,
        "token_type" : "bearer"
    }


@router.get("/users/me")
async def get_user_profile(token : Annotated[str, Depends(oauth2_scheme)], conn = Depends(get_db_connection)) :

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except InvalidTokenError :
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_id = payload.get("sub")
    
    if not user_id :
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized access",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    
    async with conn.transaction() :
        async with conn.cursor() as cur :
            await cur.execute("""SELECT user_id, full_name, email, phone_number, role, is_active FROM Users WHERE user_id=%s""", (user_id,))
            user = await cur.fetchone()

            if not user :
                raise HTTPException(status_code=404, detail="User not found")
            
            if not user["is_active"]:
                raise HTTPException(status_code=403, detail="Your account is disabled, please contact administrator")
            
            return user
        
@router.post("/worker-profile")
async def create_worker_profile(data : RegisterAsWorkerModel, token : Annotated[str, Depends(oauth2_scheme)],conn = Depends(get_db_connection) ) :
    #get user id from token, get experience, bio, hourly rate from body, insert into worker profile if does not exist.

    try :
        payload = jwt.decode(token, SECRET_KEY, algorithms=ALGORITHM)
    except InvalidTokenError :
        raise INVALID_CREDENTIALS_EXCEPTION
    
    user_id = payload.get("sub")
    if not user_id :
        raise INVALID_CREDENTIALS_EXCEPTION
    
    services = data.services
    
    try : 
        async with conn.transaction() :
            notification = None
            async with conn.cursor() as cur :
                await cur.execute("""SELECT user_id, role FROM Users WHERE user_id=%s""", (user_id,))
                userdata = await cur.fetchone()

                print(userdata)

                if not userdata :
                    raise INVALID_CREDENTIALS_EXCEPTION
                
                if userdata['role'] == 'Customer' :
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Customer can not create a worker profile")
                
                await cur.execute("""INSERT INTO worker_profile(worker_id,experience,bio) VALUES(%s,%s,%s)""", (user_id,data.experience, data.bio))

                try :
                    

                    for service in services :
                        await cur.execute("""INSERT INTO worker_skills(worker_id, service_id, hourly_rate) VALUES(%s,%s,%s)""", (user_id, service.id, service.hourly_rate,))

                except UniqueViolation :
                    raise HTTPException(status_code=400, detail="Can not add one service multiple times")

                notification = await persist_notification(
                    conn,
                    NotificationCreate(
                        recipient_id=user_id,
                        actor_id=user_id,
                        notification_type="profile_updated",
                        title="Worker profile created",
                        body="Your worker profile has been created successfully.",
                        entity_type="worker_profile",
                        entity_id=None,
                        metadata={"experience": data.experience},
                    ),
                )

        if notification:
            await broadcast_notification(notification)

        return {
            "message" : "Worker Profile Created Succesfully"
        }
    except UniqueViolation as e :
        print(e)
        raise HTTPException(status_code=500, detail="Worker Profile already created")
    





    

    


