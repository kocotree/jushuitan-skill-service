"""过滤健康检查的常规访问日志。"""

from gunicorn.glogging import Logger


class HealthFilteredLogger(Logger):
    """保留业务访问日志及独立错误日志。"""

    def access(self, resp, req, environ, request_time):
        """功能说明：跳过健康检查路径的访问记录，其他请求使用默认格式。

        参数：resp：响应对象；req：解析后的请求；environ：WSGI 环境；
        request_time：请求处理耗时。
        返回值：父类日志方法的返回值，健康检查返回 None。
        """
        if req.path == "/health":
            return None
        return super().access(resp, req, environ, request_time)
