from __future__ import annotations

import json
import time
from typing import Any

import requests

from .auth import LOGGER, ensure_token, get_access_token, mask, preview_text, refresh_token, require_credentials
from .config import BASE_URL
from .sign import generate_sign


class JushuitanClient:
    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        self.app_key, self.app_secret = require_credentials()

    def call(
        self,
        api_path: str,
        biz_params: dict[str, Any] | None = None,
        version: str = "2",
        charset: str = "utf-8",
        refresh_once: bool = True,
    ) -> dict[str, Any]:
        """功能说明：调用业务接口，鉴权失效时优先重读数据库，再尝试刷新令牌。

        参数：
            api_path：业务接口路径。
            biz_params：业务查询参数。
            version：聚水潭接口版本。
            charset：请求字符集。
            refresh_once：是否允许鉴权恢复，最多调用一次刷新流程。
        返回值：
            dict[str, Any]：上游响应或请求异常结果。
        """
        ensure_token(timeout=self.timeout)
        access_token = get_access_token()

        result = self._call_once(
            api_path=api_path,
            biz_params=biz_params,
            access_token=access_token,
            version=version,
            charset=charset,
        )
        refreshed = False
        for attempt in range(2 if refresh_once else 0):
            if not self._is_access_token_expired(result):
                break
            if attempt == 0:
                LOGGER.info("client detected invalid access_token, reloading mysql first")
                refreshed = ensure_token(timeout=self.timeout, stale_access_token=access_token)
            elif refreshed:
                break
            else:
                LOGGER.warning("mysql access_token rejected, falling back to refresh_token")
                refresh_token(timeout=self.timeout, stale_access_token=access_token)
            new_access_token = get_access_token()
            if new_access_token:
                access_token = new_access_token
                result = self._call_once(
                    api_path=api_path,
                    biz_params=biz_params,
                    access_token=new_access_token,
                    version=version,
                    charset=charset,
                )
        return result

    def _call_once(
        self,
        api_path: str,
        biz_params: dict[str, Any] | None,
        access_token: str,
        version: str,
        charset: str,
    ) -> dict[str, Any]:
        url = f"{BASE_URL}{api_path}"
        timestamp = int(time.time())
        params: dict[str, Any] = {
            "app_key": self.app_key,
            "access_token": access_token,
            "timestamp": timestamp,
            "version": version,
            "charset": charset,
            "biz": json.dumps(biz_params or {}, ensure_ascii=False, separators=(",", ":")),
        }
        params["sign"] = generate_sign(self.app_secret, params)

        LOGGER.info(
            "client request api_path=%s access_token=%s biz=%s",
            api_path,
            mask(access_token),
            params["biz"],
        )

        try:
            response = requests.post(
                url,
                data=params,
                headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = response.json()
            LOGGER.info("client response api_path=%s body=%s", api_path, preview_text(json.dumps(result, ensure_ascii=False)))
            return result
        except requests.RequestException as exc:
            LOGGER.exception("client request failed api_path=%s", api_path)
            return {"code": -1, "msg": f"请求异常: {str(exc)}"}
        except json.JSONDecodeError as exc:
            LOGGER.exception("client json decode failed api_path=%s", api_path)
            return {
                "code": -1,
                "msg": f"JSON解析错误: {str(exc)}",
                "raw_response": response.text if "response" in locals() else None,
            }

    @staticmethod
    def _is_access_token_expired(result: dict[str, Any]) -> bool:
        if result.get("code") != 100:
            return False
        message = str(result.get("msg") or "").replace(" ", "")
        return "access_token" in message and ("过期" in message or "无效" in message)
