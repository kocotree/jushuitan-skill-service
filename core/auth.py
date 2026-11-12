from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from .config import REFRESH_TOKEN_URL
from .sign import generate_sign
from .token_repository import get_latest_refresh_token, get_latest_token


TZ_UTC8 = timezone(timedelta(hours=8))
LOG_PREVIEW_LIMIT = 500

_token_store: dict[str, str] = {}
_token_lock = threading.RLock()


def get_logger() -> logging.Logger:
    logger = logging.getLogger("jushuitan.service")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


LOGGER = get_logger()


def mask(value: str | None, keep: int = 4) -> str | None:
    if not value:
        return value
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}{'*' * (len(value) - keep * 2)}{value[-keep:]}"


def preview_text(text: str, limit: int = LOG_PREVIEW_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...<truncated>"


def require_credentials() -> tuple[str, str]:
    app_key = os.environ.get("JUSHUITAN_OP_DW_APP_KEY")
    app_secret = os.environ.get("JUSHUITAN_OP_DW_APP_SECRET")
    if not app_key or not app_secret:
        raise RuntimeError("missing JUSHUITAN_OP_DW_APP_KEY or JUSHUITAN_OP_DW_APP_SECRET in environment variables")
    return app_key, app_secret


def get_access_token() -> str | None:
    return _token_store.get("access_token")


def now() -> datetime:
    return datetime.now(TZ_UTC8)


def epoch_seconds(dt: datetime) -> str:
    return str(int(dt.timestamp()))


def sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if key in {"access_token", "refresh_token", "sign"}:
            result[key] = mask(str(value))
        else:
            result[key] = value
    return result


def sanitize_response(text: str) -> str:
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        return preview_text(text)

    data = body.get("data")
    if isinstance(data, dict):
        data = dict(data)
        if data.get("access_token"):
            data["access_token"] = mask(str(data["access_token"]))
        if data.get("refresh_token"):
            data["refresh_token"] = mask(str(data["refresh_token"]))
        body["data"] = data
    return preview_text(json.dumps(body, ensure_ascii=False))


def _persist_token(data: dict[str, Any], created_at: datetime) -> None:
    """功能说明：缓存令牌及到期时间。

    参数：
        data：包含 access_token、expires_in 及可选 refresh_token 的记录。
        created_at：记录生成时间，用于计算到期时间。
    返回值：
        None：更新当前进程缓存。
    """
    _token_store["access_token"] = str(data["access_token"])
    _token_store["refresh_token"] = str(data.get("refresh_token") or "")
    _token_store["expires_in"] = str(int(data["expires_in"]))
    _token_store["created_at"] = created_at.isoformat()
    _token_store["expires_at"] = (created_at + timedelta(seconds=int(data["expires_in"]))).isoformat()
    LOGGER.info(
        "token saved access_token=%s refresh_token=%s expires_in=%s created_at=%s expires_at=%s",
        mask(_token_store["access_token"]),
        mask(_token_store["refresh_token"]),
        _token_store["expires_in"],
        _token_store["created_at"],
        _token_store["expires_at"],
    )


def _access_token_is_valid() -> bool:
    """检查缓存是否存在尚未到期的 access_token。"""
    expires_at = _token_store.get("expires_at")
    return bool(get_access_token() and expires_at and datetime.fromisoformat(expires_at) > now())


def _load_access_token(stale_access_token: str | None) -> bool:
    """功能说明：从数据库加载未到期且未被接口拒绝的 access_token。

    参数：
        stale_access_token：已被接口拒绝的 token，读取到相同值时跳过。
    返回值：
        bool：成功加载有效的数据库 access_token 时返回 True，否则返回 False。
    """
    data = get_latest_token()
    access_token = data.get("access_token")
    if not access_token or access_token == stale_access_token:
        LOGGER.warning("mysql access_token missing or already rejected by upstream")
        return False
    created_at = data.get("create_time")
    expires_in = data.get("expires_in")
    if not isinstance(created_at, datetime) or expires_in is None:
        LOGGER.warning("mysql access_token expiry information missing")
        return False
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=TZ_UTC8)
    expires_at = created_at + timedelta(seconds=int(expires_in))
    if expires_at <= now():
        LOGGER.warning("mysql access_token expired expires_at=%s", expires_at.isoformat())
        return False
    _persist_token(data, created_at)
    LOGGER.info("using access_token from mysql")
    return True


