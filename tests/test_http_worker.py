"""通过真实 TCP 连接验证慢客户端隔离和慢业务请求兼容性。"""

import concurrent.futures
import http.client
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest


class HttpWorkerTests(unittest.TestCase):
    """测试实际 Gunicorn worker 的收包边界。"""

    @classmethod
    def setUpClass(cls):
        """启动独立测试服务，使用短收包期限加速回归。"""
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            cls.port = probe.getsockname()[1]
        cls.logs = tempfile.TemporaryFile(mode="w+")
        cls.process = subprocess.Popen(
            [str(Path(sys.executable).parent / "gunicorn"), "-c", "gunicorn.py",
             "--bind", f"127.0.0.1:{cls.port}", "--threads", "8",
             "tests.http_fixture:app"],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "HTTP_HEADER_READ_TIMEOUT": "0.4", "HTTP_BODY_READ_TIMEOUT": "0.8"},
            stdout=cls.logs, stderr=subprocess.STDOUT,
        )
        for _ in range(100):
            try:
                if cls.request("GET", "/health") == (200, b"ok"):
                    return
            except OSError:
                pass
            if cls.process.poll() is not None:
                break
            time.sleep(0.05)
        cls.process.terminate()
        cls.process.wait(timeout=10)
        cls.logs.seek(0)
        raise RuntimeError(cls.logs.read())

    @classmethod
    def tearDownClass(cls):
        """关闭测试进程和日志文件。"""
        cls.process.terminate()
        cls.process.wait(timeout=10)
        cls.logs.close()

    @classmethod
    def request(cls, method, path, body=None):
        """发送测试 HTTP 请求并返回状态码及响应体。"""
        conn = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=4)
        try:
            conn.request(method, path, body=body)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def stalled(self, payload):
        """建立并发送不完整请求；返回供测试关闭的套接字。"""
        conn = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        conn.sendall(payload)
        return conn

    def test_headers_cannot_exhaust_threads(self):
        """八条残缺请求头超时释放后，健康接口应恢复响应。"""
        clients = [self.stalled(b"GET /health HTTP/1.1\r\nHost: test\r\nX:") for _ in range(8)]
        try:
            time.sleep(0.1)
            start = time.monotonic()
            self.assertEqual(self.request("GET", "/health"), (200, b"ok"))
            self.assertLess(time.monotonic() - start, 2)
        finally:
            for client in clients:
                client.close()

    def test_trickle_does_not_extend_deadline(self):
        """持续零星发送请求头不能重置绝对读取期限。"""
        with self.stalled(b"GET /health HTTP/1.1\r\nHost: test\r\nX:") as client:
            for _ in range(6):
                time.sleep(0.12)
                try:
                    client.sendall(b"x")
                except OSError:
                    break
            try:
                self.assertEqual(client.recv(1024), b"")
            except ConnectionResetError:
                pass

    def test_incomplete_bodies_are_released(self):
        """固定长度和分块请求体都不能无限等待。"""
        for framing, body in [(b"Content-Length: 20", b"x"),
                              (b"Transfer-Encoding: chunked", b"14\r\nx")]:
            with self.subTest(framing=framing):
                clients = [self.stalled(b"POST /slow HTTP/1.1\r\nHost: test\r\n" + framing + b"\r\n\r\n" + body) for _ in range(8)]
                try:
                    time.sleep(0.1)
                    start = time.monotonic()
                    self.assertEqual(self.request("GET", "/health"), (200, b"ok"))
                    self.assertLess(time.monotonic() - start, 2.5)
                finally:
                    for client in clients:
                        client.close()

    def test_slow_business_and_keepalive_survive(self):
        """完整请求的慢业务超过收包期限仍返回成功，复用连接仍能使用。"""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=4)
        try:
            for _ in range(2):
                conn.request("POST", "/slow", body=b"complete")
                response = conn.getresponse()
                self.assertEqual((response.status, response.read()), (200, b"complete"))
            conn.request("GET", "/health")
            response = conn.getresponse()
            self.assertEqual((response.status, response.read()), (200, b"ok"))
        finally:
            conn.close()

    def test_slow_business_during_stalled_clients(self):
        """慢上游与恶意慢连接并存时，完整业务请求依然成功。"""
        with concurrent.futures.ThreadPoolExecutor() as executor:
            result = executor.submit(self.request, "POST", "/slow", b"complete")
            clients = [self.stalled(b"GET /health HTTP/1.1\r\nX:") for _ in range(8)]
            try:
                self.assertEqual(result.result(timeout=4), (200, b"complete"))
            finally:
                for client in clients:
                    client.close()


if __name__ == "__main__":
    unittest.main()
