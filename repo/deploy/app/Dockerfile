# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 老夫 <2379731846@qq.com>
# 纯标准库应用：无 pip 依赖，构建秒级，内存占用 ~20MB
FROM python:3.12-slim
WORKDIR /srv
COPY ledger_hash.py app.py ./
COPY data/ ./data/
ENV PORT=8000
EXPOSE 8000
# 容器内也只读运行（非 root）。
# uid/gid 固定为 999：宿主 ./app/visits 目录要 chown 成同一个 uid 才写得进。
# 不固定的话，基础镜像或 useradd 的策略一变，写权限会静默失效——现象是
# 「访问计数一直不显示」，而容器 healthy、日志里只有一句 visits 不可用。
# /srv/visits 预建在这里，一是让 bind mount 落在一个已存在且归属正确的目录上，
# 二是本地裸跑（不挂卷）时也能写。
RUN groupadd -g 999 appuser \
 && useradd -r -u 999 -g appuser -s /usr/sbin/nologin appuser \
 && mkdir -p /srv/visits \
 && chown -R appuser:appuser /srv
USER appuser
CMD ["python", "app.py"]
