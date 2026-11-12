from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from core.token_repository import get_latest_refresh_token, get_latest_token


class TokenRepositoryTestCase(unittest.TestCase):
    """验证 MySQL refresh_token 查询行为。"""

    def setUp(self) -> None:
        """准备测试所需的数据库环境变量。"""
        self.environment = patch.dict(
            os.environ,
            {
                "MYSQL_HOST": "mysql.example",
                "MYSQL_PORT": "3306",
                "MYSQL_USER": "service",
                "MYSQL_PASSWORD": "secret",
                "MYSQL_DATABASE": "jushuitan",
            },
        )
        self.environment.start()

    def tearDown(self) -> None:
        """恢复测试修改的环境变量。"""
        self.environment.stop()

    @patch("core.token_repository.pymysql.connect")
    def test_get_latest_refresh_token_returns_database_value(self, connect: MagicMock) -> None:
        """数据库存在记录时应返回 refresh_token 并关闭连接。"""
        connection = connect.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"refresh_token": "database-refresh-token"}

        result = get_latest_refresh_token()

        self.assertEqual(result, "database-refresh-token")
        cursor.execute.assert_called_once()
        self.assertIn("`access_token`, `refresh_token`, `create_time`, `expires_in`", cursor.execute.call_args.args[0])
        connection.close.assert_called_once()

    @patch("core.token_repository.pymysql.connect")
    def test_get_latest_refresh_token_rejects_empty_result(self, connect: MagicMock) -> None:
        """数据库没有可用记录时应抛出明确异常。"""
        connection = connect.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = None

        with self.assertRaisesRegex(RuntimeError, "no token record"):
            get_latest_token()

        connection.close.assert_called_once()

    @patch("core.token_repository.pymysql.connect")
    def test_access_token_does_not_require_refresh_token(self, connect: MagicMock) -> None:
        """最新记录只含 access_token 时也可以正常读取。"""
        cursor = connect.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"access_token": "database-access", "refresh_token": None}

        self.assertEqual(get_latest_token()["access_token"], "database-access")
        with self.assertRaisesRegex(RuntimeError, "no available refresh_token"):
            get_latest_refresh_token()


if __name__ == "__main__":
    unittest.main()
