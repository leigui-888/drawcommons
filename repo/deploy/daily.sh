#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 老夫 <2379731846@qq.com>
# 每日备份：账本库（唯一不可重建的资产）+ 全部配置。
#
# 2026-11-11 修复：原版只 tar 了 /etc/caddy、Caddyfile、compose.yml，
# 账本库从未进过任何一次备份。配置丢了能重写，账本链丢了永久不可恢复
# （锚值只能证明「曾经有某物」，内容找不回来）。
#
# 设计取舍：
#   - app 以 mode=ro 打开数据库、不产生写事务，因此直接 cp 是安全的；
#   - 备份完必须与源文件比哈希，不一致就失败退出（原版用 || true 吞错，
#     导致「目录有、文件有、但其实没备到东西」这种最危险的状态）；
#   - 失败同时写 syslog，cron 的邮件丢了也能 journalctl 查到。

set -euo pipefail

APP=/opt/drawcommons
STAMP=$(date +%F_%H%M)
OUT="$APP/backup/$STAMP"
LOG="$APP/backup/backup.log"
DB="$APP/app/data/ledger.db"

log()  { printf '%s %s\n' "$(date +'%F %T')" "$*" | tee -a "$LOG" >&2; }
fail() { log "FAIL $*"; logger -t ledger-backup "FAIL $*" 2>/dev/null || true; exit 1; }

mkdir -p "$OUT"

# 1) 账本库及其 WAL/SHM（若有）
[ -f "$DB" ] || fail "ledger.db 不存在：$DB"
cp -a "$DB" "$OUT/ledger.db"
for ext in -wal -shm; do
    if [ -f "$DB$ext" ]; then cp -a "$DB$ext" "$OUT/ledger.db$ext"; fi
done

# 2) 配置
tar -czf "$OUT/etc.tgz" /etc/caddy "$APP/Caddyfile" "$APP/compose.yml" 2>/dev/null || true
ETC_SIZE=$(stat -c%s "$OUT/etc.tgz" 2>/dev/null || echo 0)

# 3) 完整性：备份件与源文件哈希必须一致
SRC=$(sha256sum "$DB" | cut -d' ' -f1)
BAK=$(sha256sum "$OUT/ledger.db" | cut -d' ' -f1)
[ "$SRC" = "$BAK" ] || fail "账本库哈希不一致 src=${SRC:0:16} bak=${BAK:0:16}"

# 4) 可读性：用容器里的 python 数一遍条目，证明库没坏
#    容器内工作目录是 /srv（见 Dockerfile），库在 /srv/data/ledger.db
COUNT=$(sudo docker exec ledger-app python -c "
import sqlite3
c = sqlite3.connect('file:/srv/data/ledger.db?mode=ro', uri=True)
print(sum(c.execute('select count(*) from ' + t).fetchone()[0]
          for t in ('ledger_give','ledger_receive','ledger_payback')))
" 2>/dev/null) || COUNT="unknown"

SIZE=$(stat -c%s "$OUT/ledger.db")
log "OK $STAMP ledger.db=${SIZE}B sha256=${BAK:0:16} entries=$COUNT etc.tgz=${ETC_SIZE}B"

# 5) 保留 14 天
find "$APP/backup" -maxdepth 1 -type d -name '20*' -mtime +14 -exec rm -rf {} +
