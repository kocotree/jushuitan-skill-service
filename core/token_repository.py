from __future__ import annotations

import logging
import os
from typing import Any

import pymysql
from pymysql.cursors import DictCursor


LOGGER = logging.getLogger("jushuitan.service")


def _require_env(name: str) -> str:
    """读取必需的环境变量。"""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing {name} in environment variables")
    return value


def get_latest_token() -> dict[str, Any]:
    """
    功能说明：从 MySQL 的 token 表读取最新的令牌及有效期记录。

    返回值：
        dict[str, Any]：包含 access_token、refresh_token、create_time 和 expires_in 的记录。
    """
    LOGGER.info("loading latest token record from mysql")
    connection = None
    try:
        connection = pymysql.connect(
            host=_require_env("MYSQL_HOST"),
            port=int(os.environ.get("MYSQL_PORT", "3306")),
            user=_require_env("MYSQL_USER"),
            password=_require_env("MYSQL_PASSWORD"),
            database=_require_env("MYSQL_DATABASE"),
            charset="utf8mb4",
            cursorclass=DictCursor,
            connect_timeout=5,
            read_timeout=5,
            write_timeout=5,
            autocommit=True,
        )
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT `access_token`, `refresh_token`, `create_time`, `expires_in`
                FROM `token`
                ORDER BY `create_time` DESC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
    except (pymysql.MySQLError, ValueError):
        LOGGER.exception("failed to load token record from mysql")
        raise
    finally:
        if connection is not None:
            connection.close()

    if not row:
        LOGGER.error("no token record found in mysql")
        raise RuntimeError("no token record found in mysql token table")

    LOGGER.info("latest token record loaded from mysql create_time=%s", row.get("create_time"))
    return row


def get_latest_refresh_token() -> str:
    """读取最新记录中的 refresh_token，缺失时抛出异常。"""
    row = get_latest_token()
    refresh_token = row.get("refresh_token")
    if not refresh_token:
        LOGGER.error("no available refresh_token found in latest mysql record")
        raise RuntimeError("no available refresh_token found in latest mysql token record")

    LOGGER.info("latest refresh_token loaded from mysql")
    return str(refresh_token)
