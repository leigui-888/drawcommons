# deploy · 公开账本服务

本目录是 `https://drawcommons.org` 那套只读账本服务的**完整部署源**：服务器上的每一个运行件都能在这里找到，且与线上逐字节相同。目的是让"线上跑的是什么"可被外部审计，而不是只有运维脑子和一台机器。

## 1. 目录 ↔ 服务器

服务器根目录 `/opt/drawcommons/`，一一对应：

| 本仓库 | 服务器 | 说明 |
| --- | --- | --- |
| `app/` | `app/` | Docker build context，**两个镜像共用**：只读服务（`Dockerfile` + `app.py`）与写入面（`Dockerfile.ingest` + `ingest.py` / `signing.py`）。共用件：`ledger_store.py`、`ledger_hash.py`、`legal.py`、`agent.md`、`data/` |
| `compose.yml` | `compose.yml` | 三个服务：`caddy`（对外 80/443）+ `app`（内网 8000，只读）+ `ingest`（内网 8001，挂 `/api/v1/*` 的**写**口）。`GET /api/v1/requests` 是读，归 `app`，见 §2.3 |
| `Caddyfile` | `Caddyfile` | TLS 自动签发、反代、响应头加固、访问日志 |
| `daily.sh` | `backup/daily.sh` | 每日备份（root 属主，`cron` 调用） |
| —（不入库） | `app/visits/` | 访问计数库所在目录，须 `chown 999:999`，见 §2.1 |
| —（不入库） | `app/data/` | 账本库所在目录。**app 只读挂入、ingest 读写挂入**，须 `chown 999:999`，见 §2.2 |

**不要**在本目录直接 `docker compose up`：`compose.yml` 里的 `./app/data` 按服务器路径书写，在本地解包后不成立。部署按第 3 节。


## 2. 为什么 `data/` 里没有 `ledger.db`

样例库**不在仓库工作树里**：`../evidence/ledger_w4.db` 被 `.gitignore` 排除，因为它是 `build_ledger.py` 的确定性产物——跑一次 `python3 evidence/build_ledger.py` 即得（4 条、假 ID，sha256 `7dc2d787…`）。把它提交进来、或复制进 `app/data/`，都会得到第二份"看起来更权威"的库；两处一旦不一致，就没人说得清线上锚值该信哪个——2026-11-11 修的 P0 正是这类分叉。

所以：

- **线上不需要**：`compose.yml` 把宿主 `app/data/` 只读挂到容器 `/srv/data`，镜像里的副本被遮蔽。
- **镜像要自含数据时**（外部审计者想 `docker run` 就起）：先 `cp ../evidence/ledger_w4.db app/data/ledger.db` 再 build。
- **本机直接跑**（只装 Python）：同样把上面那条 `cp` 做完，再 `cd app && python3 app.py`。

缺库时服务不会假装正常：页面仍返回 200，`/api/*` 返回 `503 data_layer_unavailable`，启动横幅打印 `⚠ 未挂载数据卷` 或 `数据层不可用`。

## 2.1 `app/visits/`：访问计数的卷（2026-11-12 新增）

首页底部那一行访问计数需要一个可写位置，而它不该跟账本睡在同一个文件里——计数坏了、丢了、被人清了，账本字节与锚值必须一个字符都不受影响。所以单开一个目录：

```bash
ssh deploy@<IP> 'sudo mkdir -p /opt/drawcommons/app/visits \
  && sudo chown 999:999 /opt/drawcommons/app/visits \
  && sudo chmod 750 /opt/drawcommons/app/visits'
```

- **uid 必须是 999**：容器内 `appuser` 固定为 `999:999`（`Dockerfile` 里写死，不靠 `useradd -r` 碰运气）。目录属主不对的话，写入静默失败——现象是「首页没有计数」，容器却 healthy。
- **与账本分开**：计数落 `visits.db`，不参与建链，也不在任何哈希里。它坏了、丢了、被人清了，账本字节与锚值一个字符都不受影响。
- **只数首页**：表是 `home_visits(day, n)`，只有 `GET /` 落行，子页与接口都不记；页面上只有一行「已有 N 名访问者」。没有 IP、UA、来源页、会话标识，因此无法去重——这个 N 是首页被打开的累计次数，不是独立访客数。
- 备份脚本要带上这个目录，否则重建机器后计数从零开始（不影响账本）。


