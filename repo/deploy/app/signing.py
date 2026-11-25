# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 老夫 <2379731846@qq.com>
"""写入面的鉴权：请求体自签、SSHSIG 验签。**全仓库唯一一处验签实现。**

四条 POST 共用这一份，而不是各写一份「差不多」的检查。理由不是省代码：三份实现
一开始一定一样，半年后一定不一样，而不一样的第一个后果是「有一条路径能绕过签名」，
且不会有任何测试告诉你——绕过本身就是测试要抓的东西。

**签的是什么。** 不是 JSON 的规范化重排，是**逐字节**：

```
drawcommons-ingest-v1\\n
POST\\n
<路径>\\n
<party_id>\\n
<issued_at>\\n
<nonce>\\n
<请求体原始字节的 sha256（64 位小写十六进制）>\\n
```

为什么签「原始字节的 sha256」而不签「规范化 JSON」：签 JSON 就要双方对同一份对象
算出同样的字节，`json.dumps` 少写一个 `separators` 就差一个空格（第 01 步实测过：
规范化序列化能验过、默认序列化立刻验不过）。请求体是客户端自己发的字节，服务端
收到什么就哈希什么，中间不存在第二套序列化，也就不存在「两边都实现对了才对得上」
这种脆弱约定。

**为什么路径也在载荷里。** 否则一份签给 `/api/v1/party` 的请求体可以被原样送到
`/api/v1/entry`——签名对，语义错，是最难发现的那类重放。

**签名容器用 SSHSIG，namespace = `drawcommons-ingest`。** 与 tag 签名、条目确认
（`drawcommons-confirm`）同一套工具链，不新增依赖。namespace 由容器校验：拿 git
的签名来当写入面凭证会被直接拒绝——域隔离不靠人记得。

**验签用 `ssh-keygen -Y verify`，不自己实现 Ed25519。** 这是本项目唯一的外部进程
依赖，也是刻意的：自己写曲线运算的失败方式是「大多情况下正确」，而这类错误不会
被正常用例发现。用现成工具，失败方式是「验不过」——方向安全。
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import os
import re
import subprocess
import tempfile

# 签名容器里的域。改它等于换协议，旧签名全部作废。
NAMESPACE = "drawcommons-ingest"
# 条目确认用另一个域。**不是一个 namespace 加参数**：写入面签名证明「这个请求是这把钥发的」，
# 确认签名证明「我认可这条已经发生的事」。两件事的语义不同，共用一个域就会出现
# 「把写入面签名挪来当确认」这条路，而它验得过。
CONFIRM_NAMESPACE = "drawcommons-confirm"
CONFIRM_TAG = "drawcommons-confirm-v1"
# 拒收用第三个域（v1.6）。同为「受方说一句话」，但对象不同：确认认可的是**一条账目**，
# 拒收否认的是**一次交付**（需求单的那一行）。共用一个域就会出现「把确认签名挪来当
# 拒收」这条路，而它验得过——两者的载荷结构不同，域必须不同。
REJECT_NAMESPACE = "drawcommons-reject"
REJECT_TAG = "drawcommons-reject-v1"
# 催告用第四个域（v1.7）。同为「认领方说一句话」，但对象不同：催告说的是
# 「这次交付还没被确认」，拒收说的是「这次交付我不认」。前者请对方看一眼，
# 后者否认一次交付——两者都落在同一条 delivered 行上，若共用一个域，
# 把催告签名挪来当拒收会验得过，而单子会因此被记成「被拒绝」。
REMIND_NAMESPACE = "drawcommons-remind"
REMIND_TAG = "drawcommons-remind-v1"
# 载荷第一行的版本标记。与 NAMESPACE 分开：namespace 拦「他域签名」，
# 这一行拦「同域、不同载荷格式」——后者在协议演进时才会出现，而那时旧客户端
# 的签名仍然带着合法的 namespace。
PAYLOAD_TAG = "drawcommons-ingest-v1"

H_PARTY = "X-DG-Party"
H_ISSUED = "X-DG-Issued"
H_NONCE = "X-DG-Nonce"
H_SIG = "X-DG-Sig"

# 时间窗。15 分钟：足够吸收客户端时钟漂移，又短到「抓到一份签名后慢慢重放」不成立
# （真正的重放防线是 nonce 表，这个窗口只是把攻击面收窄）。
WINDOW_SECONDS = 900
# 提前量：客户端时钟快一点是常见的，快 60 秒内照收；再快就是配错时区了。
FUTURE_SKEW = 60

NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{22,64}$")
ISSUED_FMT = "%Y-%m-%dT%H:%M:%SZ"
ED25519_PREFIX = b"\x00\x00\x00\x0bssh-ed25519"


class AuthError(Exception):
    """鉴权失败。`code` 是对外的 DGB_ING_0xx，`detail` 给人看。"""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def parse_pubkey(line: str) -> tuple[str, bytes]:
    """校验并拆开一行 authorized_keys 公钥，返回 (规范化后的单行, 原始 blob)。

    只接受 ed25519：不是「别的算法不安全」，而是**只留一种**。允许两种算法就要
    在两处验签、两处指纹、两处文档里各写一遍，而多出来的那一种没有任何调用方。

    形状检查不靠 `ssh-keygen -l`：ed25519 的公钥 blob 长度恒为 51 字节、前缀恒定，
    这两条在 RFC 8709 里写死，本地判完即可。少一次外部进程，也就少一处可以「看起来
    验过了」的地方。
    """
    if not isinstance(line, str):
        raise AuthError("DGB_ING_008", "pubkey 必须是字符串")
    s = line.strip()
    if "\n" in s or "\r" in s:
        raise AuthError("DGB_ING_008", "pubkey 必须是单行")
    if len(s) > 512:
        raise AuthError("DGB_ING_008", "pubkey 超过 512 字符")
    parts = s.split()
    if len(parts) < 2 or parts[0] != "ssh-ed25519":
        raise AuthError("DGB_ING_008", "只接受 ssh-ed25519 公钥")
    try:
        blob = base64.b64decode(parts[1], validate=True)
    except Exception:
        raise AuthError("DGB_ING_008", "pubkey 的 base64 部分解不开") from None
    if len(blob) != 51 or not blob.startswith(ED25519_PREFIX):
        raise AuthError("DGB_ING_008", "不是合法的 ed25519 公钥（blob 长度或前缀不符）")
    return f"ssh-ed25519 {parts[1]}", blob


def fingerprint(blob: bytes) -> str:
    """OpenSSH 口径的指纹：`SHA256:` + base64(sha256(blob))，去掉填充。

    自己算而不调 `ssh-keygen -lf`：口径在 OpenSSH 里是固定的，自己算的结果与
    `ssh-keygen -lf` 可逐字符比对（selftest 里就比了一次）。
    """
    digest = hashlib.sha256(blob).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def build_payload(method: str, path: str, party: str, issued: str, nonce: str,
                  body: bytes) -> bytes:
    """逐字节载荷。任何一方改动其中的空白、大小写、行序，验签即失败。"""
    digest = hashlib.sha256(body).hexdigest()
    return (f"{PAYLOAD_TAG}\n{method}\n{path}\n{party}\n{issued}\n{nonce}\n{digest}\n"
            ).encode("utf-8")


def confirm_payload(entry_id: str, entry_hash: str) -> bytes:
    """确认层被签的字节。三行，末行带换行，UTF-8。

    **为什么是这三行。**
    - 第一行做域分隔：拿写入面的签名（`drawcommons-ingest`）挪过来会被容器拒；
    - 第二行绑条目：把 A 条目的确认挪到 B 条目，重建出的载荷不同，验不过；
    - 第三行绑字节：条目被换掉 → hash 变 → 重建的载荷不同，验不过。

    少了任何一行，就有一种「挪过去照样验得过」的伪造。三条都不是装饰。

    **签这条载荷的人是谁**：受方。给方自签不叫确认——那不是「两个人各确认了一次」，
    是「一个人说了两遍」。这一条由 DDL 的 `trg_entry_confirm_is_receiver` 硬拦，
    应用层再挡一次只是为了让错误信息早一点出现。
    """
    return f"{CONFIRM_TAG}\n{entry_id}\n{entry_hash}\n".encode("utf-8")


def reject_payload(request_id: str, seq: int) -> bytes:
    """拒收层被签的字节。三行，末行带换行，UTF-8。

    **为什么绑 seq 而不只绑 request_id。** 拒收否认的是**某一次交付**，不是整张单：
    单子将来可能被放回、被重新认领、再交付一次，那时「拒收」指的是哪一次就必须能分开。
    seq 指向被拒的那条 `delivered` 行，行本身不可改（append-only），所以这个指针
    永久有效。只绑 request_id 的话，一次拒收会漂到这张单的所有交付上。

    **为什么不用条目 hash。** 确认层签 hash，是因为条目 hash 是链上算出来的、可复算的
    事实；需求单的状态行没有 hash（`request.md` §1 的诚实边界），签一个不存在的 hash
    才是撒谎。这里签的是「哪张单的哪一行」，服务端按库重算，客户端交的只用于核对。
    """
    return f"{REJECT_TAG}\n{request_id}\n{seq}\n".encode("utf-8")


def remind_payload(request_id: str, seq: int) -> bytes:
    """催告层被签的字节。三行，末行带换行，UTF-8。

    **与拒收同一个形状，但不是同一段字节。** 第一行的 tag 不同（`-remind` 而不是
    `-reject`），容器里的 namespace 也不同。两道分开都保留：tag 拦「同一 namespace
    下换了一种载荷」，namespace 拦「拿另一类签名挪过来」。任何一道单独都不够——
    前者拦不住跨域，后者拦不住同域的载荷演进。

    **绑 seq、不绑时间。** 催告的对象是「这一次交付还没被确认」，seq 指向那条
    delivered 行；把时间签进去，同一个意思在重发时就变成一条新记录，而重发应当
    是幂等的。真实时刻由服务端盖章（`signed_at`），不采信客户端。
    """
    return f"{REMIND_TAG}\n{request_id}\n{seq}\n".encode("utf-8")


def read_envelope(headers) -> dict:
    """从请求头里取四件套。缺一件就拒，且**先于**任何解析——不猜。"""
    got = {}
    for key, name in (("party", H_PARTY), ("issued", H_ISSUED),
                      ("nonce", H_NONCE), ("sig", H_SIG)):
        v = headers.get(name)
        if v is None or not str(v).strip():
            raise AuthError("DGB_ING_001", f"缺少请求头 {name}")
        got[key] = str(v).strip()
    if not NONCE_RE.match(got["nonce"]):
        raise AuthError("DGB_ING_001", f"{H_NONCE} 形状应为 22–64 位 base64url 字符")
    try:
        got["issued_dt"] = datetime.datetime.strptime(got["issued"], ISSUED_FMT).replace(
            tzinfo=datetime.timezone.utc)
    except ValueError:
        raise AuthError("DGB_ING_001",
                        f"{H_ISSUED} 必须是 {ISSUED_FMT} 形状的 UTC 时间") from None
    try:
        got["sig_text"] = base64.b64decode(got["sig"], validate=True).decode("utf-8")
    except Exception:
        raise AuthError("DGB_ING_001", f"{H_SIG} 应是 SSHSIG armor 的 base64") from None
    if "BEGIN SSH SIGNATURE" not in got["sig_text"]:
        raise AuthError("DGB_ING_001", f"{H_SIG} 解出来不是 SSHSIG")
    return got


def check_window(envelope: dict, now: datetime.datetime | None = None) -> None:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    delta = (now - envelope["issued_dt"]).total_seconds()
    if delta > WINDOW_SECONDS:
        raise AuthError("DGB_ING_004",
                        f"签名已过期 {-delta:.0f} 秒（窗口 {WINDOW_SECONDS} 秒）")
    if delta < -FUTURE_SKEW:
        raise AuthError("DGB_ING_004", f"签名时间超前 {-delta:.0f} 秒，检查客户端时钟")


def _ssh_verify(pubkey_line: str, principal: str, sig_text: str, payload: bytes,
                namespace: str = NAMESPACE) -> tuple[bool, str]:
    """**唯一调用 `ssh-keygen -Y verify` 的地方。** selftest 用 AST 扫描守住这一条。

    `allowed_signers` 每次就地生成：库里 `party.pubkey` 才是唯一事实源，缓存成
    一个长驻文件就会多一份「库改了、文件没改」的可能。一次请求一个临时目录，
    目录随 with 退出删除。

    `namespace` 落在命令行上，所以每一次调用都带着域，容器自己会拒掉不匹配的签名。
    """
    parts = pubkey_line.split()
    with tempfile.TemporaryDirectory(prefix="dg-verify-") as td:
        allowed = os.path.join(td, "allowed_signers")
        sig = os.path.join(td, "sig")
        # allowed_signers 只放主体与钥，注释字段不带进来：注释是给人看的，
        # 带进来只是多一段可能含空格、需要转义的输入。
        with open(allowed, "w", encoding="utf-8") as fh:
            fh.write(f"{principal} {parts[0]} {parts[1]}\n")
        os.chmod(allowed, 0o600)
        with open(sig, "w", encoding="utf-8") as fh:
            fh.write(sig_text)
        os.chmod(sig, 0o600)
        try:
            p = subprocess.run(
                ["ssh-keygen", "-Y", "verify", "-f", allowed, "-I", principal,
                 "-n", namespace, "-s", sig],
                input=payload, capture_output=True, timeout=15, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"ssh-keygen 不可用：{type(exc).__name__}: {exc}"
    out = (p.stdout + p.stderr).decode("utf-8", "replace").strip()
    return p.returncode == 0, out


def verify_detached(pubkey_line: str, principal: str, sig_text: str, payload: bytes,
                    namespace: str) -> tuple[bool, str]:
    """裸验签：**载荷由调用方给**，不经过信封。

    与 `verify()` 的区别不是参数多少，是防护对象不同：`verify()` 防的是「这个 HTTP
    请求是这把钥发的」，所以它自己拼载荷、自己查时间窗；这里防的是「这个人认可这条
    已经发生的事」，载荷必须是**从库里重算出来的值**——客户端自带的一律不信，否则
    签名保护的就成了客户端自己写的那句话。

    namespace 只认四个取值：写入面、确认层、拒收层、催告层。写成「随便传」的话，
    调用方某天传错一个串，表现是「验签总是失败」，而没人会想到是这里。
    """
    if namespace not in (NAMESPACE, CONFIRM_NAMESPACE, REJECT_NAMESPACE,
                         REMIND_NAMESPACE):
        raise ValueError(f"未知 namespace={namespace}")
    return _ssh_verify(pubkey_line, principal, sig_text, payload, namespace)


def verify_read(headers, path: str, lookup):
    """读口（`GET`，无请求体）的验签。**只是 `verify` 的一层固定参数转发。**

    为什么单独开这个名字，而不是让调用方直接写 `verify(..., "GET", path, b"", ...)`：
    `selftest` 用「`signing.verify(` 在 ingest.py 里只有 1 个调用点」来证明「没有哪条
    写口偷懒少验一道」。读口也验签，但它不是写口——把它的调用混进同一个计数，
    那条判据要么变红，要么被放松成「随便几个都行」，两种都在削弱它。

    所以这里把「GET + 空 body」定死成一个名字：读口的验签走同一段实现，
    但它不能自带 method、不能自带 body，也就没法变成一条绕过写口校验的旁路。
    """
    return verify(headers, "GET", path, b"", lookup)


def verify(headers, method: str, path: str, body: bytes, lookup, hint_pubkey: str | None = None):
    """验一份签名请求。返回 (party_id, 公钥指纹, 信封)。失败抛 AuthError。

    `lookup(party_id) -> 公钥行 | None`：由调用方给（它知道库在哪）。
    `hint_pubkey`：登记公钥那一条专用——第一次登记时库里还没有这把钥，
    只能拿请求体里自带的那把验，这恰好也是「持有私钥」的证明。
    """
    env = read_envelope(headers)
    check_window(env)

    raw = hint_pubkey if hint_pubkey is not None else lookup(env["party"])
    if not raw:
        raise AuthError("DGB_ING_003", f"主体 {env['party']} 尚未登记公钥")
    key_line, blob = parse_pubkey(raw)

    payload = build_payload(method, path, env["party"], env["issued"], env["nonce"], body)
    ok, out = _ssh_verify(key_line, env["party"], env["sig_text"], payload)
    if not ok:
        # 原文进服务日志，回给调用方的只有一句话。ssh-keygen 的失败串里会写出
        # 「哪一把钥、哪个 principal 不匹配」，对攻击者是免费的侦察信息。
        print(f"ingest: ssh-keygen verify failed for {env['party']}: {out[:200]}", flush=True)
        raise AuthError("DGB_ING_002", "验签失败：签名与请求体、路径或主体不符")
    fp = fingerprint(blob)
    # 这两项放回信封，是为了让调用方不必再读一次库：确认层要用同一把钥验第二段签名，
    # 而那时已经验过「这个请求是这把钥发的」。再查一次库只会多一个「两次读到不同结果」的窗口。
    env["key_line"], env["key_fp"] = key_line, fp
    # 逐字载荷也放回信封（v1.8）：需求单要把它连同签名一起存进库里，让事后的人能
    # 离线复验。**必须是这里算出来的那一段**，不能让调用方自己重拼——重拼出来的载荷
    # 只要差分一字节，存下去的就是一段永远验不过的「证据」，而它看起来完全正常。
    env["signed_payload"] = payload
    return env["party"], fp, env
