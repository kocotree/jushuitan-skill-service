"""为客户端请求收包设置独立期限，保留业务处理的等待时间。"""

import math
import os
import socket
import time

from gunicorn.workers.gthread import ThreadWorker


def _seconds(name, default):
    """读取正数秒数配置，拒绝会关闭保护的无效值。"""
    value = float(os.environ.get(name, default))
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} 必须是有限正数")
    return value


class DeadlineSocket:
    """仅约束入站 recv，向底层套接字透传其余操作。"""

    def __init__(self, sock, logger, client):
        self.sock = sock
        self.logger = logger
        self.client = client
        self.deadline = None
        self.phase = "headers"

    def __getattr__(self, name):
        return getattr(self.sock, name)

    def begin(self, phase, seconds):
        """设置当前收包阶段；零星到达的数据不会延长期限。"""
        self.phase = phase
        self.deadline = time.monotonic() + seconds

    def recv(self, *args, **kwargs):
        """功能说明：在收包剩余期限内读取客户端数据。

        参数：args、kwargs：透传给底层 socket.recv 的缓冲区大小和标志。
        返回值：接收的字节；超过期限时抛出 TimeoutError。
        """
        if self.deadline is None:
            return self.sock.recv(*args, **kwargs)
        remaining = self.deadline - time.monotonic()
        previous = self.sock.gettimeout()
        try:
            if remaining <= 0:
                raise TimeoutError("客户端请求读取期限已到")
            # 兼容 Gunicorn 在清理连接时设置的更短超时。
            self.sock.settimeout(min(previous, remaining) if previous is not None else remaining)
            return self.sock.recv(*args, **kwargs)
        except TimeoutError:
            self.logger.warning("client_read_timeout phase=%s client=%s", self.phase, self.client)
            # 关闭读写方向，使慢连接及时退出，避免再次进入读取流程。
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            raise
        finally:
            self.sock.settimeout(previous)


class DeadlineThreadWorker(ThreadWorker):
    """在 Gunicorn 26 的请求解析与业务处理边界分别设置收包期限。"""

    def init_process(self):
        """功能说明：加载收包配置并启动 worker。参数：无。返回值：无。"""
        self.header_seconds = _seconds("HTTP_HEADER_READ_TIMEOUT", "10")
        self.body_seconds = _seconds("HTTP_BODY_READ_TIMEOUT", "30")
        self.log.info("client_read_limits headers=%ss body=%ss", self.header_seconds, self.body_seconds)
        super().init_process()

    def handle(self, conn):
        """功能说明：为每次请求（含复用连接）设置请求头期限。

        参数：conn：Gunicorn 接受的客户端连接。
        返回值：父类返回的连接复用或延后处理标记。
        """
        if not isinstance(conn.sock, DeadlineSocket):
            conn.sock = DeadlineSocket(conn.sock, self.log, conn.client)
        conn.sock.begin("headers", self.header_seconds)
        return super().handle(conn)

    def handle_request(self, req, conn):
        """功能说明：请求头完整后切换到请求体收包期限。

        参数：req：解析完成的请求头；conn：客户端连接。
        返回值：父类返回的连接复用标记。
        """
        conn.sock.begin("body", self.body_seconds)
        # 期限只在读取客户端套接字时检查，不计时中断上游调用或响应生成。
        try:
            return super().handle_request(req, conn)
        finally:
            # 业务完成后由 Gunicorn 自身的有界清理流程接管剩余数据。
            conn.sock.deadline = None
