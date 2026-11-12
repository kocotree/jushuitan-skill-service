from __future__ import annotations

import unittest
from unittest.mock import patch

from core.client import JushuitanClient


class ClientAuthTestCase(unittest.TestCase):
    """验证业务请求按数据库 access_token、刷新接口的顺序恢复鉴权。"""

    @patch("core.client.require_credentials", return_value=("key", "secret"))
    @patch("core.client.refresh_token")
    @patch("core.client.ensure_token", side_effect=[False, False])
    @patch("core.client.get_access_token", side_effect=["old", "database-new", "refreshed"])
    @patch.object(JushuitanClient, "_call_once")
    def test_database_candidate_rejected_then_refreshes(self, call_once, get_access, ensure, refresh, credentials):
        """数据库候选也失效后才刷新，并使用新 token 重试一次。"""
        invalid = {"code": 100, "msg": "access_token无效或已过期"}
        call_once.side_effect = [invalid, invalid, {"code": 0}]
        self.assertEqual(JushuitanClient().call("/test")["code"], 0)

        ensure.assert_called_with(timeout=30, stale_access_token="old")
        refresh.assert_called_once_with(timeout=30, stale_access_token="database-new")
        self.assertEqual([call.kwargs["access_token"] for call in call_once.call_args_list],
                         ["old", "database-new", "refreshed"])

    @patch("core.client.require_credentials", return_value=("key", "secret"))
    @patch("core.client.refresh_token")
    @patch("core.client.ensure_token", side_effect=[False, True])
    @patch("core.client.get_access_token", side_effect=["old", "refreshed"])
    @patch.object(JushuitanClient, "_call_once")
    def test_refresh_is_attempted_only_once(self, call_once, get_access, ensure, refresh, credentials):
        """读库阶段已触发刷新后，不重复刷新被拒绝的新 token。"""
        invalid = {"code": 100, "msg": "access_token已过期"}
        call_once.return_value = invalid

        self.assertEqual(JushuitanClient().call("/test"), invalid)

        self.assertEqual(call_once.call_count, 2)
        refresh.assert_not_called()

    @patch("core.client.require_credentials", return_value=("key", "secret"))
    @patch("core.client.refresh_token")
    @patch("core.client.ensure_token", side_effect=[False, False])
    @patch("core.client.get_access_token", side_effect=["old", "database-new"])
    @patch.object(JushuitanClient, "_call_once")
    def test_database_candidate_works_without_refresh(self, call_once, get_access, ensure, refresh, credentials):
        """数据库 access_token 可用时恢复查询，不调用刷新接口。"""
        call_once.side_effect = [{"code": 100, "msg": "access_token已过期"}, {"code": 0}]

        self.assertEqual(JushuitanClient().call("/test")["code"], 0)

        self.assertEqual(call_once.call_count, 2)
        refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