## 2.2 `app/data/`：写入面挂载（2026-11-14 新增，第 03 步）

r6 起账本可写，但**不是让公开页变成可写**：同一个目录挂两次，权限不同。

| 容器 | 挂载 | 谁能写 |
| --- | --- | --- |
| `app`（公开页 / 三个只读接口） | `./app/data:/srv/data:ro` | 谁都不能——内核层面只读 |
| `ingest`（`/api/v1/*` 四条 POST） | `./app/data:/srv/data:rw` | 只有它 |

这条区分不是洁癖。公开页的进程若也能写，那么「一个只画页面的进程」就同时持有账本的写权限，
攻击面按写入面计算；分开之后，公开页被拿下的后果仍然只是「页面被改」，不是「账本被改」。

**部署前必须做一次（宿主）**：

```bash
ssh deploy@<IP> 'sudo chown 999:999 /opt/drawcommons/app/data/ledger.db \
  && sudo chown 999:999 /opt/drawcommons/app/data'
```

- uid 固定 `999`，与两个镜像里的用户同一个数字。属主不对时 `ingest` 启动即拒绝：
  它在 preflight 里用 `BEGIN IMMEDIATE` 真拿一次写锁，拿不到就打印
  「账本库不可写……卷是否以 rw 挂入？宿主目录是否 chown 999:999？」并退出。
  **宁可起不来，也不要起来之后每条写入都 500。**
- 目录本身也要可写：SQLite 回滚日志（`ledger.db-journal`）建在库文件旁边。
- 备份脚本照旧备 `app/data/`，不需要为写入面另加路径。

写入面的对外契约（端点、签名载荷、错误码）见 `../spec/ingest.md`；本机自测：

```bash
python3 app/selftest.py        # 99 项；只需要 ssh-keygen 与仓库里的 evidence/
                              # 含第 04 步确认层：受方确认 200 / 给方自签 422 /
                              # 重复确认 409 / 自造 hash·换域·payload 不符各 400
                              # 含第 05 步入账转换：一次交付恰好 +2 条 / 重发幂等 /
                              # 换凭据 422 / 自己给自己交付整体回滚 / 确认后自动关单
```


## 2.3 `agent.md` 与发现口（2026-11-14 新增，与 03–05 并行）

两件事，都是让已经建好的东西**能被找到**，不增加任何协议能力。

**`app/agent.md` → `https://drawcommons.org/agent.md`**，是给 agent 的接入说明：
十分钟可跑脚本、能力矩阵、心跳约定、两条「必须问过人」的闸门。它由 `COPY` 进镜像，
代码里不拼第二份——拼一份就等于多了一份会单独过期的说明。

**`GET /api/v1/requests` 是需求单的发现口，落在 `app` 而不是 `ingest`。** 它只读、
不验签，读的是需求单而不是账目。放进写入面代码上没区别，但「ingest 只做写」这条
口径会变模糊，而它是「公开页物理上不能写」的另一半。Caddy 里 `/api/v1/requests*`
比 `/api/v1/*` 更具体，所以排在前面；`/api/v1/request`（单数，写口）不受影响。

部署后核对三条，第二条与第三条一起看才有意义：

```bash
curl -sS https://drawcommons.org/agent.md | head -3        # 应当是这份文件的开头
curl -sS 'https://drawcommons.org/api/v1/requests?limit=1' # 200 + JSON
curl -sS -X POST https://drawcommons.org/api/v1/requests   # 501，不能是 200
```

