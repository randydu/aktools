# -*- coding:utf-8 -*-
# !/usr/bin/env python
"""
Date: 2026/06/20 15:00
Desc: Token 管理端点（需要认证）
"""
import logging

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse

from aktools.auth.token_store import token_store
from aktools.login.user_login import User, get_current_active_user

logger = logging.getLogger("AKToolsLog")
app_token_mgmt = APIRouter()


@app_token_mgmt.post("/tokens")
def token_create(
    user: str = Query("default", description="关联用户名"),
    _current_user: User = Depends(get_current_active_user),
):
    raw = token_store.create_token(user)
    logger.info(f"API token 已创建: user={user}, prefix={raw[:11]}…")
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"token": raw, "user_name": user},
    )


@app_token_mgmt.get("/tokens")
def token_list(
    _current_user: User = Depends(get_current_active_user),
):
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=token_store.list_tokens(),
    )


@app_token_mgmt.delete("/tokens")
def token_revoke(
    token: str = Query(..., min_length=1, description="要撤销的完整 Token"),
    _current_user: User = Depends(get_current_active_user),
):
    ok = token_store.revoke(token)
    if ok:
        logger.info(f"API token 已撤销: prefix={token[:11]}…")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"revoked": True},
        )
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"error": "Token 不存在或已撤销"},
    )
