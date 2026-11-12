from __future__ import annotations

import json
import os
import unittest
from datetime import timedelta
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
    @patch("core.auth.get_latest_token")
    def test_ensure_token_refreshes_with_database_value(
        self,
        get_latest_token,
        get_latest_refresh_token,
        post_token,
    ) -> None:
        """数据库 access_token 已到期时应读取 refresh_token 刷新。"""
        get_latest_token.return_value = {
            "access_token": "expired-access",
            "create_time": auth.now() - timedelta(hours=2),
            "expires_in": 3600,
        }
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
        auth._token_store["expires_at"] = (auth.now() + timedelta(hours=1)).isoformat()

        auth.refresh_token(stale_access_token="old-access-token")

        get_latest_refresh_token.assert_not_called()

    @patch("core.auth.refresh_token")
    @patch("core.auth.get_latest_token")
    def test_initial_load_uses_database_access_and_original_expiry(self, get_latest_token, refresh) -> None:
        """首次加载使用数据库 access_token，按记录时间计算到期时间并缓存。"""
        created_at = auth.now().replace(tzinfo=None) - timedelta(minutes=30)
        get_latest_token.return_value = {
            "access_token": "database-access", "create_time": created_at, "expires_in": 3600,
        }

        self.assertFalse(auth.ensure_token())
        self.assertFalse(auth.ensure_token())

        self.assertEqual(auth.get_access_token(), "database-access")
        self.assertEqual(
            auth._token_store["expires_at"],
            (created_at.replace(tzinfo=auth.TZ_UTC8) + timedelta(hours=1)).isoformat(),
        )
        get_latest_token.assert_called_once()
        refresh.assert_not_called()

    @patch("core.auth.refresh_token")
    @patch("core.auth.get_latest_token")
    def test_expired_cache_reloads_mysql_before_refresh(self, get_latest_token, refresh) -> None:
        """缓存到期时先加载数据库的新 access_token。"""
        auth._persist_token({"access_token": "old", "expires_in": 1}, auth.now() - timedelta(hours=1))
        get_latest_token.return_value = {
            "access_token": "new", "create_time": auth.now(), "expires_in": 3600,
        }

        self.assertFalse(auth.ensure_token())
        self.assertEqual(auth.get_access_token(), "new")
        refresh.assert_not_called()

    @patch("core.auth.refresh_token")
    @patch("core.auth.get_latest_token")
    def test_rejected_token_is_not_reused_from_mysql(self, get_latest_token, refresh) -> None:
        """上游已拒绝的 access_token 即使记录未到期也必须走刷新。"""
        auth._persist_token({"access_token": "rejected", "expires_in": 3600}, auth.now())
        get_latest_token.return_value = {
            "access_token": "rejected", "create_time": auth.now(), "expires_in": 3600,
        }

        self.assertTrue(auth.ensure_token(stale_access_token="rejected"))
        refresh.assert_called_once()

    @patch("core.auth.refresh_token")
    @patch("core.auth.get_latest_token")
    def test_missing_expiry_falls_back_to_refresh(self, get_latest_token, refresh) -> None:
        """缺少到期信息时不把 access_token 视为永久有效。"""
        get_latest_token.return_value = {"access_token": "unknown-expiry"}

        self.assertTrue(auth.ensure_token())
        refresh.assert_called_once()


if __name__ == "__main__":
    unittest.main()
