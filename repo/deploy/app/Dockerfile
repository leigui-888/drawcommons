# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 众汲之井 2.1 贡献者
# 纯标准库应用：无 pip 依赖，构建秒级，内存占用 ~20MB
FROM python:3.12-slim
WORKDIR /srv
COPY ledger_hash.py app.py ./
COPY data/ ./data/
ENV PORT=8000
EXPOSE 8000
# 容器内也只读运行（非 root）
RUN useradd -r -s /usr/sbin/nologin appuser && chown -R appuser:appuser /srv
USER appuser
CMD ["python", "app.py"]
