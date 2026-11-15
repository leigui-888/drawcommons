# 页面文案（content/）

一页一个文件：`<lang>/<page>.html`。**改文案只改这里**——不用动 `app.py`，
不用重建镜像，也不会重启写库的 `ingest`。`app.py` 按 mtime 热加载，存盘即生效。

## 格式：front-matter + 原样 HTML

```
---
path: /home                 ← 必须与文件名对应（zh/home.html → /home）
lang: zh-CN
title: …                    ← 浏览器标签
desc: …                     ← meta description
hero_title: …               ← 页头大标题（输出时转义）
hero_sub: …                 ← 页头副标题（输出时转义）
ask: …                      ← 可选；首页「在找什么」那行，允许 <b> 与 <a>
---
<正文 HTML，原样>
```

## 三条规矩

1. **站内链接写绝对路径**（`/testing`）。启动时会逐个核对，指向不存在的路由
   直接报错——死链不许上线。外部链接写完整 `https://`。
2. **插槽由程序填**：`__TOPBAR__`、`__STATS__`、`__ANCHOR__`、`__EN_NOTE__`。
   别删、别改名、别往里手写内容；填不上会报错。要加新插槽，得同时改
   `app.py` 的 `_KNOWN_SLOTS` 和对应渲染处。
3. **中英成对**：`zh/` 有的页，`en/` 必须有同名页，缺了启动报错。

CRLF 能读（记事本存的就是），但仓库里请存 LF。

## 生效路径

- **本地**：改文件 → 刷新即见（`CONTENT_DIR` 默认指本目录）。
- **线上**：`git push publish main` → 钩子把 `content/` 同步到
  `/opt/drawcommons/app/content/` → 热加载生效，**不重建镜像、不重启容器**。
  文案文件被删，钩子也会删掉服务器上那份。

> 前提是服务器装的钩子里有 `content` 同步那段。**钩子文件本身不会被推送更新**
> （`post-receive` 只同步 app.py 等代码与 content），改过钩子必须照
> `_ops/D1-服务器部署手册.md` §12.7 手工 `install` 一次；漏装的表现是
> Dockerfile 的 `COPY content/` 构建失败、站点继续跑旧镜像。

## 为什么不放进数据库、也不在服务器上手改

仓库必须是唯一源：文案进了库或只在线上改，这句话就没有版本、没有 diff、
复现包也带不上——与账本「只追加、不可改写」的规矩正好相反。文件在 git 里，
改了什么一眼看得见，回滚是真回滚。

判据：`_ops/w0/content_check.py`（38 项，含反证组）。
