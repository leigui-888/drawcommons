# app/data/

镜像构建时 `Dockerfile` 的 `COPY data/ ./data/` 会把本目录复制到容器 `/srv/data/`。

**这里不放 `ledger.db`。** 样例库**不在仓库工作树里**——`evidence/ledger_w4.db` 被
`.gitignore` 排除，它是 `build_ledger.py` 的确定性产物。
需要镜像自含数据或本机直接跑服务时，先重建再复制：

```bash
python3 evidence/build_ledger.py            # 生成 evidence/ledger_w4.db（4 条、假 ID，sha256 31445fa5…）
cp evidence/ledger_w4.db deploy/app/data/ledger.db
```

理由与线上挂载口径见 `../README.md` 第 2 节：第二份库会让"线上锚值该信哪个"失去唯一答案。
