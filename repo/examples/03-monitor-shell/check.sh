#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 老夫 <2379731846@qq.com>
#
# 示例 3 · 每天跑一次，只记两件事：还活着吗，账本有没有被悄悄换过。
#
# 用法：
#   ./check.sh                      # 跑一次，输出一行
#   STATE=/var/lib/dc/state.tsv ./check.sh
#
# 退出码：0 正常（含"有新条目"）／1 异常（链坏、锚值回退）／2 取不到数
#
# 为什么"取不到"要单独一个退出码：监控里把超时当成功，是最常见的一种假装。
# 0 和 2 分开，你的告警规则才写得出"连续两次 2 才叫人"这种话。

set -eu

BASE="${BASE:-https://drawcommons.org}"
STATE="${STATE:-$(dirname "$0")/state.tsv}"
BASE="${BASE%/}"

now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
die2() { echo "$now  UNREACHABLE  $1" >&2; exit 2; }
short() { printf '%s' "$1" | cut -c1-16; }

# ---- 1. 取数：三条命令，任何一条失败都按"取不到"处理，不降级为"通过"
verify_json=$(curl -fsS --max-time 20 "$BASE/api/ledger/verify" 2>/dev/null) \
  || die2 "GET /api/ledger/verify"
items_json=$(curl -fsS --max-time 20 "$BASE/api/ledger/items" 2>/dev/null) \
  || die2 "GET /api/ledger/items"

# 导出件必须先落文件再算哈希。写成 `curl … | sha256sum` 看着更短，
# 但管道的退出码取自 sha256sum：curl 失败了，sha256sum 仍会把**空输入**的
# 哈希算出来交给你——于是"取不到"变成"一个值不对的锚值"，监控成了装样子。
tmp=$(mktemp)
# `|| true` 不是凑数：EXIT trap 的**最后一条命令**的状态会成为进程退出码，
# 清理失败会把「账本正常」变成「检查失败」。清理是清理，判据是判据，两者不能串。
trap 'rm -f "$tmp" 2>/dev/null || true' EXIT
curl -fsS --max-time 20 "$BASE/api/ledger/export" -o "$tmp" 2>/dev/null \
  || die2 "GET /api/ledger/export"
# `tr -d '\\'` 不是多此一举：coreutils 的 sha256sum 在二进制模式下会输出
# `\HASH *FILE`，那个前导反斜杠会被 cut 当成字段内容带进来，之后拿它去 grep
# 就变成一个非法正则（`\c`），状态文件被写成一堆认不出来的行。
export_sha=$(sha256sum "$tmp" | cut -d' ' -f1 | tr -d '\\')

# ---- 2. 解析：JSON 是 indent=2 的固定输出，grep 足够；不引入 jq 依赖
ok=$(printf '%s' "$verify_json" | grep -o '"ok": *[a-z]*' | head -1 | sed 's/.*: *//')
first_bad=$(printf '%s' "$verify_json" | grep -o '"first_bad": *[0-9a-z]*' | head -1 | sed 's/.*: *//')
count=$(printf '%s' "$items_json" | grep -o '"count": *[0-9]*' | head -1 | sed 's/.*: *//')

[ -n "$ok" ] || die2 "verify 返回体里没有 ok 字段（接口变了？）"
[ -n "$count" ] || die2 "items 返回体里没有 count 字段（接口变了？）"

# ---- 3. 判据一：服务自己说链没坏
if [ "$ok" != "true" ]; then
  echo "$now  CHAIN_BROKEN  first_bad=$first_bad  count=$count  anchor=$export_sha"
  exit 1
fi

# ---- 4. 判据二：锚值不能回退
# 账本只追加，所以锚值序列的合法形态是「一直出现新的」。
# 若当前锚值在历史里出现过、却不是最后一行，说明链被换回了一个旧状态——
# 那是改写（或分叉），不是追加。只比"变没变"会漏掉这种情况。
mkdir -p "$(dirname "$STATE")"
touch "$STATE"
if grep -q "^$export_sha" "$STATE" 2>/dev/null; then
  last=$(tail -n 1 "$STATE" | cut -f1)
  if [ "$export_sha" != "$last" ]; then
    echo "$now  ANCHOR_ROLLBACK  anchor=$export_sha  count=$count  上一次=$last"
    exit 1
  fi
  echo "$now  OK  count=$count  anchor=$(short "$export_sha")…  (未变化)"
  exit 0
fi

printf '%s\t%s\t%s\n' "$export_sha" "$count" "$now" >> "$STATE"
echo "$now  OK  count=$count  anchor=$(short "$export_sha")…  (新)"
exit 0