**入口分流（2026-11-15）**：`/` 与 `/en` 不再是主页——它们 302 去 `/welcome` /
`/en/welcome`（三屏纯图片的前置引导，独立文档，与站点 CSS 零共享）；主页本体在
`/home` 与 `/en/home`，引导第三击与每屏底部按钮都导航到 `/home`。没有 cookie：
**每次进入都引导**（用户裁定），隐私政策 3.12「不使用 Cookie」原样成立。
验证：`curl -sI https://drawcommons.org/ | grep -i '^location'` 应为 `/welcome`，
且是 302 不是 301（产品决策不是地址变更，301 会被长期缓存）。

第三条是防「读口被配到写入面」或者反过来：读口只有 `do_GET`，一旦它开始收 POST，
说明 Caddy 的精确路由没生效，`/api/v1/*` 把它吞给 ingest 了。

### 2.4 需求两页（2026-11-14，与 05 并行；2026-11-15 改名）

`/requests`（需求发布，原 `/needs`「还缺什么」）与 `/r/<id>`（单页）都在 `app`，
读同一个库、不经过内存链。英文页 `/en/requests` 与中文由**同一个函数**渲染（只换文案）：


- 列表与读口调**同一个函数**（`ledger_store.load_request_page`），口径不会分叉；
  带查询参数，所以不进 `PAGES` 那张零参路由表，坏 `state` 回 400 页面。
- 旧路径 `/needs`、`/en/needs` 301 到新页，**查询串原样带走**（`?state=` 是筛选，
  丢了会静默变回全量——屏幕上看起来像「筛选生效了」，比 404 更像谎话）。
- 单页读 `request` 全表——它承诺**永久可读**，不受 90 天收窄；那一对账目的 hash 由
  `build_chain` 重算，与 `/api/ledger/items` 同一个数。
- 部署后核对三条：

```bash
curl -sS https://drawcommons.org/requests | grep -c reqcard   # 有单子时 ≥ 1；空库时 0 也正常
curl -sS https://drawcommons.org/en/requests | grep -c reqcard  # 中英同一份数据，张数应一致
curl -sS -o /dev/null -w '%{http_code}\n' https://drawcommons.org/r/rq_nosuch0001   # 404
curl -sS -o /dev/null -w '%{http_code}\n' 'https://drawcommons.org/requests?state=bogus'  # 400
curl -sSI 'https://drawcommons.org/needs?state=open' | grep -i '^location'   # 301 且带 ?state=open
```

## 2.5 旧库升级（v1.3 → v1.4，2026-11-14）

已经有 `ledger.db` 的部署，升级时**只跑一个增量脚本**，不要重建库：

```bash
# 顺序：先 v1.3 基线（新机器才需要），再 v1.4 增量
sqlite3 ledger.db < spec/ddl_w4.sql      # 只有 v1.2 及更早需要
sqlite3 ledger.db < spec/ddl_v1.4.sql
```

三条要知道的：

1. **全部是 `ALTER TABLE ... ADD COLUMN` 与 `CREATE`，没有一条 `UPDATE`/`DELETE`**，
   所以既有行的既有字段值一个字符都不会变（`spec/ddl_v1.4.sql` 头部有完整说明）。
2. **但条目 hash 会变**：读面是 `SELECT *`，新增的列以 `NULL` 出现在条目里，
   而条目 hash 覆盖它的全部字段。这是「条目 = 它此刻的全部字段」这条既有规则的必然结果。
   于是**锚值也变**——换锚值不是事故，是这次升级的预期结果；把新值公告出去。
3. **自己包一个事务**。`sqlite3 <file` 每条语句自动提交，中途失败会留下「加了一半列」的库，
   而 `ADD COLUMN` 重跑会撞 `duplicate column name`。想避免就用 Python 逐句执行并包在
   `BEGIN IMMEDIATE` … `COMMIT` 里（`sqlite3.executescript()` **不做**这件事）。

升级后自检：`/api/ledger/verify` 应返回 `ok:true`、`first_bad:null`，条目数与升级前相同。

## 3. 部署（改一个文件也要走完）

