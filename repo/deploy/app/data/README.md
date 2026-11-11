# app/data/

镜像构建时 `Dockerfile` 的 `COPY data/ ./data/` 会把本目录复制到容器 `/srv/data/`。

**这里不放 `ledger.db`。** 样例库在仓库里只有一份：`evidence/ledger_w4.db`
（4 条、假 ID，sha256 `31445fa5d7a61bea9db1e0ae82b5681e536ba362e0b121286f55b10e87696bd8`）。
需要镜像自含数据或本机直接跑服务时，先执行：

```bash
cp evidence/ledger_w4.db deploy/app/data/ledger.db
```

理由与线上挂载口径见 `../README.md` 第 2 节：第二份库会让"线上锚值该信哪个"失去唯一答案。
