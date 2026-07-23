from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from core import auth


class AuthTestCase(unittest.TestCase):
    """验证数据库 refresh_token 与聚水潭刷新流程的衔接。"""

    def setUp(self) -> None:
        """清理进程内 token 并准备聚水潭应用凭证。"""
        auth._token_store.clear()
        self.environment = patch.dict(
            os.environ,
            {
                "JUSHUITAN_OP_DW_APP_KEY": "app-key",
                "JUSHUITAN_OP_DW_APP_SECRET": "app-secret",
            },
        )
        self.environment.start()

    def tearDown(self) -> None:
        """恢复环境变量并清理进程内 token。"""
        self.environment.stop()
        auth._token_store.clear()

    @patch("core.auth._post_token")
    @patch("core.auth.get_latest_refresh_token")
    def test_ensure_token_refreshes_with_database_value(
        self,
        get_latest_refresh_token,
        post_token,
    ) -> None:
        """内存无 token 时应使用数据库 refresh_token 调用刷新接口。"""
        get_latest_refresh_token.return_value = "database-refresh-token"
        post_token.return_value = json.dumps(
            {
                "code": 0,
                "data": {
                    "access_token": "new-access-token",
                    "refresh_token": "new-refresh-token",
                    "expires_in": 3600,
                },
            }
        )

        auth.ensure_token()

        self.assertEqual(auth.get_access_token(), "new-access-token")
        get_latest_refresh_token.assert_called_once_with()
        request_params = post_token.call_args.args[1]
        self.assertEqual(request_params["refresh_token"], "database-refresh-token")

    @patch("core.auth.get_latest_refresh_token")
    def test_refresh_skips_when_another_thread_has_refreshed(
        self,
        get_latest_refresh_token,
    ) -> None:
        """其他线程已更新 access_token 时不应重复读取数据库和刷新。"""
        auth._token_store["access_token"] = "new-access-token"

        auth.refresh_token(stale_access_token="old-access-token")

        get_latest_refresh_token.assert_not_called()


if __name__ == "__main__":
    unittest.main()