```bash
# ① 先备份 compose.yml（回滚用）
ssh deploy@<IP> 'cd /opt/drawcommons && cp -a compose.yml compose.yml.bak.$(date +%Y%m%d_%H%M%S)'

# ② 推文件（注意 app.py 进 app/，compose.yml 进父目录）
scp app/app.py           deploy@<IP>:/opt/drawcommons/app/app.py
scp app/ingest.py        deploy@<IP>:/opt/drawcommons/app/ingest.py
scp app/signing.py       deploy@<IP>:/opt/drawcommons/app/signing.py
scp app/ledger_store.py  deploy@<IP>:/opt/drawcommons/app/ledger_store.py
scp app/ledger_hash.py   deploy@<IP>:/opt/drawcommons/app/ledger_hash.py
scp app/Dockerfile       deploy@<IP>:/opt/drawcommons/app/Dockerfile
scp app/Dockerfile.ingest deploy@<IP>:/opt/drawcommons/app/Dockerfile.ingest
scp app/agent.md        deploy@<IP>:/opt/drawcommons/app/agent.md
scp compose.yml         deploy@<IP>:/opt/drawcommons/compose.yml
scp Caddyfile           deploy@<IP>:/opt/drawcommons/Caddyfile
scp daily.sh /tmp/daily.sh && ssh deploy@<IP> \
  'sudo install -o root -g root -m 755 /tmp/daily.sh /opt/drawcommons/backup/daily.sh'

# ③ 校验语法 → 重建 → 重载
ssh deploy@<IP> 'cd /opt/drawcommons && sudo docker compose config -q \
  && sudo docker compose build app ingest && sudo docker compose up -d app ingest \
  && sudo docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile'

# ④ 三查：横幅、挂载、锚值
ssh deploy@<IP> 'sudo docker logs ledger-app 2>&1 | head -3'
curl -s https://drawcommons.org/api/ledger/export | sha256sum
```

第 ④ 步的 sha256 必须等于 `/ledger` 页上印的那个锚值（**以页面为准**，本文件不抄常量——抄一份就多一个会过期的数字）。比值的目的是证明「部署的代码与库，和页面看到的是同一份」；不一致就是数据或代码被动过。**与页面印的不一致就是数据或代码被动过**，先查库，别急着重启。

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
| `https://drawcommons.org/download/allowed_signers` | 验签公钥（OpenSSH 格式） | 钩子从 `HEAD` 摊出，与 `CREDITS.md`、`credits.json` 同一条路径 |
| `https://drawcommons.org/download/CREDITS.md` / `credits.json` | 名录（人读 / 机读） | 同上 |
| `https://drawcommons.org/download/REVIEWS.md` / `reviews.json` | 审查记录（人读 / 机读）：一条提交凭什么算贡献 | 同上 |

维护要点：

