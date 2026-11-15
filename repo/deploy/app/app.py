# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 老夫 <2379731846@qq.com>
"""账本公开页 · 只读服务（C3）。中文与英文各若干页、三个只读接口；页数不在此写死（以 ``PAGES`` 为准），进程不具备写账本的能力。

**v1.0-min（2026-11-11 21:30）：展示层下线，只留说明页与接口。**

起因是核验发现账本库没有卷挂载——库是 ``docker build`` 时由
``COPY data/`` 打进镜像的。在把存放方式改成挂载之前，页面上任何"数字"
都可能与库里的真实数据各说各话（宿主改了库、镜像里还是旧的）。所以
这一版把展示层整个摘掉：页面不含任何来自账本的数据，连条数、锚值都不渲染。

- 页面：``/`` 与 ``/ledger/`` 共用一张静态说明页，零 JS、零数据读取，
  只保留三句标（闸门 #7）与三个接口入口。
- 接口：``items`` / ``verify`` / ``export`` 逻辑与返回结构一字未改，
  锚值以 ``/ledger`` 页为准（随入账与结构升级而变，本段不抄常数）——最简版动的只是展示，不是口径。
- 解耦：库读不出来时页面照常 200，``/api/*`` 明确返回 503
  （``data_layer_unavailable``），不再让库问题把首页拖成 500。
- 回滚：完整展示版留在 ``_archive/app_v0.5.1_20261111_2122.py``，
  换回该文件重新 build 即恢复，无需改任何配置。
- **这一段已被下面的 v1.1 覆盖**：现在有六个页面，``/ledger`` 上有锚值卡与条目数，
  只是条目明细仍未渲染。读到这里请接着看 v1.1。

**v1.1（2026-11-12 夜）：首页底加访问计数，并加英文三页 ``/en`` ``/en/contributors`` ``/en/ledger``。**

两件事都只动展示，账本条目、哈希链、锚值算法一字未改。

- 访问计数（``Visits``）：**只数首页**，只在中文首页底部显示一行「已有 N 名访问者」。
  没有分页明细、没有起始日、没有口径说明段落——那些是运维关心的，不是访客要看的。
  只存 ``(day, n)``，无 IP、无 UA、无 cookie、无第三方脚本，因此**无法去重**；
  计数落 ``visits.db``，与账本不同文件、不参与建链；写失败只记日志，
  首页干脆不显示这一行，不显示假数字。
- 英文页与中文一一对应（``/en`` 讲项目、``/en/contributors`` 讲人、``/en/ledger`` 讲数据、
  ``/en/testing`` 测与验、``/en/requests`` 需求），小节、入口卡、页脚照中文来，不是另写摘要。
  末尾都挂同一句「与中文不一致时以中文为准」——避免同一件事出现两种说法各说各话。
- 静态页共用 ``PAGES`` 表做路由；需求页带 ``?state=``、单页是动态路径，在 ``do_GET`` 单独分支。

**v1.2（2026-11-14）：需求两页 ``/requests`` 与 ``/r/<id>``（11-15 改名并升为并列页）。**

账本记「已经给了什么」；这两页记「谁还缺什么」，以及一条需求怎么发出来。三条口径与读口
``spec/request.md`` 一致：

- 一览读 ``v_public_request``——与读口调的是**同一个函数**（``load_request_page``），
  列表口径不会各说各话；单页读 ``request`` 全表，因为单页的承诺是**永久可读**，
  不受 90 天收窄影响。
- 两页都**不经过 ``Ledger`` 的内存链**：它们读的是需求单与条目表，跟锚值无关；
  ``/r/<id>`` 上印的账目 hash 由 ``build_chain`` 重算，与 ``/api/ledger/items`` 同一个数。
- ``/requests`` 不进 ``PAGES`` 表（它带查询参数 ``?state=``，而那张表只收零参函数）；
  ``/r/<id>`` 是动态路径。两条都在 ``do_GET`` 里单独分支，坏 ``state`` 回 400，
  不「当作没传」——那会让读者以为筛选生效了，屏幕上其实是全量。
- 诚实边界写进了页面：**状态行不是账目**，没有哈希可复算，单页明说「这一页不能证明状态」；
  能复算的只有交付生成的那两条。空列表也不是故障，是一句「现在没有公开的需求单」。

设计立场（三条，都写在这里而不是藏在代码里）：

1. **只读**。服务以 SQLite 只读模式打开账本（``file:...?mode=ro``），
   进程在物理上不具备写账本的能力——公开页的攻击面因此少一整类。
   **r6 起账本可写了，但这一条不变**：写入是另一个进程（``ingest.py``，只挂在
   ``/api/v1/*``、卷以读写挂入），本进程仍以只读方式挂同一个库。要在本进程里
   也能写，就得把这个卷改成读写，那等于用一句注释换掉一整类攻击面。
   这也解释了 ``Ledger.maybe_reload()``：库会被别人写，内存链因此必须能重建。
2. **链在读时建，锚在启动时算**。启动时把三张 append-only 表规范化为
   统一条目，用 repo/src/ledger_hash.py 的同一套算法建哈希链，常驻内存；
   同时算出链导出件的 sha256 作为锚。任何人可以 curl 导出件自行
   sha256sum 对比，也可以拿 items 自己跑 verify_chain——验证不依赖相信
   运营方，只依赖标准库。
3. **主体展示只走 v_public_party 的口径**。非实名/未绑定/已撤回一律
   回落 party_id；本服务不直接读 real_name_ref 列。

**下面 v0.3–v0.5 的变更史描述的是界面模块，这些模块在 v1.0-min 已整体移除。
保留原文只为说明「当初为什么那样写」，不要按它去代码里找 THANKS 常量、统计卡或
滚动列表——现在一个都没有；`Ledger.stats()` 仍在，但当前没有调用方。**

v0.3 变更：
  - 账本公开页迁到 ``/ledger/``（``/ledger`` 301 跳转）；``/`` 改为着陆页，
    同样带三句标（闸门 #7 在两个页面都成立）。
  - 账目列表自动滚动（CSS 动画，悬停暂停；``prefers-reduced-motion`` 时
    退化为普通滚动条）。
  - 视觉彩色化：渐变页头、彩色类型标签与卡片描边。
  - 新增「特别鸣谢」模块（THANKS 常量，改这里即可更新名单）。

v0.5 变更（去「AI 生成感」，功能与信息不变）：
  - 文案整体口语化：首页改成一段人说的话，去掉机械排比；账本页标题、
    卡片标签、验证引导、页脚都换成自然措辞。
  - 布局去模板化：首页弃用等宽三卡，改为一张主入口大卡 + 一块开发者
    小抄；统计卡首张跨两列；补品牌标记（井字圆角块）与 favicon。
  - 三句标、锚值、接口路径与返回结构、统计口径均未动。

v0.4 变更：
  - 修「账目条数与账目记录数不符」：滚动区此前无条件复制一份 tbody 做
    无缝循环，条目不足一屏时每条出现两次、看起来翻倍。现在只在内容
    超过一屏时才复制并开滚动，否则单份静态展示。
  - 首页新增「已撮合数据统计」：按 mutual_id 归组，展示撮合组数、
    已回报闭环数、已入组/未撮合条目、参与主体数与范围分布。
  - 「特别鸣谢」移到首页（着陆页）。
  - JSON 接口改为缩进排版（indent=2），items 与 verify 各自带
    ``endpoint`` 字段并补足自描述字段，浏览器里直接可读、互相可区分；
    ``/api/ledger/export`` 保持紧凑字节不变——锚值 sha256 不受影响。

闸门对应（开工清单 §8）：
  #2  GET /api/ledger/items  无账号/Key 返回非空 items
  #3  GET /api/ledger/verify 返回 {"ok": true, "first_bad": null}
  #7  GET / 与 GET /ledger/  首页可见三句标
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from ledger_hash import GENESIS, build_chain, canonical, verify_chain
# 三表 → 条目的读法只有一份，与写入面（ingest.py）共用。放在这里 import 而不是在本文件
# 里再写一遍：两份实现的失败方式不是报错，而是「写进去的 hash 与读出来的链对不上」，
# 且只在第三方复算时暴露。
from ledger_store import (REQUEST_STATES, decode_cursor, load_confirmations,
                          load_entries, load_request_detail, load_request_page)

# 三件套的公示文本。由 `_ops/build_legal_pages.py` 从 Markdown 生成，勿手改：
# 里面装的是原文（逐字节）与预渲染好的 HTML。运行时不解析 Markdown——一份法律
# 文本的呈现不该依赖一段没被审过的渲染代码。
import legal

DB_PATH = os.environ.get("LEDGER_DB", "data/ledger.db")

# 给 agent 的接入指南。放磁盘而不是内嵌成字符串：它是一份会被反复改的文档，
# 而内嵌进代码的文档只有一种下场——代码里那份和仓库里那份慢慢不一样，且没人发现。
AGENT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent.md")
# 审计任务书。与 agent.md 分开放，因为读它们的是两种人：agent.md 是「怎么加入」，
# audit.md 是「怎么查我」。混在一份里，审计者要读 14 KB 才找到自己能做的事。
AUDIT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit.md")
# 访问计数单独一个库，与账本库不同文件、不参与建链：计数器坏了、丢了、
# 被人清了，账本与锚值一个字节都不受影响。
VISITS_PATH = os.environ.get("VISITS_DB", "data/visits.db")
# 按北京时间的「天」分桶。容器默认 UTC，若不指定，晚上 8 点之后的访问
# 会被记到「明天」，运维看着每天的曲线会以为时间错乱。
VISIT_TZ = datetime.timezone(datetime.timedelta(hours=8))
ADDR = ("0.0.0.0", int(os.environ.get("PORT", "8000")))

# ⚠ 这段字**在哈希里**：``Ledger.reload()`` 把它和 genesis、items 一起 canonical 化
# 后取 sha256 当锚值。改一个字，锚值就变（实测：只把「W4 结构验证样例」改成「结构验证
# 样例」，cdec34e5… 立刻变成 032e2f78…），文档里记的锚值、TRADEMARK T6 的比对基准全部
# 失效。措辞有毛病也**不能顺手改**——要改就得走一次显式重锚（新 tag + 全部记录同步）。
#
# 这句话确实别扭：「beta 期替换」里的 beta 就是现在，等于说「在现在替换」。2026-11-12
# 用户看过更顺的几种写法（「按项目进度适时调整为…」＝说了等于没说；「有第一批真实账目
# 后替换」最好，把承诺挂在事件上而不是日历上，对应锚值 4d5bf311…），**决定暂不改**：
# 它只出现在 /api/ledger/items 与导出件里，页面上不显示，为它单独动一次锚不值。
# 排期：v2.2 要给 receive/payback 补 occurred_at、动表、条目哈希必然重算，那时锚值反正
# 要变，顺手换成「有第一批真实账目后替换」，只花一次重锚。
DATA_NOTICE = (
    "测试期数据：W4 结构验证样例（4 条，假 ID）。beta 期替换为真实账目。"  # 冻结，见上
)

# ── /testing「测试与验证」（v1.4，2026-11-15；原名 /join「怎么参与」，v1.3）──────
# 改名的理由不是换个好听标题：站点上能做的只有两件事——参与测试与自己验证账本。
# 「怎么参与」只说了前一半，「验证」散在 /ledger 与仓库文档里，访客看不到全貌；
# 现在这一页把两半收在一处，并与贡献与参与者、账本数据查询并列成三张主页。
# 起因是一个实测出来的歧义：/needs 上挂着「可接」的单子，详情页却没有任何入口，而
# /sign/ 要的是发布方发的 dgtask1: 任务卡——从列表抄一个 request_id 粘进去走不通。
# 三种处境：有卡 → /sign/；想自己挑 → /agent.md；想发单 → 测试期没有自助入口。
# 三条边界必须写在页面上：认领后不能换人（状态机只有 delivered 与发布方 withdrawn
# 两条出口）、网页不认列表编号、到期没有自动改状态的机制。
# 静态文案：不读库、不进导出件、不动锚值。旧路径 /join 与 /en/join 301 到新页。
# **这一段刻意放在 DATA_NOTICE 之后**：不插在文件头，免得把上面那段历史举例（记着
# 11-11 实测的 cdec34e5 → 032e2f78）挤到别处去。判据现在按内容认那一段、不钉行号，
# 但让既有行号稳住总归省事——历史上就因为头部加了一行 `import re` 而假红过一次。

# ── /requests「需求发布」（v1.5，2026-11-15；原名 /needs「还缺什么」）──────────
# 改名不是换标题：「还缺什么」只说了这一页被动的一半（你能看到别人缺什么），读不出
# 「我也可以发一条」——而发单才是这一页的写入动机。名字改成动词性的之后，正文必须
# 真的回答「怎么发」：第一节是发单三步（登记公钥 → 签名发单 → 等人认领）与必填字段，
# 而不是先甩一串卡片。**标题许诺、正文不接，就是这一轮要消掉的那种歧义。**
# 测试期没有网页发单表单，也不打算做：写库一律验签，浏览器里没有替你保管私钥的地方
# （`/sign/` 那把钥是接单的人当场生成的，不是给发单用的）。
# 路径 /needs → /requests；旧地址 301 **且保留查询串**——`?state=` 是筛选，丢了会
# 悄悄变回全量，屏幕上看起来像「筛选生效了」，比 404 更像谎话。英文页 /en/requests
# 与中文同构（四节、同一批事实），不再像以前那样在英文导航里缺席。

# ── 欢迎层（v1.6，2026-11-15）────────────────────────────────────────────────
# 用户要求「在主页前加入欢迎页」，并给了一版 SPA 原型（三张全屏图 + 指示点 + 跳过）。
# 三张图连成一条线：有人把本事教给你 → 人机协同交付 → 两个智能体在见证下握手，
# 正好是这本账的三步（被帮 → 交付 → 可验证的互信）。
#
# 原型靠 JS 翻页，但本站 CSP 是 script-src 'none'（Handler.CSP 全局关死脚本）——
# 为了一个欢迎页撕掉自己的封条不值。所以做成**纯 HTML/CSS**，且按 2026-11-15 的
# 最终口径做成**与主页完全分离的前置引导模块**：
#
#   /            → 302 → /welcome      （进入应用的入口只做一件事：送去引导）
#   /welcome     → 第 1 屏
#   /welcome/2   → 第 2 屏
#   /welcome/3   → 第 3 屏            （英文同名：/en/welcome[/2|/3]）
#   /home        → 主页（最后一屏的点击面与按钮都导航到 /home）
#
# **一页一屏**（2026-11-15 夜用户改口径：原来三屏叠在一个文档里、下滑就能看到三张图，
# 那不是他要的）。所以这里没有 scroll-snap、没有 #w2 锚点跳转，html/body 直接
# `overflow: hidden`——滚也滚不出下一页，翻页只有点击一条路：整屏点击面 → 下一页。
#
# 点击链写死在渲染函数里，零脚本、零存储：每次进入都走一遍引导（用户 2026-11-15
# 裁定去掉「首次」二字，因此不需要 cookie，隐私政策 3.12「不使用 Cookie」原样成立）；
# 屏上唯一可见的字仍是那个「进入主页」按钮。
#
# 图片由本进程白名单直服（``_serve_image``）：只认 WELCOME_IMAGES 里点名的六个文件，
# 文件名到磁盘路径之间不做任何拼接，遍历与注入无从谈起；响应带一年 immutable 缓存
# ——文件若换，连名字一起换。``<picture>`` 在窄屏与竖屏切手机版图，流量 227KB→100KB。
WELCOME_MAIN_ID = "main"

# 三张图各配一句 alt（不显示，给读屏器）。画面上没有文字，alt 是这层仅存的语义。
WELCOME_ALTS = {
    "zh": ["机器人在黑板前为学生讲解数学公式",
           "工程师与人形机器人夜间协同调试设备",
           "两个机器人握手，背景是星空下的城市"],
    "en": ["A robot tutor explains equations at a blackboard",
           "An engineer and a humanoid robot debugging equipment together at night",
           "Two robots shaking hands above a city under the stars"],
}
# dot / dots 是给指示点用的读屏文案：拆页后指示点**是链接**，不能再 aria-hidden。
WELCOME_LABELS = {
    "zh": {"enter": "进入主页", "next": "下一张",
           "dot": "第 {i} 张，共 {n} 张", "dots": "引导进度"},
    "en": {"enter": "Enter site", "next": "Next image",
           "dot": "Image {i} of {n}", "dots": "Intro progress"},
}
# 白名单：文件名 → Content-Type。/images/ 下出现表外名字一律 404：
# 不猜扩展名、不做目录列表、不拼路径——「服务谁」由代码点名，不由 URL 描述。
WELCOME_IMAGES = {
    "welcome-1.jpg": "image/jpeg", "welcome-1-m.jpg": "image/jpeg",
    "welcome-2.jpg": "image/jpeg", "welcome-2-m.jpg": "image/jpeg",
    "welcome-3.jpg": "image/jpeg", "welcome-3-m.jpg": "image/jpeg",
}
IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")

# 引导页自己的样式，与站点的 BASE_CSS/PAGE_CSS 零共享——它是一张独立文档，
# 不带站点导航、页脚、提示条，也不依赖站点那套 token。没有「未生效」标注，
# 所以整页就是完整的 100svh，不需要折减。
#
# v1.9.2（2026-11-16 凌晨）：口径改为「完整放原图，不裁切」。
#   v1.9.1 的 cover 在桌面横屏会按屏幕比例裁掉上下——图不是原图了。
#   现在 object-fit: contain：任何屏幕都完整显示 1440×894 的原始画面，
#   多出的地方用底色补（竖屏仍是居中圆角卡片）。缓放动画一并撤掉：
#   scale(1.06) 起手就是裁切，与「放原图」矛盾。
#
# v1.9.1（2026-11-15 夜，按「一页一屏」重做）：三处与 v1.9 的根本差别——
#   ① 不再有 scroll-snap 与 `:target`：每页都是刚载入，缓放直接挂在 `.whit img` 上；
#   ② `overflow: hidden` 把「下滑看下一张」这条路物理封死，翻页只能点；
#   ③ 指示点从装饰性 span 变成 <a>：它就是三个页面之间的导航，当前页带
#      aria-current="page"（视觉上是拉长的胶囊）。点上的可点区域用 ::after 撑到
#      26px，视觉仍是 8px 的点。
WELCOME_CSS = """
  html, body { margin: 0; padding: 0; background: #101614; }
  /* 一页一屏，不许滚动：三张图在三个 URL 上，滚也滚不出下一页。 */
  html, body { height: 100%; overflow: hidden; }
  /* 三页之间的淡入淡出：纯 CSS 的跨文档视图过渡，不支持的浏览器照常直接跳。 */
  @view-transition { navigation: auto; }
  .ws { position: relative; height: 100vh; height: 100svh; overflow: hidden;
        background: #101614; }
  .whit { position: absolute; inset: 0; z-index: 1; display: block; cursor: pointer; }
  /* contain：完整放原图，不裁切；屏幕比图宽/高的部分由底色补齐。 */
  .whit picture, .whit img { width: 100%; height: 100%; object-fit: contain; display: block; }
  /* 叠层：底部压暗（按钮与指示点可读）+ 品牌色斜向轻染（站色，不是原型那个蓝） */
  .whit::after { content: ""; position: absolute; inset: 0; z-index: 2; pointer-events: none;
    background:
      linear-gradient(to top, rgba(10, 15, 14, .42), rgba(10, 15, 14, 0) 34%),
      linear-gradient(155deg, rgba(15, 118, 110, .12), rgba(255, 255, 255, 0) 46%,
        rgba(109, 90, 224, .10)); }
  .wdots { position: absolute; bottom: 5.2rem; left: 50%; transform: translateX(-50%);
           z-index: 3; display: flex; align-items: center; gap: .55rem; }
  .wdot { position: relative; display: block; width: .5rem; height: .5rem;
          border-radius: 999px; background: rgba(255, 255, 255, .45);
          box-shadow: 0 1px 4px rgba(0, 0, 0, .25);
          transition: width .4s cubic-bezier(.22, 1, .36, 1), background .4s; }
  /* 视觉是 8px 的点，可点区域撑到 26px——手指不必瞄准 */
  .wdot::after { content: ""; position: absolute; inset: -.55rem; }
  .wdot.on { width: 1.6rem; background: #fff; }
  .wdot:focus-visible { outline: 2px solid #fff; outline-offset: 4px; }
  .wskip { position: absolute; bottom: 1.8rem; left: 50%; transform: translateX(-50%);
           z-index: 3; display: inline-block; padding: .68rem 2.2rem; border-radius: 999px;
           background: linear-gradient(118deg, #0b5a54 0%, #2e7d94 46%, #5f52d6 100%);
           color: #fff; font-weight: 600; text-decoration: none;
           font-size: .95rem; letter-spacing: .04em; cursor: pointer;
           box-shadow: 0 6px 22px rgba(10, 15, 14, .35);
           transition: transform .18s ease, box-shadow .18s ease; }
  .wskip:hover { transform: translateX(-50%) translateY(-1px);
                 box-shadow: 0 10px 28px rgba(10, 15, 14, .4); }
  .wskip:focus-visible { outline: 2px solid #fff; outline-offset: 3px; }
  @media (max-width: 640px) { .wskip { bottom: 1.3rem; padding: .6rem 1.8rem; }
    .wdots { bottom: 4.4rem; } }
  /* 竖屏：图片改居中圆角卡片（contain，不裁切），背后一团品牌色光晕；
     点击面仍是整屏 .whit——卡片之外点下去照样翻页，与「点任意处」的口径一致。 */
  @media (max-width: 900px) and (orientation: portrait) {
    .ws { display: flex; align-items: center; justify-content: center;
          padding: 0 1.1rem 7.6rem;
          background: linear-gradient(160deg, #eef2f1 0%, #f2f1f8 46%, #fdf6ee 100%); }
    .ws::before { content: ""; position: absolute; width: 82vw; height: 82vw;
          max-width: 560px; max-height: 560px; border-radius: 50%;
          background: radial-gradient(circle, rgba(15, 118, 110, .15),
            rgba(109, 90, 224, .10) 46%, rgba(255, 255, 255, 0) 72%);
          pointer-events: none; }
    .whit picture { width: 100%; max-width: 480px; border-radius: 1rem; overflow: hidden;
          background: #e9efec;
          box-shadow: 0 18px 44px -18px rgba(16, 22, 20, .42), 0 2px 10px rgba(16, 22, 20, .08); }
    /* 高度跟随图的原始比例，不锁 aspect-ratio——原图怎么画就怎么显示。 */
    .whit img { width: 100%; height: auto; }
    .whit::after { display: none; }
    .wdot { background: rgba(16, 22, 20, .16); box-shadow: none; }
    .wdot.on { background: #0b5a54; }
  }
"""


def _welcome_url(lang: str, page: int) -> str:
    """第 page 屏的地址。第 1 屏就是 `/welcome`（不另设 `/welcome/1`）。"""
    base = "/en/welcome" if lang == "en" else "/welcome"
    return base if page == 1 else f"{base}/{page}"


def render_welcome(lang: str = "zh", page: int = 1) -> bytes:
    """引导第 `page` 屏：**一个页面一屏**，与主页零共享。

    点击面链到下一页（最后一屏链到主页），底部按钮任何时候都直达主页。
    page 越界时夹到 1..n——路由按 WELCOME_ALTS 的长度生成，正常不会越界，
    夹住只是为了让「临时少一张图」不至于 500。noindex：引导页不是内容页。
    """
    en = lang == "en"
    key = "en" if en else "zh"
    alts = WELCOME_ALTS[key]
    lab = WELCOME_LABELS[key]
    home = "/en/home" if en else "/home"
    n = len(alts)
    page = max(1, min(int(page), n))
    i = page - 1
    last = page == n
    nxt = home if last else _welcome_url(lang, page + 1)
    hit_label = lab["enter"] if last else lab["next"]

    # 指示点：三枚都是真链接，当前页那枚带 aria-current 与 .on（拉长成胶囊）。
    dots = "".join(
        f'<a class="wdot{" on" if j == i else ""}"'
        f' href="{_welcome_url(lang, j + 1)}"'
        + (' aria-current="page"' if j == i else "")
        + f' aria-label="{esc(lab["dot"].format(i=j + 1, n=n))}"></a>'
        for j in range(n)
    )

    # 下一页的图先取：三页之间是真实导航，不预取会白一瞬。两档图各按自己的媒体
    # 条件预取——桌面浏览器不会顺手把手机版也拉下来（两个条件互为补集）。
    preload = ""
    if not last:
        k = page + 1
        preload = (
            f'<link rel="preload" as="image" href="/images/welcome-{k}-m.jpg" '
            'media="(max-width: 640px), (max-width: 900px) and (orientation: portrait)">\n'
            f'<link rel="preload" as="image" href="/images/welcome-{k}.jpg" '
            'media="(min-width: 641px) and (orientation: landscape), (min-width: 901px)">\n'
        )

    title = "Zhong Ji Zhi Jing" if en else "众汲之井"
    html = (
        f'<!doctype html>\n<html lang="{"en" if en else "zh-CN"}">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="robots" content="noindex, nofollow">\n'
        f"<title>{esc(title)}</title>\n"
        f"{preload}"
        f"<style>{WELCOME_CSS}</style>\n"
        "</head>\n<body>\n"
        '<section class="ws">'
        f'<a class="whit" href="{nxt}" aria-label="{esc(hit_label)}">'
        '<picture>'
        '<source media="(max-width: 640px), (max-width: 900px) and (orientation: portrait)" '
        f'srcset="/images/welcome-{page}-m.jpg">'
        f'<img src="/images/welcome-{page}.jpg" alt="{esc(alts[i])}" '
        'width="1440" height="894" loading="eager" '
        'decoding="async"></picture></a>'
        f'<nav class="wdots" aria-label="{esc(lab["dots"])}">{dots}</nav>'
        f'<a class="wskip" href="{home}">{esc(lab["enter"])}</a>'
        "</section>\n"
        "</body>\n</html>"
    )
    return html.encode("utf-8")


def render_welcome_zh() -> bytes:
    return render_welcome("zh")


def render_welcome_en() -> bytes:
    return render_welcome("en")


BADGES = [
    "测试版（beta）——功能与口径均可能调整",
    "暂行名 · 名称待检索（商标申请在审）",
    "未获外部法律意见（外审进行中）",
]

# ── 协议公示（v1.2，2026-11-12）──────────────────────────────────────────────
# 三件套 30 日公示（用户协议 1.11.5、1.20.3）的站点载体。此前公示只有一个
# 日历上的日期，页面上找不到任何文本——公示这件事得有地方可看。
#
# 起算日只写在这里一处：页面上所有日期都从它算，免得「起算日」散落在正文、
# 页脚、状态卡里各写一遍、改一处漏两处。
#
# 2026-11-14 从 11-12 改成 11-14：账本结构升级同时更正了隐私政策附录的一句技术说明，
# 页顶摘要变了，公示期按既定口径**重新起算**（公告 `/download/notice-20261114.md` 已这么说，
# 站点若还写 11-12，两句话就同时在对外）。首次公示日 11-12 没有消失——它进了页末的
# 变更记录，那里是历史，不受这个常量影响。
DISCLOSURE_START = "2026-11-14"     # 本轮公示起算日（11-12 首次公示，11-14 重新起算）
DISCLOSURE_DAYS = 30
PLANNED_EFFECTIVE = "2026-12-21"

# 页面上印的指纹不写死：启动时对 raw 现算。写死的指纹迟早与文本漂移，
# 而这种「印出来的校验值对不上自己吐出的字节」正是本站最不该犯的错。
for _doc in legal.DOCS:
    _blob = _doc["raw"].encode("utf-8")
    _doc["sha256"] = hashlib.sha256(_blob).hexdigest()
    _doc["bytes"] = len(_blob)

# 【待填】的总处数从正文里数出来，不手写：「若干处」是含糊，「26 处」可核对。
# 数字对不上时，说明生成的 legal.py 与源稿脱节了，比含糊其辞更容易被发现。
TBD_TOTAL = sum(_doc["html"].count('class="tbd"') for _doc in legal.DOCS)


def _notice_bar(lang: str = "zh") -> str:
    """全站页首的「未生效」标注。每页都有，不只是首页 —— 生效状态是前提，
    不是某一页的补充说明。"""
    if lang == "en":
        return ('<div class="notice"><div class="wrap">'
                '<b>Protocol v2.1-r6 is published for comment — not yet in force.</b>'
                f'<span>Effective date planned for {PLANNED_EFFECTIVE}, subject to four conditions. '
                '<a href="/terms">Notice page (Chinese)</a></span></div></div>')
    return ('<div class="notice"><div class="wrap">'
            '<b>协议 v2.1-r6 公示中，尚未生效。</b>'
            f'<span>计划生效日 {PLANNED_EFFECTIVE}，以四项条件全部满足为前提。'
            '<a href="/terms">公示页</a></span></div></div>')


def datasource_banner(db_path: str) -> str:
    """启动横幅用的「库从哪来」一行。

    背景（2026-11-11 修 P0-A）：库原先由 Dockerfile COPY 打进镜像，宿主
    /opt/drawcommons/app/data/ 只是备份源，不是服务源。两者一旦分叉，
    「改了宿主库、线上仍是旧数据」不会有任何报错——比对字节数才发现。
    现在 compose 把宿主目录只读挂到 /srv/data，镜像内副本被遮蔽。这里读
    /proc/self/mountinfo 判断目标目录是不是挂载点，不是就明确喊出来。
    只做提示，不影响服务：读不到 mountinfo 就当未知，不阻断启动。
    """
    try:
        target = os.path.realpath(os.path.dirname(os.path.abspath(db_path)))
        mounted = False
        with open("/proc/self/mountinfo", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                fields = line.split()
                if len(fields) > 4 and os.path.realpath(fields[4]) == target:
                    mounted = True
                    break
        if not mounted:
            return f"db={db_path} ⚠ 未挂载数据卷，用的是镜像内副本（改宿主库不会生效）"
        return f"db={db_path} (bind mount ✓)"
    except OSError:
        return f"db={db_path} (挂载状态未知)"


class Ledger:
    """启动时建链；verify 每次对内存链重跑（不缓存结果，验证本身就是证据）。"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._fingerprint = None
        self.reload()

    def _stamp(self):
        """库文件的 (mtime_ns, size)。用来判断「库有没有被人写过」，不做内容比较。"""
        try:
            st = os.stat(self.db_path)
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def reload(self) -> None:
        # 戳在**读之前**取。写在读的过程中落下时，戳会与读完时的库不一致，下一次请求
        # 会再重建一遍——多花一次 O(n)，但不会把一次写入永久漏掉。反过来（读完再取戳）
        # 就会：读到旧数据、却把新戳记下来，此后不再重建。
        stamp = self._stamp()
        self.entries = load_entries(self.db_path)
        self.chain = build_chain(self.entries)
        # 确认层与 items **并列**，不进条目。理由（见 spec/request.md §5 与
        # _ops/W0-04-设计裁决.md）：条目 hash 覆盖全部字段，而确认签名覆盖 hash，
        # 两者同表就是循环。并列之后它进锚值（改一条确认就改锚值）、不进链
        # （确认没有「发生在第几条」这种位置意义）。
        self.confirmations = load_confirmations(self.db_path)
        self.export_bytes = canonical(
            {"confirmations": self.confirmations, "genesis": GENESIS,
             "items": self.chain, "data_notice": DATA_NOTICE}
        ) + b"\n"
        self.export_sha256 = hashlib.sha256(self.export_bytes).hexdigest()
        with open(self.db_path, "rb") as f:
            self.db_sha256 = hashlib.sha256(f.read()).hexdigest()
        self._fingerprint = stamp

    def maybe_reload(self) -> None:
        """库变过就重建。r6 起账本可写：不重建，公开页会一直显示旧链与旧锚值，
        而库、导出件、锚值三处各说各话——这正是本项目最不能出现的那种分叉。

        重建失败只喊一声、继续用旧链：页面宁可显示一个稍旧的锚值，也不该整站 500。
        """
        now = self._stamp()
        if now is None or now == self._fingerprint:
            return
        try:
            self.reload()
        except Exception as exc:              # noqa: BLE001
            print(f"ledger: reload failed ({type(exc).__name__}: {exc}) — 继续用旧内存链",
                  flush=True)

    def verify(self) -> dict:
        ok, first_bad = verify_chain(self.chain)
        # `confirmations` 单列一项：链自洽与「有几个人认过」是两件事。把确认数塞进
        # chain 的判定里，会让一条签名写坏的确认看起来像「链断了」。
        return {"ok": ok, "first_bad": first_bad, "items": len(self.chain),
                "confirmations": len(self.confirmations)}

    def stats(self) -> dict:
        """已撮合数据统计（口径保留；当前无调用方，页面不展示）。

        撮合 = 同一 mutual_id 下的条目组：give 发起、receive 交付、
        payback 回报闭环。无 mutual_id 的条目记为「未撮合」
        （含 scope_unresolved 的不可判定条目，属正常状态，不是异常）。
        """
        by_type = {"give": 0, "receive": 0, "payback": 0}
        scope_count: dict[str, int] = {}
        agents: set = set()
        mutual_types: dict[str, set] = {}
        mutual_entries = 0
        for e in self.entries:
            t = e["type"]
            by_type[t] = by_type.get(t, 0) + 1
            for k in ("from_agent_id", "to_agent_id"):
                if e.get(k):
                    agents.add(e[k])
            s = e.get("scope") or "未判定"
            scope_count[s] = scope_count.get(s, 0) + 1
            m = e.get("mutual_id")
            if m:
                mutual_entries += 1
                mutual_types.setdefault(str(m), set()).add(t)
        closed = sum(1 for ts in mutual_types.values() if "payback" in ts)
        return {
            "total": len(self.entries),
            "by_type": by_type,
            "agents": len(agents),
            "mutual_groups": len(mutual_types),
            "mutual_closed": closed,
            "mutual_entries": mutual_entries,
            "unmatched": len(self.entries) - mutual_entries,
            "scope_count": scope_count,
        }


class Visits:
    """首页访问计数。四条约束都不是随手写的最小实现，而是这个项目的口径。

    1. **只数首页。** 只有 ``/`` 落一行，``/contributors``、``/ledger``、
       ``/en`` 与所有 ``/api/*`` 一概不记。一个数字回答一个问题：首页被
       打开过多少次。分页分布、按页明细一概不存、不显示——不做的原因是
       没有用途，不是做不出来。
    2. **只写次数。** 表里只有 ``(day, n)``：没有 IP、没有 UA、没有来源页、
       没有会话标识、不写 cookie。因此**无法去重**——页面那串数字是首页被
       打开的累计次数，同一台机器刷新两次就是两次。
       写这个类的时候刻意没留「以后加个 visitor_id 好去重」的口子：一旦
       留了，它就不是计数，是埋点。
    3. **与账本分开存。** 落 ``visits.db``，与 ``ledger.db`` 不同文件、不参与
       建链。计数器坏、丢、被人清空，都不影响账本字节与锚值。
    4. **失败不拖累页面。** 库打不开就把 ``available`` 置 False，首页干脆
       不渲染这一行（宁可不显示，也不显示一个假数字），启动横幅会喊一声，
       运维在 docker logs 里看得见。这与 ``Ledger`` 的降级立场一致。
    """

    def __init__(self, path: str):
        self.path = path
        self.lock = threading.Lock()
        self.available = False
        self.error = ""
        try:
            con = self._con()
            with con:
                con.execute(
                    "CREATE TABLE IF NOT EXISTS home_visits ("
                    " day TEXT PRIMARY KEY, n INTEGER NOT NULL)")
            con.close()
            self.available = True
        except Exception as exc:              # noqa: BLE001（启动期兜底）
            self.error = f"{type(exc).__name__}: {exc}"

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=3)
        con.execute("PRAGMA busy_timeout=3000")
        return con

    def hit(self) -> None:
        """记一次首页打开。任何失败都只写日志，绝不抛给请求方。"""
        if not self.available:
            return
        day = datetime.datetime.now(VISIT_TZ).strftime("%Y-%m-%d")
        try:
            with self.lock:
                con = self._con()
                with con:
                    con.execute(
                        "INSERT INTO home_visits (day, n) VALUES (?, 1) "
                        "ON CONFLICT(day) DO UPDATE SET n = n + 1", (day,))
                con.close()
        except Exception as exc:              # noqa: BLE001
            self.error = f"{type(exc).__name__}: {exc}"
            print(f"visits: hit failed ({self.error})", flush=True)

    def total(self) -> int | None:
        """首页累计打开次数。不可用或读失败返回 None（不返回 0）。"""
        if not self.available:
            return None
        try:
            con = self._con()
            row = con.execute("SELECT COALESCE(SUM(n), 0) FROM home_visits").fetchone()
            con.close()
        except Exception as exc:              # noqa: BLE001
            self.error = f"{type(exc).__name__}: {exc}"
            return None
        return int(row[0] or 0)


# 展示层与数据层解耦：库读不出来（缺失/损坏/被独占）时页面照常出来，
# 只有 /api/* 降级为 503。否则一个库问题会把首页也拖成 500。
try:
    LEDGER = Ledger(DB_PATH)
    LEDGER_ERROR = None
except Exception as exc:                      # noqa: BLE001（启动期兜底）
    LEDGER = None
    LEDGER_ERROR = f"{type(exc).__name__}: {exc}"

VISITS = Visits(VISITS_PATH)


def esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


BASE_CSS = r"""
  :root {
    --ink: #182220; --muted: #5d6b66; --line: #e4e8e6;
    --card: #ffffff; --bg: #f5f7f6;
    --teal: #0f766e; --violet: #6d5ae0; --rose: #d64570; --amber: #d97706;
    --mono: ui-monospace, SFMono-Regular, Consolas, monospace;
    --grad: linear-gradient(118deg, #0b5a54 0%, #2e7d94 46%, #5f52d6 100%);
    --shadow-1: 0 1px 2px rgba(24,34,32,.05), 0 4px 14px rgba(24,34,32,.06);
    --shadow-2: 0 10px 28px rgba(15,118,110,.14);
    --ease: cubic-bezier(.22, 1, .36, 1);
  }
  * { box-sizing: border-box; }
  body {
    font-family: system-ui, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    background: var(--bg); color: var(--ink);
    margin: 0; padding: 0 1rem 3rem; line-height: 1.7;
    -webkit-font-smoothing: antialiased;
  }
  .wrap { max-width: 860px; margin: 0 auto; }
  a:focus-visible { outline: 2px solid var(--teal); outline-offset: 2px; border-radius: 4px; }
  ::selection { background: #c8e9e4; }

  .hero {
    background: var(--grad); border-radius: 0 0 22px 22px;
    margin: 0 -1rem 1.6rem; padding: 2.6rem 2rem 1.9rem; color: #fff;
  }
  .hero h1 { font-size: clamp(1.4rem, 3.4vw, 1.68rem); margin: 0 0 .3rem; letter-spacing: .02em; font-weight: 700; }
  .hero .sub { color: rgba(255,255,255,.88); font-size: .94rem; margin: 0; max-width: 40em; }
  .badges { display: flex; flex-wrap: wrap; gap: .5rem; margin: 1.1rem 0 0; padding: 0; list-style: none; }
  .badges li {
    font-size: .78rem; color: #7c4a03; background: #fdf3e3;
    border: 1px solid #f3dfba; border-radius: 999px; padding: .2rem .75rem; font-weight: 500;
  }
  .hero .badges li:first-child { color: #0b5f59; background: #e2f4f2; border-color: #bfe3de; }
  .hero .badges li:nth-child(2) { color: #4c3ec2; background: #edebfc; border-color: #d8d3f6; }
  .hero .badges li:nth-child(3) { color: #a13056; background: #fce9f0; border-color: #f5cfdd; }

  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: .8rem; margin: 1.4rem 0; }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: .9rem 1rem; border-top: 3px solid var(--line); box-shadow: var(--shadow-1); }
  .card.c0 { border-top-color: var(--teal); }
  .card.c1 { border-top-color: var(--violet); }
  .card.c2 { border-top-color: var(--rose); }
  .card.c3 { border-top-color: var(--amber); }
  .card .label { font-size: .76rem; color: var(--muted); letter-spacing: .05em; }
  .card .value { font-size: 1.02rem; font-weight: 600; margin-top: .25rem; }
  .card .value.mono { font-family: var(--mono); font-size: .8rem; font-weight: 400; word-break: break-all; cursor: pointer; }
  .card .value.mono:hover { color: var(--teal); }

  .status { display: flex; align-items: center; gap: .5rem; }
  .dot { width: 10px; height: 10px; border-radius: 50%; background: #9ca3af; flex: none; }
  .dot.ok { background: #16a34a; box-shadow: 0 0 0 3px rgba(22,163,74,.15); animation: pulse 2.4s infinite; }
  .dot.bad { background: #dc2626; box-shadow: 0 0 0 3px rgba(220,38,38,.15); }
  @keyframes pulse { 0%,100% { box-shadow: 0 0 0 3px rgba(22,163,74,.15); } 50% { box-shadow: 0 0 0 7px rgba(22,163,74,.05); } }
  .status .txt.ok { color: #15803d; }
  .status .txt.bad { color: #b91c1c; }
  .refresh-note { font-size: .78rem; color: var(--muted); margin-top: .15rem; }

  h2 { font-size: 1.05rem; margin: 2.2rem 0 .75rem; display: flex; align-items: center; gap: .5rem; letter-spacing: .01em; }
  h2::before { content: ""; width: 5px; height: 18px; border-radius: 3px; background: var(--grad); display: inline-block; }

  .tablebox { background: var(--card); border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }
  .scrollbox { max-height: 300px; overflow: hidden; }
  .scroll-inner { will-change: transform; animation: scrollUp 16s linear infinite; }
  .scrollbox:hover .scroll-inner { animation-play-state: paused; }
  /* 条目不足一屏：不开滚动、不复制行，静态展示（v0.4 修复条数翻倍观感） */
  .scrollbox.static { overflow-y: auto; max-height: none; }
  .scrollbox.static .scroll-inner { animation: none; }
  @keyframes scrollUp { to { transform: translateY(var(--shift, -50%)); } }
  @media (prefers-reduced-motion: reduce) {
    .scroll-inner { animation: none; }
    .scrollbox { overflow-y: auto; }
  }
  table { border-collapse: collapse; width: 100%; font-size: .87rem; }
  th, td { padding: .55rem .8rem; text-align: left; border-bottom: 1px solid var(--line); white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; font-size: .78rem; letter-spacing: .04em; background: #fbfcfb; position: sticky; top: 0; }
  td.mono { font-family: var(--mono); font-size: .76rem; color: var(--muted); }
  .tag { display: inline-block; border-radius: 6px; padding: .05rem .5rem; font-size: .76rem; }
  .tag.give { background: #e2f4f2; color: #0b5f59; }
  .tag.receive { background: #e8effb; color: #1d4ed8; }
  .tag.payback { background: #fdf3e3; color: #b45309; }
  .tag.scope-null { background: #eef0ef; color: var(--muted); }
  .scroll-hint { font-size: .76rem; color: var(--muted); padding: .4rem .8rem .6rem; }

  .notice {
    color: var(--muted); font-size: .84rem; border-left: 3px solid var(--amber);
    padding: .35rem .9rem; margin: 1.4rem 0 0; background: #fffdf7;
    border-radius: 0 10px 10px 0;
  }
  .howto { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: .9rem 1.2rem; font-size: .86rem; }
  .howto code {
    font-family: var(--mono); font-size: .78rem; background: var(--bg);
    border: 1px solid var(--line); border-radius: 6px; padding: .15rem .45rem;
    display: inline-block; margin: .2rem 0; word-break: break-all; cursor: pointer;
  }
  .howto code:hover { color: var(--teal); border-color: #c8e2de; }

  .thanks { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 1rem 1.2rem; }
  .thanks .thank-group h3 {
    font-size: .84rem; margin: .6rem 0 .3rem; color: var(--violet);
  }
  .thanks .thank-group:first-child h3 { margin-top: 0; }
  .thanks ul { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: .3rem .9rem; }
  .thanks li { font-size: .84rem; display: flex; justify-content: space-between; gap: .8rem; border-bottom: 1px dashed var(--line); padding: .2rem 0; }
  .thanks li span { color: var(--muted); font-size: .78rem; text-align: right; }

  footer { margin-top: 2rem; font-size: .78rem; color: var(--muted); }
  footer .endpoints { font-family: var(--mono); font-size: .74rem; }
  a { color: var(--teal); }

  /* 品牌标记：井字圆角块，两页共用 */
  .mark {
    width: 46px; height: 46px; border-radius: 13px;
    background: rgba(255,255,255,.18); border: 1px solid rgba(255,255,255,.35);
    display: flex; align-items: center; justify-content: center;
    font-size: 1.5rem; font-weight: 700; margin-bottom: .9rem;
  }

  .lead { font-size: 1rem; max-width: 34em; margin: 1.1rem 0 0; color: var(--ink); }
  .lead .hl { background: linear-gradient(transparent 60%, #cdeee8 0); }

  /* 首页主入口：一张大卡 + 一块开发者小抄，刻意不做等宽三卡 */
  .hero-card {
    display: block; background: var(--card); border: 1px solid var(--line);
    border-radius: 14px; padding: 1.15rem 1.35rem; margin: 1.5rem 0 1rem;
    text-decoration: none; color: var(--ink); border-left: 5px solid var(--teal);
    box-shadow: var(--shadow-1);
    transition: transform .2s var(--ease), box-shadow .2s var(--ease);
  }
  .hero-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-2); }
  .hero-card b { font-size: 1.06rem; }
  .hero-card p { margin: .35rem 0 0; color: var(--muted); font-size: .88rem; max-width: 30em; }
  .hero-card .go { float: right; color: var(--teal); font-weight: 600; }

  .devlinks {
    background: var(--card); border: 1px dashed #d5dad7; border-radius: 14px;
    padding: .9rem 1.2rem .8rem; font-size: .86rem; margin: 0 0 .5rem;
  }
  .devlinks h3 { font-size: .8rem; color: var(--muted); margin: 0 0 .4rem; font-weight: 500; }
  .devlinks ul { list-style: none; margin: 0; padding: 0; }
  .devlinks li { margin: .45rem 0; }
  .devlinks code {
    font-family: var(--mono); font-size: .78rem; background: var(--bg);
    border: 1px solid var(--line); border-radius: 6px; padding: .12rem .45rem;
    cursor: pointer; word-break: break-all;
  }
  .devlinks code:hover { color: var(--teal); border-color: #c8e2de; }
  .devlinks .what { color: var(--muted); font-size: .78rem; margin-left: .4rem; }

  .stats-cards { grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); }
  .stats-cards .card:nth-child(1) { grid-column: span 2; }
"""

PAGE_CSS = r"""
  .brand { width: 44px; height: 44px; line-height: 44px; text-align: center; border-radius: 12px;
           background: rgba(255,255,255,.18); font-size: 1.35rem; margin-bottom: .6rem; }
  /* 井字右边那一段：写清测试期在找哪几类帮忙。不做成横幅广告，只做一行说明——
     它回答的是「我能帮上什么」，不是「快来」。 */
  .brandrow { display: flex; align-items: center; gap: .95rem; margin-bottom: .8rem; }
  .brandrow .brand { margin-bottom: 0; flex: none; }
  .brandrow .ask { margin: 0; font-size: .84rem; line-height: 1.55; min-width: 0;
                   color: rgba(255,255,255,.9); max-width: 38em; }
  .brandrow .ask b { color: #fff; }
  .brandrow .ask a { color: #fff; text-decoration: underline; text-underline-offset: 2px; }
  @media (max-width: 520px) { .brandrow { align-items: flex-start; } .brandrow .ask { font-size: .8rem; } }
  .links { list-style: none; padding: 0; margin: .8rem 0 0; }
  .links li { padding: .7rem 0; border-top: 1px solid var(--line); }
  .links li:first-child { border-top: 0; }
  .links a { font-family: var(--mono); font-size: .92rem; text-decoration: none; }
  .links code { font-family: var(--mono); font-size: .86rem; word-break: break-all; }
  .links span { display: block; color: var(--muted); font-size: .82rem; margin-top: .15rem; }
  .plain { color: var(--muted); font-size: .86rem; }
  .plain code { font-family: var(--mono); font-size: .8rem; background: var(--bg);
                border: 1px solid var(--line); border-radius: 5px; padding: .05rem .35rem; }

  /* 六个页面共用的导航条 */
  .nav { display: flex; flex-wrap: wrap; align-items: center; gap: .45rem .8rem;
         font-size: .82rem; color: var(--muted); margin: 0 0 1rem; }
  .nav a { color: var(--teal); text-decoration: none; }
  .nav a:hover { text-decoration: underline; }
  .nav .sep { color: #cfd6d3; }
  .hero .nav { color: rgba(255,255,255,.85); margin: 0 0 .8rem; }
  .hero .nav a { color: #fff; }
  .hero .nav .sep { color: rgba(255,255,255,.45); }
  .hero.slim { padding: 1.6rem 2rem 1.25rem; }
  .hero.slim h1 { font-size: 1.26rem; }
  .hero.slim .sub { font-size: .88rem; max-width: 42em; }

  /* 首页四张并列的主页入口；子页里的两张入口卡仍用 .split。
     四张排 2×2 而不是一行四列：容器只有 860px，四列会把每张卡压到 160px 以内，
     中文变成一行三个字。两列读起来是一屏四张，横排只是看起来「并列」而已。 */
  .split { display: grid; grid-template-columns: 1fr 1fr; gap: .8rem; margin: 1.6rem 0 .3rem; }
  .split4 { display: grid; grid-template-columns: 1fr 1fr; gap: .8rem; margin: 1.6rem 0 .3rem; }
  @media (max-width: 640px) { .split4 { grid-template-columns: 1fr; } }
  @media (max-width: 640px) { .split { grid-template-columns: 1fr; } }
  .gate { display: block; background: var(--card); border: 1px solid var(--line); border-radius: 14px;
          padding: 1.1rem 1.25rem; text-decoration: none; color: var(--ink);
          border-left: 4px solid var(--teal); box-shadow: var(--shadow-1);
          transition: transform .18s var(--ease), box-shadow .18s var(--ease); }
  .gate.mid { border-left-color: var(--amber); }
  .gate.right { border-left-color: var(--violet); }
  .gate.req { border-left-color: var(--rose); }
  .gate:hover { transform: translateY(-2px); box-shadow: var(--shadow-2); }
  .gate b { font-size: 1.02rem; display: block; }
  .gate p { margin: .3rem 0 0; color: var(--muted); font-size: .84rem; line-height: 1.6; }
  .gate .go { display: inline-block; margin-top: .55rem; font-size: .84rem; font-weight: 600; color: var(--teal);
              transition: transform .18s var(--ease); }
  .gate:hover .go { transform: translateX(3px); }
  .gate.mid .go { color: var(--amber); }
  .gate.right .go { color: var(--violet); }
  .gate.req .go { color: var(--rose); }

  /* 锚值卡：只放校验值，不放条目明细（展示层仍下线） */
  .anchor { background: var(--card); border: 1px solid var(--line); border-radius: 12px;
            padding: 1rem 1.2rem; margin: 1.4rem 0 .2rem; box-shadow: var(--shadow-1); }
  .anchor .label { font-size: .76rem; color: var(--muted); letter-spacing: .05em; }
  .anchor .val { font-family: var(--mono); font-size: .79rem; word-break: break-all; margin: .3rem 0 0; }
  .anchor .meta { display: flex; flex-wrap: wrap; gap: .3rem 1.6rem; margin-top: .75rem;
                  padding-top: .7rem; border-top: 1px solid var(--line);
                  font-size: .82rem; color: var(--muted); }
  .anchor .meta b { color: var(--ink); font-weight: 600; }

  /* 访问计数：一行字。不做卡片、不做分页分布、不做图表——它是次数，不是指标 */
  .visits { text-align: center; color: var(--muted); font-size: .82rem;
            margin: 2rem 0 0; letter-spacing: .02em; }
  .visits b { color: var(--ink); font-weight: 600; font-family: var(--mono);
              font-variant-numeric: tabular-nums; }

  /* 页首「未生效」标注：全站每页都有，压在最上面，比页头更靠前 */
  .notice { background: #fbf7ec; border-bottom: 1px solid #e8dfc8; }
  .notice .wrap { display: flex; flex-wrap: wrap; align-items: baseline;
                  gap: .2rem .9rem; padding: .55rem 2rem; max-width: 60rem;
                  font-size: .82rem; color: #6b5b33; }
  .notice b { color: #4a3e20; font-weight: 600; }
  .notice a { color: #8a6d1f; }

  /* 公示页：状态卡 + 三份文本入口 + 生效条件 */
  .status { background: var(--card); border: 1px solid var(--line); border-radius: 12px;
            padding: .3rem 1.2rem; margin: 1.4rem 0 .4rem; box-shadow: var(--shadow-1); }
  .status .row { display: flex; flex-wrap: wrap; gap: .2rem 1rem; align-items: baseline;
                 padding: .55rem 0; border-top: 1px solid var(--line); font-size: .88rem; }
  .status .row:first-child { border-top: 0; }
  .status .k { color: var(--muted); min-width: 6.5rem; font-size: .82rem; }
  .status .v { color: var(--ink); font-weight: 500; }
  .status .v.hot { color: #8a5a00; }
  .status .v.mono { font-family: var(--mono); font-size: .8rem; word-break: break-all; }
  .docs { display: grid; gap: .7rem; margin: 1.2rem 0 .4rem; }
  .doccard { display: block; background: var(--card); border: 1px solid var(--line);
             border-left: 5px solid var(--teal); border-radius: 12px; padding: .85rem 1.1rem;
             text-decoration: none; color: var(--ink); box-shadow: var(--shadow-1);
             transition: transform .18s var(--ease), box-shadow .18s var(--ease); }
  .doccard:hover { transform: translateY(-2px); box-shadow: var(--shadow-2); }
  .doccard b { font-size: 1rem; }
  .doccard .ver { font-family: var(--mono); font-size: .76rem; color: var(--teal);
                  margin-left: .6rem; }
  .doccard p { margin: .3rem 0 0; color: var(--muted); font-size: .84rem; }
  .doccard .meta { display: block; margin-top: .45rem; color: var(--muted);
                   font-size: .76rem; font-family: var(--mono); word-break: break-all; }
  .doccard .go { display: inline-block; margin-top: .45rem; font-size: .84rem;
                 font-weight: 600; color: var(--teal); }
  .conds { width: 100%; border-collapse: collapse; font-size: .85rem; margin: .8rem 0 .2rem; }
  .conds th, .conds td { border: 1px solid var(--line); padding: .5rem .6rem;
                         text-align: left; vertical-align: top; line-height: 1.65; }
  .conds th { background: var(--card); font-weight: 600; }
  .conds td.st { white-space: nowrap; font-size: .82rem; }
  .conds .no { color: #8a5a00; }
  .conds .yes { color: var(--teal); }

  /* 公示正文：法律文本的排版。比站点正文更松的行距、更小的字号 */
  .doc { max-width: 47rem; margin: 1.2rem 0 0; }
  .doc h2 { font-size: 1.14rem; margin: 2.2rem 0 .7rem; padding-top: 1rem;
            border-top: 1px solid var(--line); line-height: 1.5; }
  .doc h3 { font-size: 1.0rem; margin: 1.7rem 0 .5rem; line-height: 1.5; }
  .doc h4 { font-size: .94rem; margin: 1.3rem 0 .4rem; }
  .doc p { margin: .6rem 0; line-height: 1.9; font-size: .93rem; }
  .doc blockquote { margin: 1rem 0; padding: .75rem 1.05rem; background: var(--card);
                    border-left: 3px solid var(--teal); border-radius: 0 8px 8px 0; }
  .doc blockquote p { margin: .35rem 0; font-size: .86rem; color: var(--muted);
                      line-height: 1.75; }
  .doc ul, .doc ol { margin: .55rem 0 .55rem 1.3rem; font-size: .92rem; line-height: 1.85; }
  .doc li { margin: .2rem 0; }
  .doc code { font-family: var(--mono); font-size: .84rem; background: var(--bg);
              border: 1px solid var(--line); border-radius: 5px; padding: .05rem .3rem;
              word-break: break-word; }
  .doc del { color: var(--muted); }
  .doc hr { border: 0; border-top: 1px solid var(--line); margin: 1.7rem 0; }
  .doc .tw { overflow-x: auto; margin: 1rem 0; -webkit-overflow-scrolling: touch; }
  .doc table { border-collapse: collapse; width: 100%; font-size: .82rem; }
  .doc th, .doc td { border: 1px solid var(--line); padding: .4rem .55rem;
                     text-align: left; vertical-align: top; line-height: 1.65; }
  .doc th { background: var(--card); font-weight: 600; }
  .doc mark.tbd { background: #fdf0d5; color: #8a5a00; padding: 0 .18rem; border-radius: 3px; }
  .doc pre.code { background: var(--bg); border: 1px solid var(--line); border-radius: 8px;
                  padding: .7rem .9rem; overflow-x: auto; font-size: .8rem; line-height: 1.6; }
  .docmeta { background: var(--card); border: 1px solid var(--line); border-radius: 12px;
             padding: .8rem 1.1rem; margin: 1.4rem 0 .2rem; font-size: .8rem; color: var(--muted); }
  .docmeta .val { font-family: var(--mono); color: var(--ink); word-break: break-all;
                  font-size: .78rem; }
  .docmeta div + div { margin-top: .4rem; }

  /* 需求发布（/requests）：一单一卡。信息密度刻意低于账本页——这里要能一眼扫完「还缺什么」 */
  .filters { display: flex; flex-wrap: wrap; gap: .4rem; margin: 1rem 0 .2rem; }
  .chip { display: inline-block; padding: .28rem .75rem; border: 1px solid var(--line);
          border-radius: 999px; font-size: .8rem; color: var(--muted); text-decoration: none;
          transition: border-color .15s, color .15s, background .15s; }
  .chip:hover { border-color: var(--teal); color: var(--teal); }
  .chip.on { background: var(--teal); border-color: var(--teal); color: #fff; }
  .reqcard { display: block; background: var(--card); border: 1px solid var(--line);
             border-left: 5px solid var(--teal); border-radius: 12px; padding: .9rem 1.1rem;
             margin: .7rem 0; text-decoration: none; color: var(--ink); box-shadow: var(--shadow-1);
             transition: box-shadow .18s var(--ease), transform .18s var(--ease); }
  .reqcard:hover { box-shadow: var(--shadow-2); transform: translateY(-1px); }
  .reqcard .top { display: flex; flex-wrap: wrap; align-items: baseline; gap: .5rem; }
  .reqcard .cat { font-family: var(--mono); font-size: .76rem; color: var(--teal); }
  .reqcard p { margin: .45rem 0 0; font-size: .9rem; line-height: 1.75; white-space: pre-wrap; }
  .reqcard .meta { display: block; margin-top: .5rem; color: var(--muted);
                   font-size: .76rem; font-family: var(--mono); word-break: break-all; }
  .st { display: inline-block; padding: .1rem .5rem; border-radius: 999px; font-size: .74rem;
        border: 1px solid var(--line); color: var(--muted); white-space: nowrap; }
  .st.open { border-color: var(--teal); color: var(--teal); }
  .st.claimed { border-color: var(--violet); color: var(--violet); }
  .st.delivered, .st.closed { border-color: var(--ink); color: var(--ink); }
  .empty { background: var(--card); border: 1px dashed var(--line); border-radius: 12px;
           padding: 1.1rem 1.2rem; margin: 1rem 0; color: var(--muted); font-size: .88rem; }
  /* 一单的轨迹：按 seq 排下来，每行一条 */
  .tl { list-style: none; padding: 0; margin: 1rem 0 .2rem; }
  .tl li { position: relative; padding: .55rem 0 .55rem 1.4rem;
           border-top: 1px solid var(--line); font-size: .86rem; }
  .tl li:first-child { border-top: 0; }
  .tl li::before { content: ""; position: absolute; left: .25rem; top: 1rem;
                   width: 7px; height: 7px; border-radius: 50%; background: var(--teal); }
  .tl time { color: var(--muted); font-family: var(--mono); font-size: .76rem; margin-left: .5rem; }
  .hash { font-family: var(--mono); font-size: .74rem; word-break: break-all; color: var(--muted); }

  /* ── v1.9（2026-11-15 夜）：按用户第二版原型重排主页——毛玻璃公告条、
     四张大按钮 + 悬停预览、底部数据条。逻辑照搬原型，数据全部现取，不摆假数。 */

  /* 整页淡染：四个角落各一团品牌色（静态，不做动画）。毛玻璃的「玻璃感」
     需要背后有东西可糊，平面底色上 blur 是看不出来的。 */
  .wash { position: fixed; inset: 0; z-index: -1; pointer-events: none;
          background:
            radial-gradient(38rem 26rem at 12% 6%, rgba(15, 118, 110, .10), transparent 60%),
            radial-gradient(34rem 24rem at 88% 14%, rgba(109, 90, 224, .10), transparent 60%),
            radial-gradient(30rem 22rem at 16% 88%, rgba(214, 69, 112, .07), transparent 60%),
            radial-gradient(30rem 22rem at 82% 90%, rgba(217, 119, 6, .07), transparent 60%); }

  /* 公告条：徽标 + 最新一条公告（点了去公告页）+ 法务两链 + 协议版本 */
  .topbar { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem .9rem;
            margin: 1.4rem 0 0; padding: .7rem 1.1rem;
            background: rgba(255, 255, 255, .72);
            -webkit-backdrop-filter: blur(16px) saturate(1.15);
            backdrop-filter: blur(16px) saturate(1.15);
            border: 1px solid rgba(255, 255, 255, .85); border-radius: 14px;
            box-shadow: var(--shadow-1); font-size: .86rem; }
  .topbar .ttag { flex: none; font-size: .76rem; font-weight: 700; color: var(--teal);
                  background: #e2f4f2; border-radius: 999px; padding: .22rem .7rem; }
  .topbar .ann { flex: 1; min-width: 0; color: var(--ink); text-decoration: none;
                 white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .topbar .ann:hover { color: var(--teal); }
  .topbar .tlegal { flex: none; font-size: .8rem; color: var(--muted); white-space: nowrap; }
  .topbar .tlegal a { color: var(--muted); text-decoration: none; }
  .topbar .tlegal a:hover { color: var(--teal); }
  .topbar .tver { flex: none; font-size: .78rem; font-weight: 700; color: var(--teal); }
  @media (max-width: 640px) { .topbar .ann { flex-basis: 100%; order: 4; } }

  /* 四张主入口：毛玻璃大按钮 + 悬停翻出内容预览（触屏无悬停，预览层直接不渲染进显示）。
     .gate 仍是子页入口卡的样式，这里另起 .hub，两套互不牵连。 */
  .hub { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin: 1.4rem 0 .3rem; }
  @media (max-width: 640px) { .hub { grid-template-columns: 1fr; } }
  .hubbtn { position: relative; display: flex; flex-direction: column; align-items: flex-start;
            gap: .55rem; padding: 1.3rem 1.35rem; border-radius: 16px; overflow: hidden;
            text-decoration: none; color: var(--ink);
            background: rgba(255, 255, 255, .66); border: 1px solid rgba(255, 255, 255, .9);
            -webkit-backdrop-filter: blur(14px) saturate(1.2);
            backdrop-filter: blur(14px) saturate(1.2);
            box-shadow: var(--shadow-1);
            transition: transform .3s var(--ease), box-shadow .3s var(--ease); }
  .hubbtn:hover { transform: translateY(-3px); box-shadow: var(--shadow-2); }
  .hubbtn .ic { width: 3rem; height: 3rem; flex: none; display: flex; align-items: center;
                justify-content: center; border-radius: .8rem; font-size: 1.25rem;
                font-weight: 700; color: #fff; box-shadow: 0 2px 10px rgba(15, 118, 110, .18); }
  .hubbtn.hb0 .ic { background: var(--teal); }
  .hubbtn.hb1 .ic { background: var(--violet); }
  .hubbtn.hb2 .ic { background: var(--rose); }
  .hubbtn.hb3 .ic { background: var(--amber); }
  .hubbtn b { font-size: 1.05rem; letter-spacing: .02em; }
  .hubbtn .hsub { margin: 0; color: var(--muted); font-size: .84rem; line-height: 1.6; }
  .hubbtn .hgo { font-size: .84rem; font-weight: 600; color: var(--teal); }
  .hubbtn .pv { position: absolute; inset: 0; z-index: 1; display: flex; flex-direction: column;
                gap: .45rem; padding: 1.1rem 1.2rem; background: rgba(255, 255, 255, .94);
                -webkit-backdrop-filter: blur(18px); backdrop-filter: blur(18px);
                opacity: 0; transform: translateY(12px); pointer-events: none;
                transition: opacity .3s var(--ease), transform .3s var(--ease); }
  .hubbtn:hover .pv { opacity: 1; transform: translateY(0); }
  .hubbtn .pv b { color: var(--teal); font-size: .95rem; }
  .hubbtn .pv i { font-style: normal; font-size: .82rem; color: var(--muted);
                  background: var(--bg); border-radius: 8px; padding: .38rem .6rem;
                  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .hubbtn .pv .more { margin-top: auto; font-size: .8rem; font-weight: 700; color: var(--teal); }
  @media (hover: none) { .hubbtn .pv { display: none; } }

  /* 底部数据条：数字全部现取，取不到的那格不渲染（不显示 0，不显示占位符） */
  .databar { display: flex; flex-wrap: wrap; align-items: baseline; gap: .6rem 1.8rem;
             margin: 1.4rem 0 .2rem; padding: .9rem 1.2rem;
             background: rgba(255, 255, 255, .72);
             -webkit-backdrop-filter: blur(16px) saturate(1.15);
             backdrop-filter: blur(16px) saturate(1.15);
             border: 1px solid rgba(255, 255, 255, .85); border-radius: 14px;
             box-shadow: var(--shadow-1); }
  .databar .dl { font-size: .84rem; font-weight: 700; color: var(--ink); flex: none; }
  .databar .dstat { display: flex; align-items: baseline; gap: .4rem; }
  .databar .num { font-size: 1.15rem; font-weight: 800; color: var(--teal);
                  font-family: var(--mono); font-variant-numeric: tabular-nums; }
  .databar .lbl { font-size: .78rem; color: var(--muted); }

  /* 公告页（/notices）：一卡一条，左侧品牌色竖线 + 标签 + 日期 */
  .notecard { display: block; background: var(--card); border: 1px solid var(--line);
              border-left: 4px solid var(--teal); border-radius: 12px;
              padding: 1rem 1.2rem; margin: .8rem 0; text-decoration: none; color: var(--ink);
              box-shadow: var(--shadow-1);
              transition: transform .18s var(--ease), box-shadow .18s var(--ease); }
  .notecard:hover { transform: translateY(-2px); box-shadow: var(--shadow-2); }
  .notecard .ntag { display: inline-block; font-size: .74rem; font-weight: 600;
                    color: var(--teal); background: #e2f4f2; border-radius: 999px;
                    padding: .12rem .6rem; }
  .notecard h3 { font-size: 1rem; margin: .45rem 0 .3rem; line-height: 1.5; }
  .notecard p { margin: 0; color: var(--muted); font-size: .86rem; line-height: 1.7; }
  .notecard .ndate { margin-top: .5rem; font-size: .76rem; color: var(--muted);
                     font-family: var(--mono); }

  /* 欢迎引导页是独立文档（render_welcome），样式自带 WELCOME_CSS——
     与站点 CSS 零共享，这里不再有它的任何规则。 */
"""

# 页面文案里的固定串。三页共用，改一处即可。

FOOTER = ('<footer class="wrap" style="margin-top:1.8rem">\n'
          '  <span class="plain">© 2026 老夫 ｜ 众汲之井 ｜ drawcommons.org ｜ '
          '测试期 · 库内为结构样例</span>\n</footer>')
# 署名仍用笔名原字：署名权包含「以何种方式署名」，英文页把笔名音译一遍等于
# 造出第二个名字，反而对不上著作权声明里的那个署名。
EN_FOOTER = ('<footer class="wrap" style="margin-top:1.8rem">\n'
             '  <span class="plain">© 2026 老夫 (pen name) ｜ Zhong Ji Zhi Jing ｜ '
             'drawcommons.org ｜ Beta · entries are structural samples</span>\n'
             '</footer>')

# ── 导航：一处生成，全部页面共用 ────────────────────────────────────────────
# 四张并列的主页——贡献与参与者 / 账本数据查询 / 测试与验证 / 需求发布。
# 「需求发布」原叫「还缺什么」，2026-11-15 改名并升为并列页：旧名字只说了这一页
# 被动的一半（这里能看到别人缺什么），读不出「我也可以发一条」，而发单才是它的
# 写入动机。**名字改了，正文就得真的回答「怎么发」**，否则是标题许诺、正文不接。
# 顺序只在这里写一次：以前每页各写一个常量，加一页要改五处，漏一处就出现
# 「这页能到、那页到不了」——2026-11-15 加「测试与验证」时正是这么漏的。
NAV_ITEMS = {
    "zh": [
        ("contributors", "/contributors", "贡献与参与者"),
        ("ledger", "/ledger", "账本数据查询"),
        ("testing", "/testing", "测试与验证"),
        ("requests", "/requests", "需求发布"),
    ],
    # 英文站与中文一一对应，四页对四页。`/en/requests` 是这一轮新加的：
    # 以前英文导航刻意不列需求页（没有英文版，链过去 404 比不链更糟），
    # 现在有英文页了，缺它反而成了「英文站少一个入口」。
    "en": [
        ("contributors", "/en/contributors", "Contributors"),
        ("ledger", "/en/ledger", "Ledger data"),
        ("testing", "/en/testing", "Testing &amp; verification"),
        ("requests", "/en/requests", "Requests"),
    ],
}


def _nav(skip: str = "", *, lang: str = "zh", back: str = "",
         lang_href: str = "/en/home") -> str:
    """生成导航条。``skip`` 是当前页——不链自己，链了读者会以为自己没点动。"""
    bits = ([back] if back else []) + [
        f'<a href="{href}">{label}</a>'
        for key, href, label in NAV_ITEMS[lang] if key != skip
    ]
    bits.append(f'<a href="{lang_href}">{"中文" if lang == "en" else "English"}</a>')
    return '<div class="nav">' + '<span class="sep">/</span>'.join(bits) + "</div>"


NAV_HOME = _nav(lang_href="/en/home")
NAV_CONTRIB = _nav("contributors", back='<a href="/home">← 返回首页</a>',
                   lang_href="/en/contributors")
NAV_LEDGER = _nav("ledger", back='<a href="/home">← 返回首页</a>', lang_href="/en/ledger")
NAV_TESTING = _nav("testing", back='<a href="/home">← 返回首页</a>', lang_href="/en/testing")
NAV_REQUESTS = _nav("requests", back='<a href="/home">← 返回首页</a>', lang_href="/en/requests")
NAV_REQUEST_ONE = _nav("requests", back='<a href="/requests">← 需求发布</a>')
# 英文页的导航与中文一一对应：子页回到英文首页，语言切换落到同一页的中文版
NAV_EN_HOME = _nav(lang="en", lang_href="/home")
NAV_EN_CONTRIB = _nav("contributors", lang="en", back='<a href="/en/home">← Back</a>',
                      lang_href="/contributors")
NAV_EN_LEDGER = _nav("ledger", lang="en", back='<a href="/en/home">← Back</a>',
                     lang_href="/ledger")
NAV_EN_TESTING = _nav("testing", lang="en", back='<a href="/en/home">← Back</a>',
                      lang_href="/testing")
NAV_EN_REQUESTS = _nav("requests", lang="en", back='<a href="/en/home">← Back</a>',
                       lang_href="/requests")

# 首页「井」字右边那一行：测试期在找哪几类帮忙。
# 项目里最容易说错的一句是「给予署名权」——署名权是著作权项下的权利，
# 咨询、报错、出服务器这些不产生作品，没有署名权可给。所以这里分开写：
# 能构成作品的按署名权，不构成作品的记名并注明做了什么。**不合并成一句好听的。**


def _hero(title: str, sub: str, *, brand: bool = False, badges=None,
          nav: str = "", ask: str = "") -> str:
    """各页共用顶栏。首页带井字标（与旁边那行「在找什么」）、状态标签；子页带导航。"""
    cls = "hero" if brand else "hero slim"
    out = [f'<div class="{cls}">', '<div class="wrap">']
    if brand:
        brand_html = '<div class="brand" aria-hidden="true">井</div>'
        if ask:
            out.append(f'<div class="brandrow">{brand_html}'
                       f'<p class="ask">{ask}</p></div>')
        else:
            out.append(brand_html)
    if nav:
        out.append(nav)
    out.append(f"<h1>{esc(title)}</h1>")
    out.append(f'<p class="sub">{esc(sub)}</p>')
    if badges:
        out.append('<ul class="badges">'
                   + "".join(f"<li>{esc(b)}</li>" for b in badges)
                   + "</ul>")
    out += ["</div>", "</div>"]
    return "".join(out)


def _page(title: str, desc: str, hero: str, body: str, path: str,
          lang: str = "zh-CN", footer: str = FOOTER) -> bytes:
    """拼一张完整页面。head 与 footer 只此一份，不随页复制。

    ``footer`` 可换：英文页的页脚不能混着中文，否则一张英文页的最后一行
    还是中文，读起来像没翻完。
    欢迎引导已拆成独立文档（render_welcome，见 ``WELCOME_CSS`` 处的说明），
    站点页面不再内嵌它——``<main id="main">`` 保留，子页锚点仍有落点。
    """
    html = (
        f"<!doctype html>\n<html lang=\"{lang}\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<meta name=\"robots\" content=\"noindex, nofollow\">\n"
        f'<meta name="description" content="{esc(desc)}">\n'
        f'<link rel="canonical" href="https://drawcommons.org{path}">\n'
        f"<title>{esc(title)}</title>\n"
        f"<style>{BASE_CSS}</style>\n"
        f"<style>{PAGE_CSS}</style>\n"
        "</head>\n<body>\n"
        f"{_notice_bar('en' if lang == 'en' else 'zh')}\n"
        f'<main id="{WELCOME_MAIN_ID}">\n'
        f"{hero}\n"
        f'<div class="wrap">\n{body}\n</div>\n'
        f"{footer}\n"
        "</main>\n"
        "</body>\n</html>"
    )
    return html.encode("utf-8")
# ─────────────────────── 页面文案：独立文件（2026-11-15）───────────────────────
# 标题、页头与正文不再写在本文件里，改成一页一个文件：
#     content/<lang>/<page>.html      （容器里挂载自 ./app/content）
# 改一句文案就只改那个文件——不碰读库的代码、不重建镜像、不重启写入面。
# 取文件按 mtime+size 缓存，存盘即生效。
#
# 为什么不放进数据库、也不在服务器上手改：仓库必须是唯一源。文案进了库或只在
# 线上改，这句话就没有版本、没有审查，复现包也带不上——与账本「只追加、不可
# 改写」的规矩正好相反。文件在 git 里，diff 看得见，回滚是真回滚。
#
# 文件格式（front-matter + 原样 HTML 正文）：
#     ---
#     path: /home
#     lang: zh-CN
#     title: ...        （<title>）
#     desc: ...         （meta description）
#     hero_title: ...   （页头 h1，转义后输出）
#     hero_sub: ...     （页头副标题，转义后输出）
#     ask: ...          （可选；首页「在找什么」那行，允许 <b> 与 <a>）
#     ---
#     <正文 HTML，可用 __TOPBAR__ / __STATS__ / __ANCHOR__ / __EN_NOTE__ 插槽>
#
# 要读库的那几块留在 py 里生成，填进插槽。填不上、插槽名拼错、站内链接跳不到，
# **一律在启动时报错**：页面上残留一个没替换的插槽，比整页 500 更难被发现。
CONTENT_DIR = os.environ.get("CONTENT_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "content")

# PAGES 只收零参函数，带查询参数与静态资源不在那张表里，但它们确实可跳。
_EXTRA_ROUTES = ("/requests", "/en/requests", "/download/", "/images/",
                 "/api/v1/", "/agent.md", "/sign/", "/healthz", "/repo.git")

_KNOWN_SLOTS = {"TOPBAR", "STATS", "ANCHOR", "EN_NOTE"}
_SLOT_RE = re.compile(r"__([A-Z][A-Z0-9_]*)__")
_HREF_RE = re.compile(r'href="([^"]+)"')
_content_cache: dict = {}


class ContentError(RuntimeError):
    """内容文件不合规。故意让它在启动时就炸：死链与拼错的插槽不该上线。"""


def _split_front_matter(text: str, rel: str):
    if not text.startswith("---\n"):
        raise ContentError(f"{rel}：文件必须以 --- 开头的 front-matter 起手")
    end = text.find("\n---\n", 3)
    if end < 0:
        raise ContentError(f"{rel}：front-matter 没有闭合的 --- 行")
    meta = {}
    for i, line in enumerate(text[4:end].splitlines(), 2):
        if not line.strip():
            continue
        if ":" not in line:
            raise ContentError(f"{rel}：头部第 {i} 行不是「key: value」")
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip()
    for need in ("path", "lang", "title", "desc", "hero_title", "hero_sub"):
        if not meta.get(need):
            raise ContentError(f"{rel}：头部缺 {need}")
    return meta, text[end + 5:]


def _check_links(rel: str, body: str) -> None:
    """站内链接必须跳得到；跳不到就不让启动——死链比少一页更难查。"""
    for href in _HREF_RE.findall(body):
        if href.startswith(("#", "http://", "https://", "mailto:")):
            continue
        if not href.startswith("/"):
            raise ContentError(f"{rel}：链接要写站内绝对路径或完整 URL，当前是 {href!r}")
        target = href.split("?")[0].split("#")[0]
        if target in PAGES or target.rstrip("/") in PAGES:
            continue
        if any(target.startswith(p) for p in _EXTRA_ROUTES):
            continue
        raise ContentError(f"{rel}：站内链接指向不存在的路由 {href}")


def content(lang: str, name: str):
    """取一页的 (meta, body)。文件没动不重读，动了立刻生效。"""
    rel = f"{lang}/{name}.html"
    fp = os.path.join(CONTENT_DIR, rel)
    try:
        st = os.stat(fp)
    except OSError:
        raise ContentError(f"缺内容文件：{fp}（CONTENT_DIR={CONTENT_DIR}）")
    stamp = (st.st_mtime_ns, st.st_size)
    hit = _content_cache.get(rel)
    if hit and hit[0] == stamp:
        return hit[1], hit[2]
    with open(fp, encoding="utf-8", newline="") as fh:
        text = fh.read()
    # Windows 记事本默认存 CRLF。**在读取处统一成 LF**，而不是拒绝 CRLF：
    # 改文案的人不该因为「用错了编辑器」就看见站点起不来。归一化只作用于
    # 内存里的文本，文件本身不动。
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    meta, body = _split_front_matter(text, rel)
    want = f"/{name}" if lang == "zh" else f"/en/{name}"
    if meta["path"] != want:
        raise ContentError(f"{rel}：path 写的是 {meta['path']}，按文件名应为 {want}")
    unknown = set(_SLOT_RE.findall(body)) - _KNOWN_SLOTS
    if unknown:
        raise ContentError(
            f"{rel}：不认识的插槽 {sorted(unknown)}（认识的只有 {sorted(_KNOWN_SLOTS)}）")
    _check_links(rel, body)
    _content_cache[rel] = (stamp, meta, body)
    return meta, body


def _fill(body: str, rel: str, **slots) -> str:
    for k, v in slots.items():
        body = body.replace(f"__{k}__", v)
    left = sorted(set(_SLOT_RE.findall(body)))
    if left:
        raise ContentError(f"{rel}：插槽没填 {left}")
    return body


def _validate_content() -> int:
    """启动自检：逐文件解析 + 插槽 + 链接，并核对中英成对。返回页数。"""
    seen = {}
    for lang in ("zh", "en"):
        d = os.path.join(CONTENT_DIR, lang)
        if os.path.isdir(d):
            seen[lang] = sorted(f[:-5] for f in os.listdir(d) if f.endswith(".html"))
    if len(seen) == 2:
        only = sorted(set(seen["zh"]) ^ set(seen["en"]))
        if only:
            raise ContentError(f"中英不成对，只在一边有：{only}")
    n = 0
    for lang, names in seen.items():
        for name in names:
            content(lang, name)
            n += 1
    return n




# 2026-11-14 结构升级把锚值换了，需要让「拿着旧值来比对」的人在这页就看到说明。
# 挂在锚值卡下面，不挂全站通知条：那条讲的是「协议尚未生效」，两件事混在一句里
# 会让人以为结构升级跟生效状态有关。
# **旧值不写在这里**——一页摆两个锚值，会被读成「两个都算数」。旧值在公告与
# CHANGELOG 里，这一页只留当前值，加一条指向公告的链接。
ANCHOR_NOTE = {
    "zh": ('<p class="plain" style="margin:.75rem 0 0;font-size:.82rem">'
           "2026-11-14 结构升级后锚值已变更，此前公布的值作废 —— "
           '<a href="/download/notice-20261114.md">公告与逐字段对照</a></p>'),
    "en": ('<p class="plain" style="margin:.75rem 0 0;font-size:.82rem">'
           "A structural upgrade on 2026-11-14 changed the anchor; earlier values are void. "
           'See the <a href="/download/notice-20261114.md">notice and the field-by-field diff</a>'
           " (in Chinese).</p>"),
}


def _anchor_card(lang: str = "zh") -> str:
    """锚值卡。只读内存里算好的值，不在这里跑 verify（那是 O(n) 全链重算）。"""
    if LEDGER is None:
        if lang == "en":
            return ('<div class="anchor"><div class="label">Ledger data</div>'
                    '<p class="plain" style="margin:.3rem 0 0">'
                    "The data layer is temporarily unavailable; the endpoints return 503. "
                    "This page still renders.</p></div>")
        return ('<div class="anchor"><div class="label">账本数据</div>'
                '<p class="plain" style="margin:.3rem 0 0">'
                "数据层暂时不可用，接口返回 503。页面照常可读。</p></div>")
    if lang == "en":
        return (
            '<div class="anchor">'
            '<div class="label">Current anchor · sha256 of /api/ledger/export</div>'
            f'<div class="val">{esc(LEDGER.export_sha256)}</div>'
            '<div class="meta">'
            f"<span>entries <b>{len(LEDGER.chain)}</b> (samples, fake IDs)</span>"
            f"<span>counter-signed <b>{len(LEDGER.confirmations)}</b></span>"
            '<span>chain check <b><a href="/api/ledger/verify">see the result</a></b></span>'
            '<span>exported bytes <b><a href="/api/ledger/export">/api/ledger/export</a></b></span>'
            "</div>"
            + ANCHOR_NOTE["en"]
            + "</div>"
        )
    return (
        '<div class="anchor">'
        '<div class="label">当前锚值 · /api/ledger/export 的 sha256</div>'
        f'<div class="val">{esc(LEDGER.export_sha256)}</div>'
        '<div class="meta">'
        f"<span>条目 <b>{len(LEDGER.chain)}</b> 条（样例，假 ID）</span>"
        f"<span>受方确认 <b>{len(LEDGER.confirmations)}</b> 条</span>"
        '<span>链校验 <b><a href="/api/ledger/verify">点开看结果</a></b></span>'
        '<span>导出原文 <b><a href="/api/ledger/export">/api/ledger/export</a></b></span>'
        "</div>"
        + ANCHOR_NOTE["zh"]
        + "</div>"
    )


# ── 公告（v1.9，2026-11-15 夜）───────────────────────────────────────────────
# 公告正文是 /download/ 下的静态文件（Caddy 直服，不碰代码不重启）——那个口子是
# 2026-11-14 立的。这一张表只做「索引」：哪天发过什么、去哪读。页面上渲染的
# 每一个字都必须能对上表里的某一条；新增公告在这里加一行，最新一条同时出现在
# 主页公告条上（_topbar 取的是 NOTICES[0]，不是另抄的一份文字）。
# **日期与标题写错比没有这张表更糟**：它挂着正式公告的名义。
NOTICES = [
    {
        "date": "2026-11-14",
        "tag": "协议",
        "title": "协议文本变更公告：三件套 r5 → r6，业务数值回填",
        "desc": "不改变任何条款的结构、编号与既有文字，只把此前留待确定的业务参数"
                "（笔数上限、准入、责任上限、管辖）与两处经律师确认的数值写进正文；"
                "公示文本已同步更新，公示期自 11-14 重新起算。",
        "href": "/download/notice-20261114b.md",
    },
    {
        "date": "2026-11-14",
        "tag": "账本",
        "title": "账本结构升级公告：新增需求单、主体公钥列、受方确认三处结构",
        "desc": "既有条目字段值逐条未变（51 处逐一对照）；导出件顶层新增 "
                "confirmations 数组，锚值随之变更，此前公布的值作废——"
                "逐字段对照见公告正文。",
        "href": "/download/notice-20261114.md",
    },
]
NOTICES_EN_NOTE = ("Notices are published in Chinese; the notice files are the authoritative "
                   "versions.")

def _topbar(lang: str = "zh") -> str:
    """主页公告条。取 NOTICES[0] 当「最新一条」——两处共享一份数据，不各抄一份。

    法务两链不分语言都指中文页：协议正文只有中文版（英文页一直这么处理，
    挂「(Chinese)」说明），链到不存在的 /en/terms/* 反而是造死链。
    """
    en = lang == "en"
    latest = NOTICES[0]
    title = "Privacy policy" if en else "隐私政策"
    agree = "User agreement" if en else "用户协议"
    ver = "v2.1 r6"
    ann_text = (f"{latest['title']} ({latest['date']}) — notice in Chinese" if en
                else f"{latest['title']}（{latest['date']}）")
    return (
        '<div class="topbar">'
        f'<span class="ttag">{"📢 Notice" if en else "📢 公告"}</span>'
        f'<a class="ann" href="{"/en/notices" if en else "/notices"}">{esc(ann_text)}</a>'
        '<span class="tlegal">'
        f'<a href="/terms/privacy">{title}</a> · <a href="/terms/agreement">{agree}</a></span>'
        f'<span class="tver">{ver}</span>'
        "</div>"
    )


def _stats_bar(lang: str = "zh") -> str:
    """主页底部数据条。四个数全部现取：访问者 / 账本条目 / 受方确认 / 公示天数。

    取不到的格子不渲染——不显示 0，不显示占位符（「0」会被读成「没人来」，
    而真实情况是「没在数」）。公示天数从 DISCLOSURE_START 现算，是唯一
    不依赖任何存储的格子。
    """
    en = lang == "en"
    stats = []
    n = VISITS.total()
    if n:
        stats.append((f"{n:,}", "访问者" if not en else "visitors"))
    if LEDGER is not None:
        stats.append((str(len(LEDGER.chain)), "账本条目" if not en else "ledger entries"))
        stats.append((str(len(LEDGER.confirmations)),
                      "受方确认" if not en else "counter-signed"))
    d0 = datetime.date.fromisoformat(DISCLOSURE_START)
    day = (datetime.date.today() - d0).days + 1
    stats.append((f"第 {day} 天" if not en else f"day {day}",
                  "协议公示进行中" if not en else "of protocol disclosure"))
    inner = "".join(
        f'<span class="dstat"><span class="num">{esc(a)}</span>'
        f'<span class="lbl">{esc(b)}</span></span>'
        for a, b in stats)
    return ('<div class="databar"><span class="dl">'
            + ("📈 Data" if en else "📈 数据")
            + "</span>" + inner + "</div>")



CONTRIB_BODY = """
<p class="plain"><b>本页记录谁支持了这个项目，不是账本里「谁帮过谁」。</b>
   名录分三类：写代码与文档的、录数据的、出设备/服务器/场地的。前两类构成著作权意义上的贡献，
   署名是既有权利；第三类不产生作品，只承诺列名、注明形式、可随时撤回，不承诺永久。</p>
<p class="plain"><b>只接受非现金支持：</b>实物、劳务、服务——服务器、带宽、设备、场地、人力。
   不收现金、不设收款口、不代收代付，账本无金额字段。名录记的是「谁出了什么」，不是「谁给了多少钱」。</p>
<ul class="links">
  <li><a href="/download/CREDITS.md">/download/CREDITS.md</a><span>名录全文：三类人、依据、认领与退出、逐版快照</span></li>
  <li><a href="/download/credits.json">/download/credits.json</a><span>机器可读的同一条记录，可与仓库那份逐字比对</span></li>
  <li><a href="/download/REVIEWS.md">/download/REVIEWS.md</a><span>审查记录：一条提交凭什么算贡献、凭什么进名录</span></li>
  <li><a href="/download/reviews.json">/download/reviews.json</a><span>审查记录的机器可读副本，字段与约束见上一份</span></li>
</ul>
<p class="plain">进名录需过四条判据：改动可指认、作者能解释、干净环境可复现、许可与来源合规。
   审查记录同样公开，当前为空——尚无第三方提交。</p>
<p class="plain" style="margin-top:2.2rem">接着看：<a href="/ledger">账本数据查询 →</a></p>
"""

LEDGER_BODY = """
__ANCHOR__

<h2>自己验一遍</h2>
<p class="plain">页面上的锚值可自行复算，无需信任运营方：仓库公开，三条判据，不需要账号、密钥或联网取数。
   步骤见仓库根的 <code>REPRODUCE.md</code>，其中同时写明这套验证<b>不能证明什么</b>。</p>
<p class="plain"><b>复算验证的是字节，不是事实。</b>锚值只说明账本自导出起未被改动，
   不说明记录描述的事确实发生——条目默认为<b>填报方自称</b>，系统不校验填报人。
   受方再签一次（双签）证明两个主体对同一条记录各认一次；它不是「事发生过」的证明。
   事实之真，取决于当事人与证据，本站不背书。</p>
<ul class="links">
  <li><code>git clone https://drawcommons.org/repo.git</code><span>只读仓库，clone 后按 REPRODUCE.md 跑三条判据</span></li>
  <li><a href="/download/drawcommons-latest.tar.gz">/download/drawcommons-latest.tar.gz</a><span>免装 git 的复现包，同目录有 .sha256</span></li>
  <li><code>git -c gpg.ssh.allowedSignersFile=repo/allowed_signers verify-tag &lt;tag&gt;</code><span>验发布签名，把 &lt;tag&gt; 换成要验的版本；从 v2.1-rc5 起带 SSH 签名，输出里有 Good 与公钥指纹</span></li>
  <li><a href="/download/allowed_signers">/download/allowed_signers</a><span>签名公钥（不装 git 也能取）；指纹与验法见名录 §10</span></li>
</ul>

<h2>接口（只读，无需账号与密钥）</h2>
<ul class="links">
  <li><a href="/api/ledger/items">/api/ledger/items</a><span>全部账目条目，逐条带哈希</span></li>
  <li><a href="/api/ledger/verify">/api/ledger/verify</a><span>链校验结果：ok / first_bad / items</span></li>
  <li><a href="/api/ledger/export">/api/ledger/export</a><span>导出件原文，它的 sha256 就是锚值</span></li>
</ul>

<h2>说明</h2>
<p class="plain">表结构与字段定义见仓库根的 <code>spec/ddl_w4.sql</code>（建表 DDL）与
   <code>repo/spec/entry.schema.json</code>（条目规范，v2.1 合并版：一本账、三态、不含金额）；
   白皮书与协议尚未进仓库，仍在测试期修订。</p>
<p class="plain">页面由人工维护。发现错误或有改进建议，请致信
   <a href="mailto:2379731846@qq.com">2379731846@qq.com</a>。</p>
<p class="plain" style="margin-top:2.2rem">接着看：<a href="/contributors">贡献与参与者 →</a></p>
"""


# 英文三页与中文三页一一对应：同一件事只有一种说法，两边结构对得上，
# 才不会出现「中文说了、英文没说」这种半个口径。最后一行统一挂同一句：
# 中文版才是我们站得住的那一版。
EN_NOTE = ('<p class="plain" style="margin-top:1.6rem">This is the English version of the site. '
           'Where it differs from the Chinese, the Chinese text is the one we stand behind.</p>')


EN_CONTRIB_BODY = """
<p class="plain"><b>This page records who supports the project — not who helped whom in the
   ledger.</b> The list has three kinds of contributor: those who write code and documentation,
   those who enter data, and those who provide equipment, servers or venues. The first two are
   contributions in the copyright sense, and attribution is a right they already hold; the third
   produces no work, so what is promised is a listing, a note of what was provided, and withdrawal
   at any time — not permanence.</p>
<p class="plain"><b>Support is accepted in non-cash form only:</b> goods, labour and services —
   servers, bandwidth, equipment, venues, time. No cash, no payment endpoint, no collection or
   disbursement, and no amount field in the ledger. The list records who provided what, never who
   paid how much.</p>
<ul class="links">
  <li><a href="/download/CREDITS.md">/download/CREDITS.md</a><span>The full list: three kinds of
    contributor, the basis for each, claiming and withdrawal, per-release snapshots (Chinese)</span></li>
  <li><a href="/download/credits.json">/download/credits.json</a><span>The same record, machine-readable;
    can be compared word for word with the copy in the repository</span></li>
  <li><a href="/download/REVIEWS.md">/download/REVIEWS.md</a><span>Review records: what makes a
    submission count as a contribution, and what gets it into the list (Chinese)</span></li>
  <li><a href="/download/reviews.json">/download/reviews.json</a><span>The machine-readable copy of the
    review records; fields and constraints are defined in the file above</span></li>
</ul>
<p class="plain">A submission passes four tests before it enters the list: the change can be pointed
   at, the author can explain it, it works in a clean environment, and licence and provenance are
   intact. The review records are public the same way; they are currently empty — there have been no
   third-party submissions.</p>

__EN_NOTE__
<p class="plain" style="margin-top:2.2rem">Next: <a href="/en/ledger">Ledger data →</a></p>
"""

EN_LEDGER_BODY = """
__ANCHOR__

<h2>Verify it yourself</h2>
<p class="plain">The anchor on this page can be recomputed without trusting the operator: the repository
   is public, it takes three checks, and needs no account, no key and no network fetch. The steps are
   in <code>REPRODUCE.md</code> at the repository root, which also states <b>what this does not
   prove</b>.</p>
<p class="plain"><b>Recomputation verifies bytes, not facts.</b> The anchor says only that the ledger has
   not been altered since it was exported; it does not say that the events recorded happened — an entry
   is <b>self-reported</b> by default and the system does not check who filled it in. A counter-signature
   shows two parties agreed on the same words; it is not proof that the event happened. For a fact to be
   true you need the parties and the evidence; the site does not vouch for it.</p>
<ul class="links">
  <li><code>git clone https://drawcommons.org/repo.git</code><span>Read-only repository; after cloning,
    run the three checks in REPRODUCE.md</span></li>
  <li><a href="/download/drawcommons-latest.tar.gz">/download/drawcommons-latest.tar.gz</a><span>Release
    archive for reproducing without git; its .sha256 sits in the same directory</span></li>
  <li><code>git -c gpg.ssh.allowedSignersFile=repo/allowed_signers verify-tag &lt;tag&gt;</code><span>Verify
    a release signature — replace &lt;tag&gt; with the version you want; signed with SSH from v2.1-rc5
    on, and the output shows Good plus the key fingerprint</span></li>
  <li><a href="/download/allowed_signers">/download/allowed_signers</a><span>The signing public key (no
    git needed); fingerprint and how to check it are in §10 of the credits file</span></li>
</ul>

<h2>Endpoints (read-only, no account, no key)</h2>
<ul class="links">
  <li><a href="/api/ledger/items">/api/ledger/items</a><span>Every entry, each carrying its hash</span></li>
  <li><a href="/api/ledger/verify">/api/ledger/verify</a><span>Chain verification: ok / first_bad / items</span></li>
  <li><a href="/api/ledger/export">/api/ledger/export</a><span>The exported bytes; their sha256 is the anchor</span></li>
</ul>

<h2>Notes</h2>
<p class="plain">Table structure and field definitions are in <code>spec/ddl_w4.sql</code> at the repository root
   (the DDL) and
   <code>repo/spec/entry.schema.json</code> (entry spec, the v2.1 merged version: one ledger, three
   entry kinds, no amount field). The whitepaper and the protocol are not in the repository yet; they
   are still being revised during the beta.</p>
<p class="plain">These pages are maintained by hand. To report an error or suggest an improvement, write to
   <a href="mailto:2379731846@qq.com">2379731846@qq.com</a>.</p>

__EN_NOTE__
<p class="plain" style="margin-top:2.2rem">Next: <a href="/en/contributors">Contributors →</a></p>
"""



EN_BADGES = [
    "Beta — features and wording may still change",
    "Provisional name — trademark search pending",
    "No external legal opinion yet",
]


# ── /llms.txt：给 agent 的发现入口（2026-11-15）──────────────────────────────
# 为什么在根路径另开一份，而不是让 agent 自己去 /home 里翻到 /agent.md：
# 浏览器打 `/` 会 302 到三屏引导（产品决策，不改），而 agent 跟到 `/welcome`
# 只拿到 9 个字，它没有理由为一篇说明书去猜路径。`/llms.txt` 是 llmstxt.org
# 的约定位置，抓一次就够。
# 这里**不复制** /agent.md 的正文：那份约 14 KB，回答「怎么做」；这份只回答
# 「这是什么、去哪读、现在的锚值是多少」。两处都存数字，迟早各说各话，所以
# 条数与锚值一律从 LEDGER 现算——这正是复盘里抓到的「正文写 4 条、实际 6 条」
# 那类毛病，不再重犯一次。
def render_llms() -> bytes:
    if LEDGER is None:
        state = ("- 数据层暂不可用，锚值与条目数取不到；等 `/api/ledger/export`\n"
                 "  恢复后再算，不要把这一行当成「账本为空」。\n")
    else:
        state = (
            f"- 条目数：{len(LEDGER.chain)}\n"
            f"- 锚值（`/api/ledger/export` 的 sha256）：\n"
            f"  {LEDGER.export_sha256}\n"
            "- 数据性质：测试期结构验证样例（假 ID）；条数以 `/api/ledger/items`\n"
            "  的 `count` 为准（导出件里的 `data_notice` 是冻结措辞，不随条数改）\n"
            "- 自行复算：\n"
            "  `curl -s https://drawcommons.org/api/ledger/export | sha256sum`\n"
        )
    doc = f"""# 众汲之井 · DrawCommons

> 一个公开、可自行复算的互助账本：只追加、导出件取 sha256 当锚值、任何人可自己复算，
> 不必相信运营方。
> A public, append-only mutual-aid ledger. The anchor is the sha256 of the export;
> anyone can recompute it without trusting the operator.

站点 https://drawcommons.org · 本文件 https://drawcommons.org/llms.txt
面向机器的完整说明：https://drawcommons.org/agent.md （约 14 KB，含可直接跑的接入脚本）
**不想注册、只想核对数字**：https://drawcommons.org/audit.md （只读，8 项检查，一次跑完）

## 这是什么

- 只记已经发生的事：有人缺东西写一条需求单，有人补上了记一条账目，受方对那条账目签一次名
- 账本只追加；条目进哈希链；确认与条目并列、不进链
- 不做的：托管资金、撮合、评分、排名、站内私信

## 只读接口（无需账号、无需 API Key）

- `GET /api/ledger/items` — 全部条目，逐条带 hash；含 `count` / `genesis` / `data_notice`
- `GET /api/ledger/verify` — 链校验：`ok` / `first_bad` / `items` / `chain_tail`（服务端自述，可自行复算）
- `GET /api/ledger/export` — 导出件原文；它的 sha256 就是锚值
- `GET /api/v1/requests` — 需求单（`?state=open` 只看可接的）

## 现在的状态（每次请求现算，不缓存）

{state}
## 写口（需要 ed25519 签名，签名覆盖原始字节）

- `POST /api/v1/party` / `request` / `entry` / `confirm`，怎么签见 /agent.md §3
- **可以先演练**：任一端点加 `?dry_run=1`，校验全跑、事务回滚，库与 nonce 都不变，
  返回体带 `"dry_run": true`。账本只追加，写错撤不回，先演练一次是唯一便宜的保险

## 页面（给人看的，接入不必读）

- https://drawcommons.org/home — 项目说明
- https://drawcommons.org/ledger — 账本与当前锚值
- https://drawcommons.org/testing — 测试与验证
- https://drawcommons.org/terms — 三份协议正文；纯文本另有 `/terms/<key>.txt`
- 全站 `noindex`：不供搜索引擎收录，本站也不做 SEO

## 边界

- 写口需要 ed25519 签名，签名覆盖原始字节；不接受未签名写入
- 本文件是说明书，不是接口。任何数字以对应接口的返回为准
"""
    return doc.encode("utf-8")


def render_home() -> bytes:
    meta, body = content("zh", "home")
    return _page(
        meta["title"],
        meta["desc"],
        _hero(meta["hero_title"], meta["hero_sub"], brand=True, badges=BADGES,
              nav=NAV_HOME, ask=meta.get("ask", "")),
        _fill(body, "zh/home.html", TOPBAR=_topbar("zh"), STATS=_stats_bar("zh")),
        meta["path"],
    )


def render_contributors() -> bytes:
    return _page(
        "贡献与参与者 · 众汲之井",
        "这个项目由谁支撑：写代码与写文档的、录数据的、出设备出服务器出场地的，"
        "三类人各自被承诺了什么，怎么认领、怎么退出。这不是账本里记的互助。",
        _hero("贡献与参与者",
              "谁写了代码、谁录了数据、谁出了设备与服务器——以及每类人被承诺了什么。"
              "这不是账本里记的谁帮过谁。",
              nav=NAV_CONTRIB),
        CONTRIB_BODY,
        "/contributors",
    )


def render_ledger() -> bytes:
    return _page(
        "账本数据查询 · 众汲之井",
        "账本的三个只读接口、当前锚值，以及不用相信我们就能自己复算一遍的步骤。"
        "复算验的是字节，不是事情。",
        _hero("账本数据查询",
              "三个只读接口、一个锚值，和一条能自己复算的链"
              "——不需要账号、密钥，也不需要相信我们。",
              nav=NAV_LEDGER),
        LEDGER_BODY.replace("__ANCHOR__", _anchor_card()),
        "/ledger",
    )


def _notices_body(lang: str = "zh") -> str:
    """公告页正文：NOTICES 表一卡一条，全部链到 /download/ 的静态原文。

    卡片里的每个字都来自 NOTICES 表（同表也喂主页公告条）——这里不再有
    第二份文字，改公告只改一处。
    """
    en = lang == "en"
    cards = []
    for it in NOTICES:
        cards.append(
            f'<a class="notecard" href="{esc(it["href"])}">'
            f'<span class="ntag">{esc(it["tag"])}</span>'
            f'<h3>{esc(it["title"])}</h3>'
            f"<p>{esc(it['desc'])}</p>"
            f'<span class="ndate">{esc(it["date"])} · {esc(it["href"])}</span>'
            "</a>")
    if en:
        intro = ("Formal notices about site and ledger changes are collected here. Notices are "
                 "published in Chinese; the files under /download/ are authoritative — this page "
                 "is an index.")
        tail = (f'<p class="plain" style="margin-top:1.2rem">{esc(NOTICES_EN_NOTE)}</p>'
                '<p class="plain" style="margin-top:2.2rem">Next: '
                '<a href="/en/ledger">Ledger data →</a></p>')
    else:
        intro = ("站点变更与账本结构的正式说明都收在这里。公告是对外文件：正文以 "
                 "/download/ 下的原文为准，本页只是索引。")
        tail = ('<p class="plain" style="margin-top:2.2rem">接着看：'
                '<a href="/ledger">账本数据查询 →</a></p>')
    return f'<p class="plain">{intro}</p>\n' + "\n".join(cards) + "\n" + tail


def render_notices() -> bytes:
    return _page(
        "公告 · 众汲之井",
        "站点变更与账本结构的正式公告：结构升级、协议文本变更，以及作废值与重算口径的说明。",
        _hero("公告", "每一次动到对外口径的变更，都会在这里留一条正式的说明。",
              nav=_nav(back='<a href="/home">← 返回首页</a>', lang_href="/en/notices")),
        _notices_body("zh"),
        "/notices",
    )


def render_en_notices() -> bytes:
    return _page(
        "Notices · Zhong Ji Zhi Jing",
        "Formal notices about site and ledger changes — structural upgrades, protocol revisions, "
        "and what values were voided.",
        _hero("Notices", "Every change that moves a public claim leaves a formal notice here.",
              nav=_nav(lang="en", back='<a href="/en/home">← Back</a>', lang_href="/notices")),
        _notices_body("en"),
        "/en/notices",
        lang="en", footer=EN_FOOTER,
    )


# ── 需求：发布页（/requests）与单页（/r/<id>）──────────────────────────────
# 这两页是账本之外唯一「现在进行时」的入口：账本记已经给了什么，它们记谁还缺什么。
# 三条口径必须与读口 `GET /api/v1/requests`、`spec/request.md` 一致：
#   ① 只读 `v_public_request`（列表）/ `request`（单页，因为单页承诺永久可读）；
#   ② 一单只显示当前状态，历史在单页里按 `seq` 列出；
#   ③ 终态 90 天后从**列表**隐藏，单据本身不删。
STATE_LABEL = {"open": "可接", "claimed": "已认领", "delivered": "已交付",
               "closed": "已结", "withdrawn": "已撤回", "expired": "已过期"}
# 英文页面的状态名直接用意语原词（open/claimed/...）：它们是协议里的字面量，
# 翻成 "claimable" 之类反而与 `/api/v1/requests` 返回的 `state` 对不上。
STATE_LABEL_EN = {k: k for k in STATE_LABEL}

# 需求两页的导航直接用上面那份 _nav 生成的结果（NAV_REQUESTS / NAV_REQUEST_ONE），
# 不再在这里另立一份——这里原来是第二份常量，2026-11-15 改名时差点只改了一处。


def _state_chip(state: str, lang: str = "zh") -> str:
    # 类名只从白名单里来（STATE_LABEL 的键），不拼用户输入——拼了就是一个 CSS 注入点。
    labels = STATE_LABEL_EN if lang == "en" else STATE_LABEL
    return (f'<span class="st {esc(state)}">'
            f'{esc(labels.get(state, state))}</span>')


def _short(text, n: int = 260) -> str:
    s = str(text or "")
    return s if len(s) <= n else s[:n].rstrip() + "…"


def render_testing() -> bytes:
    """「测试与验证」：怎么参与测试、在找什么帮忙、以及怎么自己验账。

    这一页是从「怎么参与」改来的（2026-11-15）。改名的原因不是换个好听标题：
    站点上能做的只有两件事——**参与测试**（拿任务卡签、自己接单、发单）与
    **自己验证**（复算导出件、跑链校验）。「怎么参与」只说了前一半，
    「验证」这件事以前散在 `/ledger` 与仓库文档里，访客看不到全貌。

    第一段仍要先解那个具体歧义：``/requests`` 上挂着「可接」的单子，``/sign/`` 却只认
    发布方发的 ``dgtask1:`` 任务卡——**从列表里抄一个 request_id 粘进去走不通**。

    三条不写的：不写「到期自动作废」（``expired`` 没有自动机制）、不写「我们会帮你核对」
    （没有这个角色）、不写「钥匙可以找回」（找不回）。**少一句承诺，比多一句好。**
    """
    meta, body = content("zh", "testing")
    return _page(
        meta["title"],
        meta["desc"],
        _hero(meta["hero_title"], meta["hero_sub"], nav=NAV_TESTING),
        body,
        meta["path"],
    )


def render_requests(state: str | None = None, note: str = "", lang: str = "zh") -> bytes:
    """「需求发布」：怎么发一单、现在有哪些公开的单、以及这一页不管什么。

    改名（2026-11-15，原 ``/needs``「还缺什么」）不只是换标题。旧名字只读得出被动的
    一半——「这里能看到别人缺什么」，看不出「我也可以发一条」；而发单才是这一页的
    写入动机，也是它唯一与账本互补的地方。**名字改成动词性的，正文就得回答「怎么发」**，
    所以第一节是发单三步与必填字段，而不是先甩一串卡片。

    三条不写的：不写「网页可以发单」（没有表单；写库一律验签，浏览器里没有替你保管
    私钥的地方）、不写「到期自动作废」（``expired`` 没有自动机制）、不写「我们会帮你
    匹配」（没有这个角色，按时间列、不排名）。

    ``note`` 非空时取代列表区：坏参数与数据层不可用要**说一句人话**，而不是让读者
    看成「现在没有需求」——空列表与读不到，在屏幕上长得一模一样。
    """
    en = lang == "en"
    try:
        # 倒序取完再翻正，所以这里再反一次：列表要「新的在前」。
        items = list(reversed(load_request_page(DB_PATH, state=state, limit=50)["items"]))
        failure = ""
    except sqlite3.Error as exc:
        items, failure = [], type(exc).__name__

    labels = STATE_LABEL_EN if en else STATE_LABEL
    chips = [("", "All" if en else "全部")] + [(s, labels[s])
                                               for s in ("open", "claimed", "delivered")]
    base = "/en/requests" if en else "/requests"
    filters = "".join(
        f'<a class="chip{" on" if (state or "") == s else ""}" '
        f'href="{base}{("?state=" + s) if s else ""}">{esc(label)}</a>'
        for s, label in chips)

    if note:
        listing = f'<div class="empty">{note}</div>'
    elif failure:
        listing = (
            '<div class="empty">The data layer is temporarily unavailable (%s); this page '
            'cannot read requests. The API returns 503 and the ledger page is unaffected.</div>'
            % esc(failure) if en else
            '<div class="empty">数据层暂时不可用（%s），这一页读不到需求单。'
            '接口会返回 503，账本那一页照常可读。</div>' % esc(failure))
    elif not items:
        # 空列表不是故障，是常态。写清楚，免得读者以为页面坏了。
        listing = (
            '<div class="empty"><b>No public requests right now.</b><br>'
            'That is a normal state: this page is empty when nobody is missing anything. '
            'Please do not post an empty request just to mark your presence — the request '
            'table is not a status bar.</div>' if en else
            '<div class="empty"><b>现在没有公开的需求单。</b><br>'
            '这是正常状态：无人缺什么时，本页即为空。'
            '请勿为「表示在线」发布空需求——需求表不是在线状态栏。</div>')
    else:
        cards = []
        for it in items:
            if en:
                claim = (f'<span class="sep">·</span> claimed by '
                         f'<code>{esc(it["claim_agent_id"])}</code>'
                         if it.get("claim_agent_id")
                         else '<span class="sep">·</span> unclaimed')
                meta = (f'{esc(it["request_id"])} · posted by {esc(it["requested_by"])} '
                        f'{claim} · due {esc(it["window_expires_at"] or "no deadline")} '
                        f'· updated {esc(it["created_at"])}')
            else:
                claim = (f'<span class="sep">·</span> 认领 <code>{esc(it["claim_agent_id"])}</code>'
                         if it.get("claim_agent_id") else '<span class="sep">·</span> 尚未认领')
                meta = (f'{esc(it["request_id"])} · 发布 {esc(it["requested_by"])} {claim} '
                        f'· 期限 {esc(it["window_expires_at"] or "无期限")} '
                        f'· 更新 {esc(it["created_at"])}')
            cards.append(
                f'<a class="reqcard" href="/r/{esc(it["request_id"])}">'
                f'<span class="top">{_state_chip(it["state"], lang)}'
                f'<span class="cat">{esc(it["category"])}</span></span>'
                f'<p>{esc(_short(it["need_desc"]))}</p>'
                f'<span class="meta">{meta}</span></a>')
        listing = "".join(cards)

    if en:
        body = f"""
<p class="plain">The ledger records <b>what has already been given</b>. This page records
   <b>requests</b> — what is missing, who has claimed it, and <b>how to post one</b>.
   They are not the same table: a request is an <b>intention</b> (it can be withdrawn, expire,
   or be voided after a claim), so it is <b>not in the hash chain and not counted in the
   anchor</b>. The chain records only what already happened.</p>

<h2>Publish a request</h2>
<p class="plain">There is <b>no form on this page</b>, and none is planned for the beta: every
   write is signature-verified, and a browser is no place to keep the private key that would
   make it count (the key on <code>/sign/</code> is generated on the spot by the person
   accepting a task — it is not for posting). Posting means a script, in three steps:</p>
<table class="conds">
<tr><th>Step</th><th>What to do</th><th>What to watch</th></tr>
<tr><td>①</td><td>Register a public key with <code>POST /api/v1/party</code></td>
    <td>You get a <code>party_id</code>. Once is enough; the same key keeps working</td></tr>
<tr><td>②</td><td>Sign the request: <code>POST /api/v1/request</code></td>
    <td>with <code>state=open</code>. The signing party must <b>equal</b>
    <code>requested_by</code> — you cannot post under someone else's name</td></tr>
<tr><td>③</td><td>Wait for a claim</td>
    <td>The request appears in the section below; the claim is printed on its card, and
    <b>a claimed request cannot be handed to someone else</b></td></tr>
</table>
<p class="plain">Four fields are required: <code>request_id</code> (<code>rq_</code> plus 8–32
   lowercase letters or digits, chosen by you; duplicates are rejected),
   <code>category</code> (same vocabulary as ledger entries), <code>need_desc</code>
   (1–2000 characters, <b>describe the work, not the person</b>), and
   <code>requested_by</code> (the <code>party_id</code> just registered).
   <code>window_expires_at</code> is optional — leave it out and the request has <b>no
   deadline</b>, which is exactly what the page prints. Full field list and state machine:
   <a href="/agent.md">/agent.md</a> and <code>spec/request.md</code> in the repository.</p>
<p class="plain"><b>A request has to say three things</b>: what is missing, how much, and what
   counts as delivered. Delivery is judged against it — a vague request gets no takers.</p>

<h2>Open requests</h2>
<div class="filters">{filters}</div>
{listing}

<h2>What this page does not do</h2>
<p class="plain">One status line per request; history is appended (<code>seq</code> increases),
   never overwritten. The list shows the <b>current state only</b>, at most the latest 50.
   Closed, withdrawn and expired requests drop out of the list after 90 days, while
   <code>/r/&lt;id&gt;</code> stays readable forever.</p>
<p class="plain">Every row came from a signed request; the signature evidence is on the
   server, <b>not on this page</b>. To verify anything yourself, go to
   <a href="/en/ledger">Ledger data</a> — that verifies <b>entries</b>, not requests.</p>
<p class="plain">Want to take one on? Read <a href="/en/testing">Testing &amp; verification</a>
   first — the signing page only accepts a task card from the publisher, and
   <b>an ID copied from this page will not work</b>.</p>
<p class="plain">This page does <b>not match</b> anyone: it lists by time, first come first
   served — no ranking, no recommendations, no money. Do not post anything illegal,
   infringing, or asking others to carry your risk: requests are publicly quotable, and a
   withdrawal still leaves the trail.</p>

<h2>For agents</h2>
<ul class="links">
  <li><a href="/api/v1/requests?state=open&amp;limit=20">/api/v1/requests?state=open&amp;limit=20</a>
      <span>the same data as JSON, with a cursor; a bad cursor returns 400 instead of
      silently starting over</span></li>
  <li><a href="/agent.md">/agent.md</a>
      <span>integration guide: a script you can run in ten minutes, the capability matrix,
      and the two things to ask a human first</span></li>
</ul>
<p class="plain" style="margin-top:2.2rem">Next:
   <a href="/en/testing">Testing &amp; verification →</a></p>
"""
        return _page(
            "Requests · Zhong Ji Zhi Jing",
            "Public requests: what is missing, who has claimed it, and how to post one. "
            "Requests are intentions — not in the hash chain, not counted in the anchor.",
            _hero("Requests",
                  "The ledger records what was given; here is what is still missing — and how "
                  "to post one of your own.",
                  nav=NAV_EN_REQUESTS),
            body,
            "/en/requests",
            lang="en", footer=EN_FOOTER,
        )

    body = f"""
<p class="plain">账本记<b>已经给了什么</b>；本页记<b>需求</b>——谁缺什么、谁已认领，
   以及一条需求怎么发出。两类记录不是同一张表：需求单记的是<b>意图</b>
   （可撤回、可过期、认领后可作废），因此<b>不进哈希链、不计入锚值</b>。
   链只记已发生的事。</p>

<h2>发一条需求</h2>
<p class="plain">本页<b>没有发单表单</b>，测试期也不打算做：写库一律验签，而浏览器里
   没有替你保管私钥的地方（<code>/sign/</code> 那把钥是接单人当场生成的，不是发单用的）。
   发单走脚本，三步：</p>
<table class="conds">
<tr><th>步骤</th><th>做什么</th><th>要点</th></tr>
<tr><td>①</td><td>登记公钥 <code>POST /api/v1/party</code></td>
    <td>取得 <code>party_id</code>。一次即可，同一把钥此后一直可用</td></tr>
<tr><td>②</td><td>签名发单 <code>POST /api/v1/request</code></td>
    <td>带 <code>state=open</code>。签名主体必须<b>等于</b> <code>requested_by</code>
    ——冒用他人名义发不出单</td></tr>
<tr><td>③</td><td>等人认领</td>
    <td>单子出现在下一节；认领方会印在卡片上，认领之后<b>不能换人</b></td></tr>
</table>
<p class="plain">必填四个字段：<code>request_id</code>（<code>rq_</code> 加 8–32 位小写字母数字，
   自拟，重复即被拒）、<code>category</code>（与账本条目同一词表）、
   <code>need_desc</code>（1–2000 字，<b>只写事不写人</b>）、<code>requested_by</code>
   （即刚登记的 <code>party_id</code>）。<code>window_expires_at</code> 可不填——
   不填就是「无期限」，页面照实印出。字段全集与状态机见
   <a href="/agent.md">/agent.md</a> 与仓库的 <code>spec/request.md</code>。</p>
<p class="plain"><b>一条需求要写清三件事</b>：缺什么、要多少、什么条件下算交付。
   交付凭此判定——写不清的单子无人能接。</p>

<h2>现在公开的单</h2>
<div class="filters">{filters}</div>
{listing}

<h2>这一页的边界</h2>
<p class="plain">一单一条状态行，历史只追加（<code>seq</code> 递增），不改写。列表只显示
   <b>当前状态</b>，最多最近 50 条；已结 / 已撤回 / 已过期的单子 90 天后从列表隐藏，
   <code>/r/&lt;id&gt;</code> 永久可读。</p>
<p class="plain">每一条都来自提交时签名的请求；签名证据在服务端，<b>不在本页</b>。
   自行验证请去 <a href="/ledger">账本数据查询</a>——可验的是<b>账目</b>，不是需求单。</p>
<p class="plain">想接其中一单？先看 <a href="/testing">测试与验证</a>——签署页只认发布方发的
   任务卡，<b>不能把这里的编号直接粘进去</b>。</p>
<p class="plain">本页<b>不做匹配</b>：按时间排序，先到先得；不排名、不推荐、不收费。
   请勿发布违法、侵权或要求他人承担风险的需求——需求单会被公开引用，撤回亦留痕。</p>

<h2>给 agent 用</h2>
<ul class="links">
  <li><a href="/api/v1/requests?state=open&amp;limit=20">/api/v1/requests?state=open&amp;limit=20</a>
      <span>同一份数据的 JSON 读口，带游标增量；坏游标回 400，不会静默重头开始</span></li>
  <li><a href="/agent.md">/agent.md</a>
      <span>接入指南：十分钟可跑脚本、能力矩阵、哪两件事必须先问过人</span></li>
</ul>
<p class="plain" style="margin-top:2.2rem">接着看：<a href="/testing">测试与验证 →</a></p>
"""
    return _page(
        "需求发布 · 众汲之井",
        "公开的需求单：谁缺什么、谁已经认领，以及怎么发一条。需求单是意图，"
        "不进哈希链、不计入锚值——账本只记已经发生的事。",
        _hero("需求发布",
              "账本记已经给了什么；这里记谁还缺什么，以及一条需求怎么发出来。",
              nav=NAV_REQUESTS),
        body,
        "/requests",
    )


def render_request_detail(detail: dict) -> bytes:
    """一单的状态、轨迹与那一对账目。

    这一页要同时说清两件事：**状态行不是账目**（没有哈希可复算），而**交付那两条是**
    （hash 从链上重算，与 `/api/ledger/items` 同一个数）。混在一起讲，读者会以为
    「这一单整体都被链保护着」——那句话是假的。
    """
    cur = detail["current"]
    rid = detail["request_id"]
    state = cur["state"]

    rows = [
        ("当前状态", _state_chip(state)),
        ("类别", f'<code>{esc(cur["category"])}</code>'),
        ("发布方", f'<code>{esc(cur["requested_by"])}</code>'),
        ("认领方", f'<code>{esc(cur["claim_agent_id"])}</code>'
                   if cur.get("claim_agent_id") else "尚未认领"),
        ("期限", esc(cur["window_expires_at"] or "无期限")),
        ("交付时间", f'<code>{esc(cur["occurred_at"])}</code>' if cur.get("occurred_at") else "—"),
        ("交付凭据", f'<code>{esc(cur["evidence_uri"])}</code>' if cur.get("evidence_uri") else "—"),
        ("本行落库", f'<code>{esc(cur["created_at"])}</code>'),
    ]
    table = "".join(f'<tr><th>{k}</th><td>{v}</td></tr>' for k, v in rows)

    # 只有还开着的单子才需要「怎么接」。已结的单子加这句，是把人往一条走不通的路上引。
    hint = ('<p class="plain">想接这一单？先看 <a href="/testing">测试与验证</a>——'
            '签署页只认发布方发的任务卡，<b>这一页的编号不能直接粘进去</b>。</p>'
            if state == "open" else "")

    steps = []
    for h in detail["history"]:
        note = (f'<div class="plain">{esc(h["note"])}</div>' if h.get("note") else "")
        steps.append(f'<li>{_state_chip(h["state"])}'
                     f'<span class="plain"> 第 {h["seq"]} 行</span>'
                     f'<time>{esc(h["created_at"])}</time>{note}</li>')

    if detail["entries"]:
        erows = []
        for e in detail["entries"]:
            if e.get("confirmed"):
                c = e["confirmed"]
                cell = (f'已由 <code>{esc(c["party_id"])}</code> 确认'
                        f'<div class="hash">{esc(c["signed_at"])}</div>')
            elif e["type"] == "give":
                cell = "尚未确认"
            else:
                cell = ("不需要——它由那次交付提交推出，<br>提交本身已经签过名")
            erows.append(f'<tr><td><code>{esc(e["type"])}</code></td>'
                         f'<td><code>{esc(e["entry_id"])}</code></td>'
                         f'<td class="hash">{esc(e["hash"])}</td>'
                         f'<td class="plain">{cell}</td></tr>')
        entries = ('<table class="conds"><tr><th>类型</th><th>entry_id</th>'
                   '<th>hash（从链上重算）</th><th>受方确认</th></tr>'
                   + "".join(erows) + "</table>")
    else:
        entries = ('<div class="empty">这一单还没到 <code>delivered</code>，'
                   '账本里没有对应账目。交付时会同时生成两条（<code>give</code> + '
                   '<code>receive</code>），无需另外登记。</div>')

    body = f"""
<p class="plain">{_state_chip(state)} <code>{esc(rid)}</code></p>
<p style="white-space:pre-wrap;line-height:1.9;font-size:.95rem">{esc(cur["need_desc"])}</p>

<h2>这一单</h2>
<table class="conds">{table}</table>
{hint}

<h2>轨迹（{len(detail["history"])} 行）</h2>
<p class="plain">状态前进是<b>加一行</b>，不是改一行——上面这张表里的每个状态都还在，
   最新一行即当前状态。这些行<b>没有哈希</b>：需求单不入链。</p>
<ul class="tl">{"".join(steps)}</ul>

<h2>这一单在账本里</h2>
<p class="plain">交付时自动生成两条账目，共用 <code>m-{esc(rid)}</code>。
   下面的 hash 由服务端按链重算，与 <a href="/api/ledger/items">/api/ledger/items</a>
   是同一个数；受方确认的是 <code>give</code> 的 hash，确认后这一单即 <code>closed</code>。</p>
{entries}

<h2>两句话分清</h2>
<p class="plain"><b>状态行不是账目。</b>「轨迹」里每一行都是一次已签名请求落下的结果，
   但它们不进哈希链，没有可供第三方重算的 hash——本页<b>不能</b>证明「这单确实是这个状态」，
   只是把库里那一行如实印出。</p>
<p class="plain"><b>账目是账目。</b>交付生成的两条进链、进锚值，任何人可下载导出件自行复算。
   验证入口：<a href="/ledger">账本数据查询</a> 或 <code>/api/ledger/verify</code>。</p>
<p class="plain" style="margin-top:2.2rem">接着看：<a href="/requests">需求发布 →</a></p>
"""
    return _page(
        f"{_short(cur['need_desc'], 40)} · 众汲之井",
        _short(f"需求单 {rid}：状态、轨迹，以及交付生成的两条账目。", 150),
        _hero(_short(cur["need_desc"], 48) or "一单需求",
              f"{rid} · {STATE_LABEL.get(state, state)} · 发布 {cur['requested_by']}",
              nav=NAV_REQUEST_ONE),
        body,
        f"/r/{rid}",
    )


def render_request_missing(rid: str) -> bytes:
    """找不到这一单。**不猜、不模糊匹配**：猜出来的东西比 404 更糟。"""
    body = f"""
<div class="empty"><b>库里没有 <code>{esc(rid)}</code> 这一单。</b><br>
    可能是 id 有误，也可能它从未被发布。需求单不做物理删除，所以「存在过但被删了」
    这种情况不存在——没有，就是没有。</div>
<p class="plain"><a href="/requests">← 回到需求发布</a></p>
"""
    return _page(
        "没有这一单 · 众汲之井",
        "这个 request_id 在库里找不到。",
        _hero("没有这一单", "地址里的 request_id 在库里找不到。", nav=NAV_REQUEST_ONE),
        body,
        "/requests",
    )


def render_en_home() -> bytes:
    meta, body = content("en", "home")
    return _page(
        meta["title"],
        meta["desc"],
        _hero(meta["hero_title"], meta["hero_sub"], brand=True, badges=EN_BADGES,
              nav=NAV_EN_HOME, ask=meta.get("ask", "")),
        _fill(body, "en/home.html",
              TOPBAR=_topbar("en"), STATS=_stats_bar("en"), EN_NOTE=EN_NOTE),
        meta["path"],
        lang="en", footer=EN_FOOTER,
    )


def render_en_contributors() -> bytes:
    return _page(
        "Contributors · Zhong Ji Zhi Jing",
        "Who supports this project: those who write code and documentation, those who enter data, "
        "and those who provide equipment, servers or venues — what each is promised, how to claim, "
        "how to withdraw. This is not the mutual aid recorded in the ledger.",
        _hero("Contributors",
              "Who wrote the code, who entered the data, who provided equipment and servers — "
              "and what each kind of contributor is promised. This is not who helped whom in the "
              "ledger.",
              nav=NAV_EN_CONTRIB),
        EN_CONTRIB_BODY.replace("__EN_NOTE__", EN_NOTE),
        "/en/contributors",
        lang="en", footer=EN_FOOTER,
    )


def render_en_ledger() -> bytes:
    return _page(
        "Ledger data · Zhong Ji Zhi Jing",
        "The ledger's three read-only endpoints, the current anchor, and the steps to recompute it "
        "yourself without trusting us. Recomputation verifies bytes, not facts.",
        _hero("Ledger data",
              "Three read-only endpoints, one anchor, and a chain you can recompute yourself — "
              "no account, no key, and no need to trust us.",
              nav=NAV_EN_LEDGER),
        EN_LEDGER_BODY.replace("__ANCHOR__", _anchor_card("en")).replace("__EN_NOTE__", EN_NOTE),
        "/en/ledger",
        lang="en", footer=EN_FOOTER,
    )


def render_en_testing() -> bytes:
    meta, body = content("en", "testing")
    return _page(
        meta["title"],
        meta["desc"],
        _hero(meta["hero_title"], meta["hero_sub"], nav=NAV_EN_TESTING),
        _fill(body, "en/testing.html", EN_NOTE=EN_NOTE),
        meta["path"],
        lang="en", footer=EN_FOOTER,
    )


NAV_TERMS = ('<div class="nav"><a href="/home">← 返回首页</a>'
             '<span class="sep">/</span><a href="/contributors">贡献与参与者</a>'
             '<span class="sep">/</span><a href="/ledger">账本数据查询</a>'
             '<span class="sep">/</span><a href="/testing">测试与验证</a></div>')
NAV_DOC = ('<div class="nav"><a href="/terms">← 协议公示</a>'
           '<span class="sep">/</span><a href="/home">返回首页</a></div>')

# 四项生效条件。状态写死在页面里，是因为它们此刻就是事实判断，不该由模板
# 从别处推断——推断错了，公示页会替项目说一句没兑现的话。
CONDITIONS = [
    ("①", "笔数上限与准入笔数已回填（1.7.2、1.16.3）", "no", "未满足",
     "五处【待填】原样保留，公示稿不代填"),
    ("②", f"{DISCLOSURE_DAYS} 日公示期满（1.11.5）", "no", "进行中",
     f"自 {DISCLOSURE_START} 起算"),
    ("③", "三项法律问题经执业律师书面答复（附录 B 第 2–4 项）", "no", "未取得",
     "送审包已定稿，回件后按实际档位标注"),
    ("④", "§2、§3 已按 r5 合并", "yes", "已满足", "2026-11-12 两份各自成册"),
]


def render_terms() -> bytes:
    docs = "".join(
        f'<a class="doccard" href="/terms/{esc(d["key"])}">'
        f'<b>{esc(d["short"])}</b><span class="ver">{esc(d["version"])}</span>'
        f'<p>{esc(d["blurb"])}</p>'
        f'<span class="meta">{d["bytes"]:,} 字节 · sha256 {esc(d["sha256"][:16])}…</span>'
        '<span class="go">阅读全文 →</span></a>'
        for d in legal.DOCS
    )
    conds = "".join(
        f'<tr><td>{n}</td><td>{esc(text)}</td>'
        f'<td class="st"><span class="{cls}">{esc(label)}</span></td>'
        f'<td>{esc(note)}</td></tr>'
        for n, text, cls, label, note in CONDITIONS
    )
    body = f"""
<div class="status">
  <div class="row"><span class="k">版本串</span><span class="v">v2.1-r6（三份一致）</span></div>
  <div class="row"><span class="k">状态</span><span class="v hot">公示中，尚未生效</span></div>
  <div class="row"><span class="k">公示起算</span><span class="v">{DISCLOSURE_START}（重新起算；首次公示 2026-11-12）</span></div>
  <div class="row"><span class="k">公示期</span><span class="v">{DISCLOSURE_DAYS} 日，自起算日起连续计算，不因生效日顺延中断（1.20.3）</span></div>
  <div class="row"><span class="k">计划生效日</span><span class="v">{PLANNED_EFFECTIVE}，以四项条件全部满足为前提</span></div>
</div>

<p class="plain" style="margin:.9rem 0 0">用户协议文首仍写着「当前未起算：公示自本稿发布之日起算」——
   那是 2026-11-12 定稿时点的状态标注。本组页面 2026-11-12 上线，公示自此起算；
   2026-11-14 账本结构升级，隐私政策附录「本稿的可核查项」里那句列举随之更正
   （只改这一句，页顶摘要因此改变），公示期<b>自该日重新起算</b>——所以上面写的是
   {DISCLOSURE_START} 而不是 11-12。三份文本的其余部分一字未改。</p>

<h2>三份文本</h2>
<p class="plain">三份同版本串、同日生效。下面是全文入口，每份都另附 <code>.txt</code>
   原文——页面上印的 sha256 由同一份字节现算，可以自己核对一遍。</p>
<div class="docs">{docs}</div>

<h2>四项生效条件</h2>
<p class="plain">任一条未满足，本版本即为公示稿而非生效文本；生效日顺延至全部满足之日，另行公告。
   顺延不改变公示的性质，公示期照常计算。</p>
<table class="conds">
  <thead><tr><th>#</th><th>条件</th><th>当前</th><th>说明</th></tr></thead>
  <tbody>{conds}</tbody>
</table>

<h2>这份公示是什么，不是什么</h2>
<p><b>是</b>拟生效文本的全文，连同它的空白。三份文本里共 {TBD_TOTAL} 处
   <mark class="tbd">【待填】</mark>——笔数上限、责任上限、管辖法院、准入笔数、托管方全称。
   这些是还没定的业务参数，不是排版瑕疵，也不是忘了删的占位符；
   公示稿原样保留，任何人都不代填，包括审阅方。</p>
<p><b>不是什么</b>：不是生效文本，签不了、也约束不了任何人<b>——除了我们自己</b>。
   这份公示本身即是一句承诺：在条件满足之前，我们不会按它主张任何权利。</p>
<p>三份文本<b>均未经执业律师书面审核</b>。任何场合都不应把它表述为「已获法律意见」；
   生效条件 ③ 正是为此而设，未取得即不生效。</p>

<h2>怎么核这份文本</h2>
<p>每份文档页顶都印着该文本的 sha256。把 <code>/terms/&lt;名称&gt;.txt</code> 下载下来
   <code>sha256sum</code> 一遍，与页面上的值逐字符比对即可——两者出自同一份字节，
   对不上就是被改过。docx、PDF 只是排版形态，字体与分页不改变文本。</p>

<h2>意见与变更</h2>
<p>对文本有意见，写到 <a href="mailto:2379731846@qq.com">2379731846@qq.com</a>，
   标题请含「协议公示意见」。公示期内文本若有变更，本页会留变更记录并另行公示；
   已公示的版本不覆盖、不删除。</p>
<p class="plain">变更记录：v2.1-r5　2026-11-12　首次公示（三份同版本串）；
   2026-11-14　两处修订同日发布，公示期均自该日重新起算：① 账本结构升级，隐私政策附录补一处事实性更正；② v2.1-r6 数值回填（N／M／K＝12／60／3、准入 3 次、责任上限与管辖法院填暂定值、注销后保留 30 天、泄露通知 72 小时），条款结构与编号未变。</p>
<p class="plain" style="margin:.6rem 0 0;font-size:.82rem">本次变更公告：
   <a href="/download/notice-20261114b.md">v2.1 r6 数值回填（2026-11-14）</a>　·　
   <a href="/download/notice-20261114.md">2026-11-14 账本结构升级</a></p>
"""
    return _page(
        "协议公示 · 众汲之井",
        "众汲之井三件套（用户协议、隐私政策、免责声明）v2.1-r6 公示页："
        "全文、四项生效条件与当前状态，附可自行核对的文本指纹。",
        _hero("协议公示",
              "三份文本、一个版本串，公示中——尚未生效。",
              nav=NAV_TERMS),
        body,
        "/terms",
    )


def _render_doc(key: str) -> bytes:
    doc = legal.DOCS_BY_KEY[key]
    meta = (
        '<div class="docmeta">'
        f'<div>版本串 <span class="val">{esc(doc["version"])}</span>　·　状态 <b>公示稿，尚未生效</b>'
        f'　·　{doc["bytes"]:,} 字节</div>'
        f'<div>sha256 <span class="val">{esc(doc["sha256"])}</span></div>'
        f'<div>原文 <a href="/terms/{esc(key)}.txt">/terms/{esc(key)}.txt</a>'
        '（纯文本，与上面的指纹同一份字节）</div>'
        '</div>'
    )
    body = (meta
            + f'<article class="doc">{doc["html"]}</article>'
            + '<p class="plain" style="margin-top:2.2rem">'
              '<a href="/terms">← 协议公示</a>　·　本文本为公示稿，尚未生效；'
              '文本以本页为准，排版形态（docx / PDF）不改变文本。</p>')
    return _page(
        f'{doc["short"]}（{doc["version"]}）· 公示稿 · 众汲之井',
        f'{doc["short"]} {doc["version"]} 公示稿：{doc["blurb"]}附原文 sha256，可自行核对。',
        _hero(doc["short"], f'{doc["version"]}　·　公示稿，尚未生效', nav=NAV_DOC),
        body,
        f"/terms/{key}",
    )


def render_agreement() -> bytes:
    return _render_doc("agreement")


def render_privacy() -> bytes:
    return _render_doc("privacy")


def render_disclaimer() -> bytes:
    return _render_doc("disclaimer")


def render_page() -> bytes:
    """兼容旧名：默认渲染主页。六个页面各有自己的 render_*。"""
    return render_home()


# 路径 → 渲染函数。四张并列的主页（贡献与参与者 / 账本数据查询 / 测试与验证 /
# 需求发布）各自还有英文版；公示页与三份正文是中文。路由与计数都从这里取，
# 避免「加了页面忘了计数」这种半拉子改动。
# 入口页不在这张表：`/` 与 `/en` 是 302 去 /welcome（见 do_GET 顶部的分流），
# 主页本体在 /home 与 /en/home；引导页 /welcome、/en/welcome 也在表里——
# 它们是零参渲染函数，与内容页同一条发送路径，但没有站点导航/页脚（独立文档）。
# 注：需求页带 `?state=`，不进这张表，由 `do_GET` 单独分支——表里只放零参函数。
PAGES = {
    "/home": render_home,
    "/contributors": render_contributors,
    "/ledger": render_ledger,
    "/testing": render_testing,
    "/notices": render_notices,
    "/terms": render_terms,
    "/terms/agreement": render_agreement,
    "/terms/privacy": render_privacy,
    "/terms/disclaimer": render_disclaimer,
    "/welcome": render_welcome_zh,
    "/en/home": render_en_home,
    "/en/contributors": render_en_contributors,
    "/en/ledger": render_en_ledger,
    "/en/testing": render_en_testing,
    "/en/notices": render_en_notices,
    "/en/welcome": render_welcome_en,
}


def _welcome_route(lang: str, page: int):
    """把「第几屏」包成零参视图，供 PAGES 表调用（表里只放零参函数）。"""
    def view() -> bytes:
        return render_welcome(lang, page)

    view.__name__ = f"render_welcome_{lang}_p{page}"
    return view


# 引导页第 2 屏及以后：每屏一个独立 URL。条数跟着 WELCOME_ALTS 走，换图不必改这里。
for _wp in range(2, len(WELCOME_ALTS["zh"]) + 1):
    PAGES[f"/welcome/{_wp}"] = _welcome_route("zh", _wp)
    PAGES[f"/en/welcome/{_wp}"] = _welcome_route("en", _wp)
del _wp


class Handler(BaseHTTPRequestHandler):
    server_version = "drawcommons"  # 不写版本号：页面与服务早已不是 1.0-min，写死只会过时

    # 慢连接保护：BaseHTTPRequestHandler 默认 timeout=None，一个挂住的连接
    # 会一直占着线程（ThreadingHTTPServer 下就是一直占一个线程）。公网可见后
    # 这是最省成本的攻击面，15 秒足够正常请求，也足够把 slowloris 挡掉。
    timeout = 15

    # 最简版的页面里没有任何 <script>，所以 script-src 直接关死；
    # style 仍是内联的，只放开 style 的 inline。除此之外不许加载外部资源，
    # 也不许被 iframe 嵌入。
    CSP = (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'none'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )

    def _client_ip(self) -> str:
        """取真实客户端 IP。Caddy 反代之后 socket 对端是 Docker 网关，
        真实地址只在 X-Forwarded-For 里（Caddy 默认就会设）。

        注意：parse_request 失败时（头太多、行长超限）``self.headers`` 尚未赋值。
        此时 send_error 会走到 log_error → log_message → 这里，若直接取属性就会
        抛 AttributeError，把本该发出去的 431 变成「连接被关闭」，反代侧记成 502。
        所以必须用 getattr 兜底。
        """
        headers = getattr(self, "headers", None)
        xff = headers.get("X-Forwarded-For", "") if headers else ""
        if xff:
            return xff.split(",")[0].strip()
        return self.client_address[0]

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Content-Security-Policy", self.CSP)
        self.end_headers()
        if not getattr(self, "_head_only", False):
            self.wfile.write(body)

    def _redirect(self, location: str, code: int = 301) -> None:
        # 改名用 301（永久，可缓存）；入口分流用 302——「先看引导再进主页」是产品
        # 决策不是地址变更，哪天改主意了，301 的缓存会让旧决定在别人浏览器里多活一年。
        self.send_response(code)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _json(self, code: int, obj: dict) -> None:
        self._send(code,
                   json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _serve_requests(self) -> None:
        """需求单发现口。读数：`v_public_request`（与公开页同一口径）。

        三个参数各管一件事，不互相解释：`since` 决定「增量还是最近一屏」，
        `state` 只做过滤，`limit` 只管页大小。返回体里把这三个都抄回去，
        调用方不必回忆自己刚才传了什么。
        """
        q = parse_qs(urlsplit(self.path).query, keep_blank_values=True)

        def one(key: str) -> str | None:
            vals = q.get(key)
            return vals[0] if vals else None

        raw_limit = one("limit") or "20"
        try:
            limit = int(raw_limit)
        except ValueError:
            self._json(400, {"ok": False, "error": "bad_limit",
                             "detail": f"limit={raw_limit!r} 不是整数"})
            return
        if not 1 <= limit <= 200:
            self._json(400, {"ok": False, "error": "bad_limit",
                             "detail": "limit 必须在 1..200"})
            return

        state = one("state")
        if state is not None and state not in REQUEST_STATES:
            self._json(400, {"ok": False, "error": "bad_state",
                             "detail": "state 只能是 " + " / ".join(REQUEST_STATES)})
            return

        raw_since = one("since")
        since = None
        if raw_since:
            try:
                since = decode_cursor(raw_since)
            except ValueError as exc:
                # 明确回 400，不偷偷从头开始：静默降级会让客户端以为在拿增量，
                # 其实每次都重放全量——而它永远不会知道，这才是最坏的失败方式。
                self._json(400, {"ok": False, "error": "bad_cursor",
                                 "detail": str(exc)})
                return

        try:
            page = load_request_page(DB_PATH, since=since, state=state, limit=limit)
        except sqlite3.Error as exc:
            self._json(503, {"ok": False, "error": "data_layer_unavailable",
                             "detail": f"{type(exc).__name__}: {exc}"})
            return

        self._json(200, {
            "ok": True,
            "endpoint": "requests",
            "contract": "v1",
            "since": raw_since,
            "state": state,
            "limit": limit,
            **page,
        })

    def _serve_md(self, path: str, missing: str) -> None:
        """发一份 markdown 原样字节。`agent.md` 与 `audit.md` 共用这一个出口。

        发镜像里那份文件，不在这里拼字符串——拼一份就等于多了一份会单独过期的说明，
        而它和仓库那份谁新谁旧没人说得清。
        """
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError as exc:
            self._json(503, {"ok": False, "error": missing,
                             "detail": f"{path}: {exc}"})
            return
        self._send(200, body, "text/markdown; charset=utf-8")

    def _serve_agent_md(self) -> None:
        self._serve_md(AGENT_MD, "agent_md_missing")

    def _serve_audit_md(self) -> None:
        self._serve_md(AUDIT_MD, "audit_md_missing")

    def _serve_image(self, name: str) -> None:
        """欢迎层图片：白名单直服。

        文件名不在 WELCOME_IMAGES 表里就是 404——从 URL 到磁盘路径之间没有
        任何拼接，目录遍历与扩展名猜测都无从发生。「服务谁」由代码点名，
        不由 URL 描述。响应带一年 immutable 缓存：文件若换，连名字一起换。
        """
        ctype = WELCOME_IMAGES.get(name)
        if ctype is None:
            self._send(404, b'{"error":"not found"}', "application/json")
            return
        try:
            with open(os.path.join(IMAGES_DIR, name), "rb") as f:
                body = f.read()
        except OSError:
            self._send(404, b'{"error":"not found"}', "application/json")
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if not getattr(self, "_head_only", False):
            self.wfile.write(body)

    def _serve_requests_page(self, lang: str = "zh") -> None:
        """需求发布页。坏 `state` 回 400 而不是「当作没传」——后者会让读者以为筛选生效了，
        而屏幕上其实是全量。这与读口对坏游标的处理是同一条原则。

        中英两页走同一个函数、同一份数据，只换文案：两套实现迟早会在「同一条单子
        两种说法」上分叉，而分叉的那一天没人会发现。
        """
        en = lang == "en"
        q = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        vals = q.get("state")
        state = vals[0] if vals else None
        if state == "":
            state = None
        if state is not None and state not in REQUEST_STATES:
            home = "/en/requests" if en else "/requests"
            note = ((f"<b><code>state={esc(state)}</code> is not a state.</b><br>"
                     "It must be one of " + " / ".join(REQUEST_STATES) + "."
                     f' <a href="{home}">See all →</a>') if en else
                    (f"<b><code>state={esc(state)}</code> 不是一个状态。</b><br>"
                     "只能是 " + " / ".join(REQUEST_STATES) + "。"
                     f' <a href="{home}">看全部 →</a>'))
            self._send(400, render_requests(None, note, lang), "text/html; charset=utf-8")
            return
        self._send(200, render_requests(state, lang=lang), "text/html; charset=utf-8")

    def _serve_request(self, rid: str) -> None:
        """单页。id 不合法与 id 不存在都回 404 的同一页：对读者是同一件事——
        这里没有你要的那一单。"""
        if len(rid) > 64 or not rid.startswith("rq_"):
            self._send(404, render_request_missing(rid), "text/html; charset=utf-8")
            return
        try:
            detail = load_request_detail(DB_PATH, rid)
        except sqlite3.Error as exc:
            note = (f"数据层暂时不可用（{esc(type(exc).__name__)}），这一页读不到这一单。"
                    "接口会返回 503，账本那一页照常可读。")
            self._send(503, render_requests(None, note), "text/html; charset=utf-8")
            return
        if detail is None:
            self._send(404, render_request_missing(rid), "text/html; charset=utf-8")
            return
        self._send(200, render_request_detail(detail), "text/html; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802（基类命名）
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        # 入口分流（2026-11-15）：进入应用先看三屏引导。`/` 与 `/en` 不再直接是
        # 主页——主页搬到 /home 与 /en/home，引导页是 /welcome 与 /en/welcome
        # （独立文档，与主页零共享）。用 302 不用 301：这是产品决策不是地址变更，
        # 301 会被浏览器长期缓存，哪天改主意就收不回来了。
        if path in ("/", "/en"):
            self._redirect("/welcome" if path == "/" else "/en/welcome", code=302)
            return
        # 引导第 1 屏的地址是 `/welcome`（不是 `/welcome/1`）。手输 `/welcome/1`
        # 的人不该看到 404——301 归位；**只认这一个**，`/welcome/9` 仍旧 404，
        # 免得把「第几屏」写成任意数字也能进。
        if path in ("/welcome/1", "/en/welcome/1"):
            self._redirect("/welcome" if path == "/welcome/1" else "/en/welcome", code=301)
            return
        # 2026-11-15 改名：「怎么参与」→「测试与验证」，路径 /join → /testing。
        # 旧地址 301 过去而不是 404——这一页上线不到一天就改了名，抄了旧地址的笔记还在，
        # 链接坏了是我的事，不是读者的事。英文同理。
        if path in ("/join", "/en/join"):
            self._redirect("/testing" if path == "/join" else "/en/testing")
            return
        # 2026-11-15 改名：「还缺什么」→「需求发布」，路径 /needs → /requests。
        # 链接坏了是我的事，不是读者的事，所以旧地址 301；但**查询串要一起带过去**：
        # `?state=` 是筛选，丢掉会悄悄变回全量——屏幕上看起来像「筛选生效了」，
        # 比 404 更像谎话。这一条比 301 本身重要。
        if path in ("/needs", "/en/needs"):
            qs = self.path.split("?", 1)[1] if "?" in self.path else ""
            self._redirect(("/requests" if path == "/needs" else "/en/requests")
                           + (f"?{qs}" if qs else ""))
            return
        # 库被写过就重建内存链。只在这些路径上 stat 一次：静态页与协议正文不读账本，
        # 为它们也 stat 只会让健康检查多一次磁盘调用。放在 503 判断之前——库不可用时
        # maybe_reload 自己会早退（_stamp 返回 None）。
        if LEDGER is not None and (path.startswith("/api/ledger/")
                                   or path in ("/ledger", "/en/ledger")):
            LEDGER.maybe_reload()
        # 数据层不可用时，接口明确报 503，而不是甩一个 500 让人以为站点挂了
        if path.startswith("/api/ledger/") and LEDGER is None:
            body = json.dumps(
                {"ok": False, "endpoint": path.rsplit("/", 1)[-1],
                 "error": "data_layer_unavailable", "detail": LEDGER_ERROR},
                ensure_ascii=False, indent=2,
            ).encode("utf-8")
            self._send(503, body, "application/json; charset=utf-8")
            return
        if path == "/healthz":
            # 探活专用：不碰账本链（verify 是 O(n) 全链重算），也不进访问日志，
            # 免得每 30 秒一条 127.0.0.1 污染以后的访问统计。
            self._send(200, b"ok", "text/plain; charset=utf-8")
        # 公示文本的纯文本原文。与文档页上印的 sha256 出自同一份字节：
        # 谁都能下载、自己 sha256sum 一遍，与页面对一遍。
        elif path.startswith("/terms/") and path.endswith(".txt"):
            doc = legal.DOCS_BY_KEY.get(path[len("/terms/"):-len(".txt")])
            if doc is None:
                self._send(404, b'{"error":"not found"}', "application/json")
            else:
                self._send(200, doc["raw"].encode("utf-8"), "text/plain; charset=utf-8")
        # 中文：/home 讲项目，/contributors 讲人，/ledger 讲数据，/testing 讲怎么测与
        # 怎么验，/terms 及其三份正文；/welcome 是前置引导（独立文档）。英文各页
        # （/en/home、/en/contributors、/en/ledger、/en/testing、/en/requests）与中文
        # 一一对应，同一件事只有一种说法。
        # path 已被 rstrip，"/ledger/" 到这里就是 "/ledger"——两者都渲染，
        # 若在此 301 到带斜杠的形式会造成重定向循环。
        # 计数只算中文主页的 GET：其余页面与 /api/* 一概不记；do_HEAD 复用本函数，
        # 监控探活若用 HEAD /home 会把数字刷起来，那不是「有人来看」，是「有人在数自己」。
        elif path in PAGES:
            if path == "/home" and not getattr(self, "_head_only", False):
                VISITS.hit()
            self._send(200, PAGES[path](), "text/html; charset=utf-8")
        # 需求两页。`/requests` 与 `/en/requests` 带查询参数（`?state=`），所以不进 PAGES
        # 那张「路径 → 零参函数」的表；`/r/<id>` 更是动态路径。两条都直接读库，
        # 不经过 Ledger 的内存链——它们读的是需求单与条目表，跟锚值无关。
        elif path in ("/requests", "/en/requests"):
            self._serve_requests_page("en" if path.startswith("/en/") else "zh")
        elif path.startswith("/r/"):
            self._serve_request(path[len("/r/"):])
        elif path == "/api/ledger/items":
            # indent=2：浏览器直接打开也整齐可读；量小（测试期），排版开销可忽略
            body = json.dumps(
                {"endpoint": "items", "count": len(LEDGER.chain),
                 "genesis": GENESIS, "data_notice": DATA_NOTICE,
                 "items": LEDGER.chain},
                ensure_ascii=False, indent=2,
            ).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
        elif path == "/api/ledger/verify":
            result = LEDGER.verify()
            result.update({
                "endpoint": "verify",
                "genesis": GENESIS,
                "chain_tail": LEDGER.chain[-1]["hash"] if LEDGER.chain else None,
            })
            body = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
        elif path == "/api/ledger/export":
            self._send(200, LEDGER.export_bytes, "application/json; charset=utf-8")
        # 发现口（r6 · 需求发布页的数据源）。只读、不验签、不碰链：
        # 它读的是需求单，不是账目，所以既不改锚值，也不依赖 Ledger 的内存链。
        elif path == "/api/v1/requests":
            self._serve_requests()
        # 欢迎层的图片。放在 PAGES 之后、兜底 404 之前：它只服务白名单里的六个名字。
        elif path.startswith("/images/"):
            self._serve_image(path[len("/images/"):])
        # 给 agent 的发现入口。放在 `/agent.md` 之前：`/llms.txt` 是约定的
        # 第一站，`/agent.md` 是它的下一跳。两者都不碰 `/` 的 302。
        elif path == "/llms.txt":
            self._send(200, render_llms(), "text/plain; charset=utf-8")
        # 给 agent 的接入指南。放在站点根而不是 /api/ 下：它不是接口，是说明书，
        # 一个只会 curl 的 agent 拿到 URL 就该能读懂并照做。
        elif path == "/agent.md":
            self._serve_agent_md()
        # 给 agent 的**审计**任务书。与上面这份是两种活：那份教它怎么加入，
        # 这份教它怎么查我。不需要注册、不需要私钥、不写账本。
        elif path == "/audit.md":
            self._serve_audit_md()
        else:
            self._send(404, b'{"error":"not found"}', "application/json")

    def do_HEAD(self) -> None:  # noqa: N802
        # 复用 GET 的路由与头部，只是不写 body（监控探活会用 HEAD）
        self._head_only = True
        self.do_GET()

    def log_message(self, fmt, *args):  # 安静一点，一行一条
        # 原先是 self.address_string()，反代后全是 172.18.0.2。
        # 改成真实 IP + flush，docker logs 里才看得出谁在扫、谁在用。
        msg = fmt % args
        if "/healthz" in msg:
            return
        print(self._client_ip(), msg, flush=True)


if __name__ == "__main__":
    # 三行都带 flush：stdout 接管道时 Python 用块缓冲（默认 8KB），启动横幅
    # 只有百余字节，不 flush 就永远留在缓冲区里——docker logs 全空，而监控
    # 看容器又是 healthy，等于把「版本对不对」这件事藏起来了。
    if LEDGER is None:
        print(f"ledger public page: 数据层不可用（{LEDGER_ERROR}），接口将返回 503",
              flush=True)
    else:
        size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else -1
        print(f"ledger public page: {len(LEDGER.chain)} items, "
              f"export sha256={LEDGER.export_sha256}", flush=True)
        print(f"data source: {datasource_banner(DB_PATH)}  size={size}B", flush=True)
    # 访问计数的状态必须能看到：它不可写时首页会静默不显示那一行，
    # 若不在启动时喊一声，运维只会看到「页面上没数字」，查不出为什么。
    if VISITS.available:
        print(f"visits: {VISITS_PATH} (ok, 只数首页)", flush=True)
    else:
        print(f"visits: ⚠ 不可用（{VISITS.error}）——首页不显示访问者数", flush=True)
    n_content = _validate_content()   # 死链/缺页/插槽拼错，在这里炸
    print(f"content: {n_content} 页（{CONTENT_DIR}）", flush=True)
    print(f"listening on {ADDR[0]}:{ADDR[1]}  "
          f"(/ 引导, /home 主页, /contributors 贡献与参与者, /ledger 账本数据查询, "
          f"/testing 测试与验证, /requests 需求发布, /r/<id> 一单的轨迹, "
          f"/notices 公告, /terms 协议公示 + 三份正文, "
          f"/en english, /en/contributors, /en/ledger, /en/testing, "
          f"/en/requests, /api/... json)", flush=True)
    ThreadingHTTPServer(ADDR, Handler).serve_forever()
