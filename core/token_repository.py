from __future__ import annotations

import logging
import os

import pymysql
from pymysql.cursors import DictCursor


LOGGER = logging.getLogger("jushuitan.service")


def _require_env(name: str) -> str:
    """读取必需的环境变量。"""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing {name} in environment variables")
    return value


def get_latest_refresh_token() -> str:
    """
    功能说明：从 MySQL 的 token 表读取创建时间最新的 refresh_token。

    返回值：
        str：最新且非空的 refresh_token。
    """
    LOGGER.info("loading latest refresh_token from mysql")
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
                SELECT `refresh_token`
                FROM `token`
                WHERE `refresh_token` IS NOT NULL
                  AND `refresh_token` <> ''
                ORDER BY `create_time` DESC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
    except (pymysql.MySQLError, ValueError):
        LOGGER.exception("failed to load refresh_token from mysql")
        raise
    finally:
        if connection is not None:
            connection.close()

    refresh_token = str(row["refresh_token"]) if row and row.get("refresh_token") else ""
    if not refresh_token:
        LOGGER.error("no available refresh_token found in mysql")
        raise RuntimeError("no available refresh_token found in mysql token table")

    LOGGER.info("latest refresh_token loaded from mysql")
    return refresh_token
