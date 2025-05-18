import jwt
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from typing import Optional
import bcrypt
import logging
import mysql.connector

import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import config

logger = logging.getLogger(__name__)

# Pydantic models
class Token(BaseModel):
    access_token: str
    token_type: str
    user_id: str
    username: str

class TokenData(BaseModel):
    user_id: Optional[str] = None
    username: Optional[str] = None

class User(BaseModel):
    user_id: str
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    disabled: Optional[bool] = None

class UserInDB(User):
    hashed_password: str

class UserCreate(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    full_name: Optional[str] = None

# Authentication config
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "a_very_secret_key_for_development_only")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Helper Functions
def get_db_connection():
    """Connects to the MySQL database and returns a connection object."""
    try:
        db_config = config.get_mysql_connection_config()
        connection = mysql.connector.connect(**db_config)
        logger.debug("Successfully connected to MySQL database.")
        return connection
    except mysql.connector.Error as e:
        logger.error(f"Failed to connect to MySQL database: {e}")
        return None

def verify_password(plain_password, hashed_password):
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def get_password_hash(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def get_user(username: str):
    """Get user from database by username"""
    conn = get_db_connection()
    if not conn:
        return None
        
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT user_id, username, email, hashed_password, full_name, disabled FROM users WHERE username = %s", (username,))
        user_data = cursor.fetchone()
        
        if user_data:
            return UserInDB(**user_data)
            
    except mysql.connector.Error as e:
        logger.error(f"Error getting user from database: {e}")
    finally:
        if conn:
            conn.close()
    
    return None

def get_user_by_id(user_id: str):
    """Get user from database by user_id"""
    conn = get_db_connection()
    if not conn:
        return None
        
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT user_id, username, email, full_name, disabled FROM users WHERE user_id = %s", (user_id,))
        user_data = cursor.fetchone()
        
        if user_data:
            return User(**user_data)
            
    except mysql.connector.Error as e:
        logger.error(f"Error getting user by ID from database: {e}")
    finally:
        if conn:
            conn.close()
    
    return None

def authenticate_user(username: str, password: str):
    user = get_user(username)
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        username: str = payload.get("username")
        if user_id is None:
            raise credentials_exception
        token_data = TokenData(user_id=user_id, username=username)
    except jwt.PyJWTError:
        raise credentials_exception
        
    user = get_user_by_id(token_data.user_id)
    if user is None:
        raise credentials_exception
        
    return user

async def get_current_active_user(current_user: User = Depends(get_current_user)):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

def create_user(user_data: UserCreate):
    """Create a new user in the database"""
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
        
    try:
        # Check if username already exists
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT user_id FROM users WHERE username = %s", (user_data.username,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Username already registered")
        
        # Generate user_id and hash password
        user_id = f"user_{datetime.now().timestamp()}".replace(".", "")
        hashed_password = get_password_hash(user_data.password)
        
        # Insert new user
        cursor.execute(
            """
            INSERT INTO users 
            (user_id, username, email, full_name, hashed_password, disabled, usual_location)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user_id,
                user_data.username,
                user_data.email,
                user_data.full_name,
                hashed_password,
                False,
                "Unknown"
            )
        )
        conn.commit()
        
        return {
            "user_id": user_id,
            "username": user_data.username,
            "email": user_data.email,
            "full_name": user_data.full_name
        }
        
    except mysql.connector.Error as e:
        logger.error(f"Error creating user in database: {e}")
        raise HTTPException(status_code=500, detail="Database error")
    finally:
        if conn:
            conn.close()
