bind = "0.0.0.0:5011"

workers = 1
worker_class = "core.http_worker.DeadlineThreadWorker"
threads = 8

timeout = 420
graceful_timeout = 30
keepalive = 5

max_requests = 500
max_requests_jitter = 50

accesslog = "-"
errorlog = "-"
loglevel = "info"
capture_output = True