def _handle_token_response(raw_text: str, created_at: datetime) -> bool:
    try:
        body = json.loads(raw_text)
    except json.JSONDecodeError:
        LOGGER.exception("invalid token response json")
        return False

    if body.get("code") != 0:
        LOGGER.error("token api failed: %s", preview_text(raw_text))
        return False

    data = body.get("data") or {}
    if not data.get("access_token") or not data.get("refresh_token") or data.get("expires_in") is None:
        LOGGER.error("token response missing fields: %s", preview_text(json.dumps(data, ensure_ascii=False)))
        return False

    _persist_token(data, created_at)
    return True


def _post_token(url: str, params: dict[str, Any], timeout: int) -> str | None:
    LOGGER.info("token request url=%s params=%s", url, json.dumps(sanitize_payload(params), ensure_ascii=False))
    try:
        response = requests.post(
            url,
            data=params,
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException:
        LOGGER.exception("token request failed")
        return None

    LOGGER.info("token response status=%s body=%s", response.status_code, sanitize_response(response.text))
    return response.text


def _retry(label: str, worker) -> None:
    for attempt in range(1, 4):
        LOGGER.info("%s attempt %s/3", label, attempt)
        try:
            if worker():
                LOGGER.info("%s success", label)
                return
        except Exception:
            LOGGER.exception("%s raised exception", label)
        if attempt < 3:
            time.sleep(1)
    raise RuntimeError(f"{label} failed after 3 attempts")


def refresh_token(timeout: int = 30, stale_access_token: str | None = None) -> None:
    """
    功能说明：从 MySQL 读取最新 refresh_token，并刷新进程内的 access_token。

    参数：
        timeout：调用聚水潭刷新接口的超时时间，单位为秒。
        stale_access_token：触发刷新时使用的旧 access_token，用于避免并发重复刷新。

    返回值：
        None：刷新成功后更新进程内 token，不返回数据。
    """
    with _token_lock:
        current_access_token = get_access_token()
        if stale_access_token and current_access_token != stale_access_token and _access_token_is_valid():
            LOGGER.info("access_token already refreshed by another thread, skipping duplicate refresh")
            return

        app_key, app_secret = require_credentials()
        refresh_token_value = get_latest_refresh_token()

        def worker() -> bool:
            created_at = now()
            params = {
                "app_key": app_key,
                "timestamp": epoch_seconds(created_at),
                "grant_type": "refresh_token",
                "charset": "utf-8",
                "refresh_token": refresh_token_value,
                "scope": "all",
            }
            params["sign"] = generate_sign(app_secret, params)
            response_text = _post_token(REFRESH_TOKEN_URL, params, timeout)
            return bool(response_text) and _handle_token_response(response_text, created_at)

        _retry("refresh token", worker)


def ensure_token(timeout: int = 30, stale_access_token: str | None = None) -> bool:
    """
    功能说明：优先复用未过期的缓存或数据库 access_token，不可用时调用刷新接口。

    参数：
        timeout：调用聚水潭刷新接口的超时时间，单位为秒。
        stale_access_token：已被接口拒绝的 access_token，用于强制重新读库并跳过旧值。

    返回值：
        bool：本次是否调用了聚水潭刷新接口；复用缓存或数据库 token 时返回 False。
    """
    if _access_token_is_valid() and get_access_token() != stale_access_token:
        return False
    with _token_lock:
        if _access_token_is_valid() and get_access_token() != stale_access_token:
            return False
        LOGGER.info("cached access_token missing, expired or rejected, reloading mysql")
        if _load_access_token(stale_access_token):
            return False
        LOGGER.warning("mysql access_token unavailable, falling back to refresh_token")
        refresh_token(timeout=timeout)
        return True
