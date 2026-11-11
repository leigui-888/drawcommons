# deploy · 公开账本服务

本目录是 `https://drawcommons.org` 那套只读账本服务的**完整部署源**：服务器上的每一个运行件都能在这里找到，且与线上逐字节相同。目的是让"线上跑的是什么"可被外部审计，而不是只有运维脑子和一台机器。

## 1. 目录 ↔ 服务器

服务器根目录 `/opt/drawcommons/`，一一对应：

| 本仓库 | 服务器 | 说明 |
| --- | --- | --- |
| `app/` | `app/` | Docker build context。4 个文件：`Dockerfile`、`app.py`、`ledger_hash.py`、`data/` |
| `compose.yml` | `compose.yml` | 两个服务：`caddy`（对外 80/443）+ `app`（内网 8000） |
| `Caddyfile` | `Caddyfile` | TLS 自动签发、反代、响应头加固、访问日志 |
| `daily.sh` | `backup/daily.sh` | 每日备份（root 属主，`cron` 调用） |

**不要**在本目录直接 `docker compose up`：`compose.yml` 里的 `./app/data` 按服务器路径书写，在本地解包后不成立。部署按第 3 节。

## 2. 为什么 `data/` 里没有 `ledger.db`

样例库**不在仓库工作树里**：`../evidence/ledger_w4.db` 被 `.gitignore` 排除，因为它是 `build_ledger.py` 的确定性产物——跑一次 `python3 evidence/build_ledger.py` 即得（4 条、假 ID，sha256 `31445fa5…`）。把它提交进来、或复制进 `app/data/`，都会得到第二份"看起来更权威"的库；两处一旦不一致，就没人说得清线上锚值该信哪个——2026-11-11 修的 P0 正是这类分叉。

所以：

- **线上不需要**：`compose.yml` 把宿主 `app/data/` 只读挂到容器 `/srv/data`，镜像里的副本被遮蔽。
- **镜像要自含数据时**（外部审计者想 `docker run` 就起）：先 `cp ../evidence/ledger_w4.db app/data/ledger.db` 再 build。
- **本机直接跑**（只装 Python）：同样把上面那条 `cp` 做完，再 `cd app && python3 app.py`。

缺库时服务不会假装正常：页面仍返回 200，`/api/*` 返回 `503 data_layer_unavailable`，启动横幅打印 `⚠ 未挂载数据卷` 或 `数据层不可用`。

## 3. 部署（改一个文件也要走完）

```bash
# ① 先备份 compose.yml（回滚用）
ssh deploy@<IP> 'cd /opt/drawcommons && cp -a compose.yml compose.yml.bak.$(date +%Y%m%d_%H%M%S)'

# ② 推文件（注意 app.py 进 app/，compose.yml 进父目录）
scp app/app.py          deploy@<IP>:/opt/drawcommons/app/app.py
scp app/ledger_hash.py  deploy@<IP>:/opt/drawcommons/app/ledger_hash.py
scp app/Dockerfile      deploy@<IP>:/opt/drawcommons/app/Dockerfile
scp compose.yml         deploy@<IP>:/opt/drawcommons/compose.yml
scp Caddyfile           deploy@<IP>:/opt/drawcommons/Caddyfile
scp daily.sh /tmp/daily.sh && ssh deploy@<IP> \
  'sudo install -o root -g root -m 755 /tmp/daily.sh /opt/drawcommons/backup/daily.sh'

# ③ 校验语法 → 重建 → 重载
ssh deploy@<IP> 'cd /opt/drawcommons && sudo docker compose config -q \
  && sudo docker compose build app && sudo docker compose up -d app \
  && sudo docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile'

# ④ 三查：横幅、挂载、锚值
ssh deploy@<IP> 'sudo docker logs ledger-app 2>&1 | head -3'
curl -s https://drawcommons.org/api/ledger/export | sha256sum
```

第 ④ 步的 sha256 必须等于线上页面锚值 `cdec34e5bb85018a9a0d905307ee2103fa1ee7a9f046290987cc1a801efe30a9`（样例库口径）。**锚值变了就是数据被动过**，先查库，别急着重启。

## 4. 两个必须知道的坑

