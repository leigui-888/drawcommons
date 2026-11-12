# 众汲之井 · drawcommons

**这是公开可读副本；发布口在 [drawcommons.org](https://drawcommons.org)。此处打 tag 不等于发版。**

每一版的正式发布以 `drawcommons.org` 上带签名的 tag 与发布包为准：镜像站的 tag 被平台规则
保护，但规则可以由账号持有者关闭；自建裸仓的 `hooks/update` 与 `receive.denyNonFastForwards`
才是不可改写承诺的落点。要核验某一版，认发布口，不认这里。

## 这是什么

一个公共品化的记账与公示项目：账本字节锚定、判据机器可查、许可逐文件归属。
具体从哪里读起：

| 想了解 | 看 |
| --- | --- |
| 项目当前版本与状态 | [`VERSION.md`](VERSION.md)、[`version.json`](version.json) |
| 谁做了这个站（名录，逐版快照） | [`repo/CREDITS.md`](repo/CREDITS.md)、[`repo/credits.json`](repo/credits.json) |
| 自己动手验证，不用信任何人 | [`REPRODUCE.md`](REPRODUCE.md)——三条判据，无需联网与凭据 |
| 这套账本怎么部署 | [`repo/deploy/README.md`](repo/deploy/README.md) |
| 代码与数据的许可条件 | [`repo/README.md`](repo/README.md) |
| 版本间改了什么 | [`CHANGELOG.md`](CHANGELOG.md) |

## 验证 tag 签名

`v2.1-rc5` 起的 tag 带有 SSH 签名。克隆后直接 `git tag -v` 会报
`allowedSignersFile needs to be configured`——这不是签名有问题，是你还没指定信任文件。
信任文件就在仓库里，指定它即可：

```bash
# 仓库是公开的，https 即可匿名克隆，不需要 GitHub 账号或公钥
git clone https://github.com/leigui-888/drawcommons.git
cd drawcommons
git -c gpg.ssh.allowedSignersFile=repo/allowed_signers verify-tag v2.1-rc10
```

看到 `Good "git" signature for 2379731846@qq.com` 即通过。信任根说明（域名侧 DNS TXT、
指纹）见 `repo/CREDITS.md` §10。

## 不可改写

已存在的 tag 不删除、不移动；历史提交不改写。这在自建裸仓由服务端钩子强制执行，在本站
由 GitHub ruleset（`Restrict deletions` + `Restrict updates`，2026-11-12 实测拦截删/移）近似
执行。发现任何一个镜像站的 tag 与发布口不一致，以发布口为准，并请视为事故。

## 状态

代码可用、基线可复现；**协议三件套未齐（免责声明与隐私政策未合并），`protocol_ready=false`，
不得对外发布服务**。详见 `VERSION.md`。