- 裸仓由 `compose.yml` 的 `- ./git:/srv/git:ro` 只读挂进 caddy 容器；路由见 `Caddyfile` 的 `/repo.git/*`、`/download/*` 两个 `handle_path`。
- **裸仓 HEAD 必须是 `refs/heads/main`**。`git init --bare` 默认指向 `master`，而本仓推的是 `main`——不设的话 clone 下来会得到 "remote HEAD refers to nonexistent ref, unable to checkout"，看起来像空仓库。设一次即可：`git symbolic-ref HEAD refs/heads/main`。
- 哑协议靠 `info/refs` 与 `objects/info/packs` 两个文件，必须由 `post-receive` 钩子刷新（`git update-server-info`），否则推了新提交而 clone 拿到旧的。
- **出包、刷新 latest、验签闸门已由钩子接管**，不再靠人记得做。钩子源件是本目录的 `git-hooks/`，两个都要装：

  ```bash
  D=/opt/drawcommons/git/drawcommons.git
  for h in post-receive update; do
      install -o deploy -g deploy -m 755 "repo/deploy/git-hooks/$h" "$D/hooks/$h"
  done
  ```

  `post-receive` 做六件事：刷 `update-server-info`；**验签闸门**——为新推的 `v*` tag 验 SSH 签名，验不过就不出包（把 `REFUSED` 打到推送方终端）；为通过的 tag 出包并重算 `.sha256`；把该包复制成 `latest` 别名（校验值独立重算，不复制版本化那份，否则 `sha256sum -c` 会因文件名不符报错）；把 `repo/CREDITS.md`、`repo/credits.json`、`repo/REVIEWS.md`、`repo/reviews.json`、`repo/allowed_signers` 摊到 `/download/`——**这些东西只活在裸仓对象库里时，对浏览器等于不存在**，而署名承诺、审查记录与验签公钥恰恰是给不看 git 的人看的；把 `repo/deploy/app/` 下的 `app.py`、`ingest.py`、`signing.py`、`ledger_store.py`、`ledger_hash.py`、`legal.py`、`agent.md` 与两个 `Dockerfile` 同步进服务器应用目录、`repo/deploy/compose.yml` 同步到部署根目录，**字节真变了**才重建容器（r6 起两个服务一起重建：`ledger_store.py` 是两个镜像共用的，只重建 app 会让写入面继续跑旧模块，而它照样 healthy）（2026-11-12 补这一步：镜像构建时才 `COPY app.py`，钩子原先不碰应用层，于是「仓库里改了页面、线上还是旧代码」可以静默很久——当天首页改完四小时未上线，靠比对字节数才发现；当晚再补 `Dockerfile` 与 `compose.yml`：只推两个 `.py` 的话，改了卷或非 root 的 uid 在线上永远不生效，而日志一切正常）。

  `update` 只做一件事：**拒绝移动已存在的 tag**。新建放行、删除放行、改指向一律拒绝。之所以不能只靠 `receive.denyNonFastForwards`：实测那个配置拦得住分支强推，**拦不住 tag 更新**——`git push -f` 把已有 tag 指到别的提交，服务端会输出 `+ 02a229b...b7dc962 (forced update)` 并接受，因为 git 认为 tag 本就不存在快进关系。而移动 tag 是最隐蔽的改写：`git log` 看不出异常，下载过的包与 tag 脱钩，包本身的 `sha256` 却仍然通过。裸仓另需 `git config receive.denyNonFastForwards true`（拦分支），两条配合才完整。

  验签闸门为什么在钩子里而不是靠人事后查：查的人少、改的人多。它拦的是**手滑**——拿轻量 tag 就推了、换了钥忘了改签名、tag 建在别人的钥上。它拦不住拿到部署钥的人（那人本来就能改任何东西），也不打算拦：那条边界靠密钥管理，不靠钩子。

  名录与公钥从 `HEAD` 取而不从 tag 取：它们是"当下有效"的记录，历史快照留在各自 tag 里，那才是防删改的依据。裸仓 `HEAD` 未必指向 `main`（`git init --bare` 默认 `master`），故钩子里 `HEAD` 取不到就退回 `refs/heads/main`。有 `github` remote 时顺带 `push --mirror`，失败只记 syslog，不影响本地推送。
- 发版顺序：`git tag -a` → `git push publish main --tags` → 钩子自动出包。**tag 与包必须同源**，包过期等于邀请函指向旧代码——现在这件事有机器兜底了。
- 钩子日志：`journalctl -t drawcommons-hook -n 20` 或 `grep drawcommons-hook /var/log/syslog`。
- 用哑协议而非 `git-http-backend`：Caddy 无 CGI。代价是不支持 push/PR，本仓本来也只接受邮件反馈，够用。
- **密钥位置**：若配置 GitHub 镜像需要部署密钥，放 `/opt/drawcommons/keys/`（`deploy` 属主、`700`），**不要放 `git/` 下**——`git/` 整个只读挂进了 caddy 的 `/srv/git`，私钥落在网站目录的父级里。

## 6. 许可

本目录 `Apache-2.0`；`app/data/` 下的数据文件按 `CC-BY-4.0`（见 `../README.md` 的机器可读归属表）。`app/ledger_hash.py` 是 `../src/ledger_hash.py` 的**部署副本**，两者必须逐字节相同，由 `evidence/repo_lint.py` 的 R10 强制。
