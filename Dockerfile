FROM python:3.14-slim

ENV TZ=Asia/Shanghai

RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ uv
ENV UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev

COPY main.py ./
COPY gunicorn.py ./
COPY core ./core
COPY flows ./flows
COPY kocotree_skills_auth ./kocotree_skills_auth

EXPOSE 5011

CMD ["./.venv/bin/gunicorn", "-c", "gunicorn.py", "main:app"]
