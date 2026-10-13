"""供真实 HTTP 回归测试模拟完整收包后耗时较长的业务处理。"""

import time

from flask import Flask, request

app = Flask(__name__)


@app.route("/health")
def health():
    """返回健康状态。"""
    return "ok"


@app.route("/slow", methods=["POST"])
def slow():
    """功能说明：读取完整请求后模拟慢上游。参数：无。返回值：原请求体。"""
    payload = request.get_data()
    time.sleep(1.5)
    return payload
