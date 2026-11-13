# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 老夫 <2379731846@qq.com>
#
# 这个镜像只有一个用途：让目录站（Glama）能把它构建起来、跑起来、问清三个 tool。
# 不装依赖、不联网构建、不写任何东西。
#
# 构建上下文必须是**仓库根**（不是 examples 目录）：
#
#     docker build -t drawcommons-ledger-mcp .
#     printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}' \
#       '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
#       '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
#       | docker run --rm -i drawcommons-ledger-mcp
#
# 为什么放在根上而不是 examples 里：Glama 只认仓库根的 Dockerfile，并且拿根当构建上下文。
# 代码在 repo/ 下，所以这里多一层 COPY —— 代价写在明处，好过让人找不到入口。
FROM python:3.12-alpine

LABEL org.opencontainers.image.title="drawcommons-ledger-mcp"
LABEL org.opencontainers.image.description="Read-only MCP server for a public audit ledger: entries, local hash-chain recheck, anchor."
LABEL org.opencontainers.image.licenses="Apache-2.0"
LABEL org.opencontainers.image.source="https://github.com/leigui-888/drawcommons"
LABEL org.opencontainers.image.url="https://drawcommons.org"

# stdout 是协议通道：不缓冲、不写 .pyc、固定 UTF-8，避免任何一行杂讯混进 JSON-RPC。
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

WORKDIR /app
COPY repo/examples/04-mcp-server/server.py /app/server.py

# 非 root：这个 server 全程只读，没有任何理由给它 root。
RUN adduser -D -H -u 10001 mcp
USER 10001

# 连哪个站点在启动时定死；tool 参数里没有改地址的选项，容器里也只能改这一处。
ENV LEDGER_BASE=https://drawcommons.org

# -u 是关键：不加缓冲，客户端才等得到回应。
ENTRYPOINT ["python", "-u", "/app/server.py"]