1. **`app.py` 必须推进 `app/`**。build context 是 `./app`，推到 `/opt/drawcommons/app.py` 会让 `docker compose build` 全程走缓存、容器仍是旧版，而构建输出照样打印 `Built`。判别：看启动横幅，或 `docker exec ledger-app python -c "import app;print(app.Handler.server_version)"`。
2. **横幅要能看见**。2026-11-11 之前三行启动 `print` 没有 `flush=True`，stdout 接管道时是 8KB 块缓冲，`docker logs` 一片空白而容器 healthy——"用横幅核对版本"这招直接失效。现在三行都带 flush，正常应立刻出现，且第二行是 `data source: … (bind mount ✓)`。

## 5. 公开仓库与复现包（2026-11-11 起）

线上同时对外提供**只读**的源码发布通道，供第三方 clone 自行复现（G3 复现邀请的落点）：

| 地址 | 内容 | 实现 |
| --- | --- | --- |
| `https://drawcommons.org/repo.git` | 整包裸仓，`main` 分支 + tag | `/opt/drawcommons/git/drawcommons.git`，Caddy 静态服务（哑协议） |
| `https://drawcommons.org/download/drawcommons-latest.tar.gz` | **稳定别名**，当前 tag 的压缩包 + `.sha256` | 钩子每次出包时同步复制 |
| `https://drawcommons.org/download/drawcommons-<tag>.tar.gz` | 版本化压缩包 + `.sha256`，可长期引用 | `git archive` 生成在 `git/download/` |

维护要点：

- 裸仓由 `compose.yml` 的 `- ./git:/srv/git:ro` 只读挂进 caddy 容器；路由见 `Caddyfile` 的 `/repo.git/*`、`/download/*` 两个 `handle_path`。
- **裸仓 HEAD 必须是 `refs/heads/main`**。`git init --bare` 默认指向 `master`，而本仓推的是 `main`——不设的话 clone 下来会得到 "remote HEAD refers to nonexistent ref, unable to checkout"，看起来像空仓库。设一次即可：`git symbolic-ref HEAD refs/heads/main`。
- 哑协议靠 `info/refs` 与 `objects/info/packs` 两个文件，必须由 `post-receive` 钩子刷新（`git update-server-info`），否则推了新提交而 clone 拿到旧的。
- **出包与刷新 latest 已由钩子接管**，不再靠人记得做。钩子源件是本目录的 `git-hooks/post-receive`，装法：

  ```bash
  sudo install -o deploy -g deploy -m 755 \
      /opt/drawcommons/git/drawcommons.git/hooks/post-receive
  # 源件在仓库 repo/deploy/git-hooks/post-receive，改动后重装即可
  ```

  它做三件事：刷 `update-server-info`；为每个新推的 `v*` tag 出包并重算 `.sha256`；把该包复制成 `latest` 别名（校验值独立重算，不复制版本化那份，否则 `sha256sum -c` 会因文件名不符报错）。有 `github` remote 时顺带 `push --mirror`，失败只记 syslog，不影响本地推送。
- 发版顺序：`git tag -a` → `git push publish main --tags` → 钩子自动出包。**tag 与包必须同源**，包过期等于邀请函指向旧代码——现在这件事有机器兜底了。
- 钩子日志：`journalctl -t drawcommons-hook -n 20` 或 `grep drawcommons-hook /var/log/syslog`。
- 用哑协议而非 `git-http-backend`：Caddy 无 CGI。代价是不支持 push/PR，本仓本来也只接受邮件反馈，够用。
- **密钥位置**：若配置 GitHub 镜像需要部署密钥，放 `/opt/drawcommons/keys/`（`deploy` 属主、`700`），**不要放 `git/` 下**——`git/` 整个只读挂进了 caddy 的 `/srv/git`，私钥落在网站目录的父级里。

## 6. 许可

本目录 `Apache-2.0`；`app/data/` 下的数据文件按 `CC-BY-4.0`（见 `../README.md` 的机器可读归属表）。`app/ledger_hash.py` 是 `../src/ledger_hash.py` 的**部署副本**，两者必须逐字节相同，由 `evidence/repo_lint.py` 的 R10 强制。
