# -*- coding:utf-8 -*-
# !/usr/bin/env python
"""
Date: 2022/8/18 20:16
Desc: 登录文件 (v2 — SQLite token store)
"""
import logging
from typing import Optional

from fastapi import APIRouter
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel

from aktools.auth.token_store import token_store

logger = logging.getLogger("AKToolsLog")
app_user_login = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token", auto_error=False)


class User(BaseModel):
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    disabled: Optional[bool] = None


async def get_current_user(token: str = Depends(oauth2_scheme)):
    """Validate API token from SQLite store."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_name = token_store.validate(token)
    if not user_name:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return User(username=user_name)


async def get_current_active_user(current_user: User = Depends(get_current_user)):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


@app_user_login.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """Legacy login — returns the first active token from the store."""
    tokens = token_store.list_tokens()
    active = [t for t in tokens if not t["revoked"]]
    if not active:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No API tokens configured. Check server logs for the auto-created root token.",
        )
    # Return the first active token's prefix as a hint; the full token must be
    # retrieved from the server log or created via a valid token.
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Username/password login is deprecated. "
            "Use an API token with 'Authorization: Bearer <token>'. "
            "Token management: POST /api/public/v1/tokens"
        ),
    )
