# 第三方许可正文的来源

本目录的三份文本是**许可正文**，不是我方说明。说明在上一级 `LICENSE-CC-*.md` 里；两者分开，是为了让法律文本可以逐字节校验，
而不被说明文字稀释。

取件日期：2026-11-12　通道：项目服务器（本机到 raw.githubusercontent.com 的 TLS 被拦）

| 文件 | SPDX | 正文字节 | 正文 SHA-256 | 权威版本 |
|---|---|---|---|---|
| `CC-BY-4.0.txt` | CC-BY-4.0 | 17,023 | `d557539df68e771cc1eedcc91d13f70fca930e508d11eedcafa4b15db49e3744` | https://creativecommons.org/licenses/by/4.0/legalcode |
| `CC-BY-SA-4.0.txt` | CC-BY-SA-4.0 | 18,375 | `cde7883b9050a1104f4ac19a1572aafd6e5d7323b68351aaf51fbf4beba54966` | https://creativecommons.org/licenses/by-sa/4.0/legalcode |
| `CC0-1.0.txt` | CC0-1.0 | 7,048 | `a2010f343487d3f7618affe54f789f5487602331c0a8d03f49e9a7c547cf0499` | https://creativecommons.org/publicdomain/zero/1.0/legalcode |

## 为什么用 SPDX 的副本而不是直接抓官网

官网 `legalcode` 是 HTML，抓下来要经过剥标签才能成为纯文本——那一步会
引入转换误差，而误差恰恰是本项目最不能容忍的东西。SPDX License List Data
是 Linux 基金会维护的许可登记处，其 `text/` 目录就是官方许可的纯文本副本，
取回即可用，且能算出一个稳定的 SHA-256。

两者的差别只在标点（`--` → `–`、直引号 → 弯引号），条款文字一致。
**有疑义时以各文件头部所列的官方 URL 为准**——CC 自己也只认网页上的 legalcode。

## 怎么重取

```sh
# 在一台能直连外网的机器上（本项目用部署服务器）
for k in CC-BY-4.0 CC-BY-SA-4.0 CC0-1.0; do
  curl -sSL -o "/tmp/cctxt/$k.txt" \
    "https://raw.githubusercontent.com/spdx/license-list-data/main/text/$k.txt"
done

# 取回本地后装配（会重算正文 SHA-256 并重写头部）
python _ops/build_license_texts.py --src /tmp/cctxt --out repo/licenses
```
