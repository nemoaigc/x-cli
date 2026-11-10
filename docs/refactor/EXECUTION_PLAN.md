# x-cli 重构执行文档

> 读者：执行重构的模型（Opus 5.5）。你没有看过产生这份文档的讨论，所需背景都在本文内。
> 基线：`main` @ `afc8feb`，v2.1.2。文中行号均以该提交为准，动手前先核对。
> 状态：方案已获仓库所有者同意；第 5 阶段尚未批准，不要做。

## 1. 目标与非目标

x-cli 是一个用 cookie 调 X 私有接口的命令行工具，输出 JSON，主要被 LLM agent（Claude Code、Codex）和定时任务通过 shell 调用。仓库还随包带一个 agent skill（`skills/x-research`），里面只有提示词和参考文档。

这次重构要解决三件事：

1. `core/client.py`（1605 行）是一个上帝类，每加一个端点都要复制一段变量、特性开关和分页循环。
2. 命令层有大量复制粘贴（`_ctx` 13 份、`_serialize` 4 份、`except XQueryError` 23 处），输出格式因此不一致。
3. 上一次从 argparse 迁到 typer 时丢了功能，没人发现，因为内核没有测试。

**非目标**：不重写，不换框架（typer、curl_cffi 保留），不做 MCP 服务，不改命令名和参数（那是第 5 阶段，未批准）。

### 分层原则

所有设计取舍按这张表判断。拿不准一段逻辑放哪层时，回到这里。

| 层 | 负责 | 不负责 |
|---|---|---|
| 核心库 `x_cli.core` | 跟 X 对话，返回类型化对象；可被其他 Python 程序直接 import | 打印、退出码、typer |
| CLI `x_cli.commands` | 参数解析、确定性的抓取与机械变换（去重、时间窗切分、按给定参数过滤排序）、JSON 信封 | 任何"取多少、阈值多少算好"的默认判断 |
| Skill `skills/x-research` | 判断：选哪些源、权重和垃圾模式怎么定、怎么综合 | 可执行逻辑 |

## 2. 全程必须守住的约束

这些约束每个阶段都适用。违反任何一条都要停下来问所有者。

**输出契约不变。** 成功是 `{"ok": true, "schema_version": "1", "data": ...}`，失败是 `{"ok": false, "schema_version": "1", "error": {"code", "message"}}`，退出码 1 是运行时错误、2 是输入非法。第 0 阶段建立的快照测试是裁判：第 1–3 阶段结束时快照必须逐字节相同，只有本文明确列为"允许的变化"的地方可以更新快照，并在 PR 描述里逐条写明。

**不动反检测细节。** `_build_headers`（client.py:1567）里的请求头名称、取值、顺序，`_best_chrome_target` 的指纹选择，请求间隔与抖动的默认值（`requestDelay` 2.5s、`uniform(0.7, 1.5)`、写操作 1.5–4s），都原样搬运。这些值是对着 X 的风控调出来的，改了不会让测试失败，但会让真实账号被限流或封禁。

**不动 `FALLBACK_QUERY_IDS` 的值。** 可以改它存放的位置和结构，不要改任何一个 ID。

**写操作不重试网络错误。** 发推、点赞、关注这类请求如果在网络错误后自动重试，可能重复执行。统一传输层时，网络错误重试只给 GET；POST 保持各通道现在的行为（见 3.2 的表）。

**不对真实账号做写操作。** 所有测试离线跑。需要联网冒烟时只跑只读命令，并且先征得所有者同意。录制 fixture 的规则见第 0 阶段。

**测试断言不改。** 现有 118 个测试全部在命令层 patch `x_cli.commands.<模块>.build_client`。重构可以改 patch 的目标路径，但要单独一个提交，且该提交里断言内容一行不动。如果某个断言必须改才能通过，说明行为变了，停下来。

**流程。** 每个阶段一个分支（`refactor/phase-N-<名字>`，从最新 `main` 切）、一个 PR。阶段结束后停下等所有者审，不要连着做下一个。不要发版、不要改 `pyproject.toml` 里的版本号。

## 3. 现状要点

只列会影响你决策的事实，完整结构自己读代码。

### 3.1 规模

`src/x_cli` 共 6,668 行。最大的几个文件：`core/client.py` 1605、`core/auth.py` 523、`core/parser.py` 500、`core/rank.py` 253、`core/graphql.py` 242、`timeline_io.py` 230。测试 118 个，0.9 秒，只覆盖 `tests/commands/*` 和 `tests/test_timeline_io.py`；`core/` 下的 parser、client、graphql 没有任何测试，仓库里没有真实响应样本，也没有 CI。

### 3.2 三套 HTTP 通道

`TwitterClient` 里有三个各自为政的请求方法，行为差异是真实存在的，统一时要保留差异而不是抹平：

| 通道 | 位置 | 请求头 | 429 重试 | 网络错误 | 错误类型 |
|---|---|---|---|---|---|
| GraphQL `_api_request` | client.py:1446 | `_build_headers` 全套 | 指数退避 | 不重试，包成 `TwitterAPIError(0)`，错误码是 `api_error` | 另外解析响应体里的 `errors`（88、348、349） |
| REST v1.1 `_legacy_rest_post` | client.py:918 | 全套 + 表单编码 | 指数退避 | 重试，最后抛 `NetworkError` | `RateLimitError` / `TwitterAPIError` |
| 上传 `_upload_post` | client.py:1235 | 只有 5 个头 | 无 | 无处理，异常直接冒出 | `TwitterAPIError` |

cookie 字符串解析成字典的代码在 REST 和上传两处重复。

### 3.3 已知的坑

- **构造即联网。** `TwitterClient.__init__` 末尾调 `_ensure_client_transaction()`（client.py:133），缓存过期时会请求 x.com 首页。所以连 dry-run 都会发网络请求。
- **一个潜伏的崩溃。** `_legacy_rest_post` 里有 `if not self._ct_init_attempted: self._init_client_transaction()`，但 `_init_client_transaction` 这个方法不存在。现在因为构造函数总是先把标志置真，这行永远走不到。你一旦改成懒加载，它就会抛 `AttributeError`。
- **全局可变状态。** `graphql.py` 的 `FEATURES` 被 `_update_features_from_html` 原地修改；`_cached_query_ids`、`_bundles_scanned`、client.py 的 `_cffi_session` 都是模块级全局。
- **queryId 缓存只在进程内。** CLI 每次都是新进程，所以内置 ID 一旦过期，每次调用都要付一遍"404 → 拉 GitHub → 重试"。
- **四个几乎相同的分页循环。** `_fetch_timeline`（client.py:1280）、`_fetch_user_list`（1339）、`search_users`（411）、`fetch_recommended_users`（591）。
- **越层调用。** `core/explore.py`（3 处）和 `commands/me.py:116` 直接调私有的 `client._graphql_get`。
- **死代码。** `commands/me.py` 的 `_probe_mentions` 先探测 `NotificationsTimeline` 和 `Notifications`，这两个操作不在 ID 表里，解析时不给抓取函数，所以循环总是 `continue`，实际只走最后的搜索兜底。`core/timeutil.py` 没有任何引用。`core/output.py` 的 `add_common_args`、`require_positive_int` 没有调用方。`graphql.py` 里的 `PinTweet` / `UnpinTweet` 没被用到（置顶走的是 REST）。
- **输出不一致。** `feed`、`user`、`list` 经过 `timeline_io.emit_timeline`，推文带 `content_kind`；`search`、`tweet` / `tweet-article` / `tweet-batch`、`me likes` / `bookmarks` / `mentions` 直接 `dataclasses.asdict`，没有这个字段。`trend drill` 的结果里是否含推文，自己读 `commands/trend.py` 确认。
- **丢失的功能。** skill 文档（`references/search-plan.md`、`read-mode.md`）教 LLM 用 `search --auto-window`，但 `search` 命令没有这个参数；实现还在 `core/window.py` 的 `adaptive_search`，只是没接线。skill 文档还让 LLM 写 `from x_cli.core import rank`，另有两处写的是早已不存在的 `from scripts._core import rank`。
- **过期文案。** `SPEC.md` 写的错误信封是 `{"ok": false, "error_code": ..., "error": ...}`，与实现不符。`core/auth.py:498` 和 `:509` 的报错让用户运行不存在的 `scripts/profile.py`。源码里有 150 处 `# type:` 注释式标注。
- **auth 的重复。** `_extract_via_subprocess`（auth.py:271）内嵌了一段约 125 行的脚本字符串，逻辑与进程内的 `_extract_in_process` 重复，浏览器列表两边各写一遍。

`core/paths.py` 里的 `x-query` 旧目录是给老用户迁移 profile 用的，是有意保留的，不要当过期引用删掉。

## 4. 阶段

### 第 0 阶段：安全网

**为什么先做这个。** 后面每个阶段都在动没有测试的内核。上次重构丢功能就是因为没有这层网。这个阶段不改任何产品代码的行为。

**交付物：**

1. **真实响应 fixture**，放 `tests/fixtures/responses/<操作名>__<场景>.json`，内容是 X 返回的原始 JSON。
2. **解析器黄金测试**：对每个 fixture 跑 `parse_timeline_response` / `parse_tweet_result` / `parse_user_result` / explore 的解析函数，把结果 `asdict` 后与提交进仓库的黄金文件比较。黄金文件由当前代码生成，目的是锁定现状，不是判断现状对不对。发现解析结果明显有误时记到 PR 描述里，不要顺手修。
3. **全栈快照测试**：新增一个测试夹具，在 HTTP 这一层喂 fixture（现在的拦截点是 `TwitterClient._api_request`，同时让 `_ensure_client_transaction` 和 `get_cookies` 不联网），然后通过 `CliRunner` 跑真实命令，对 stdout 的完整 JSON 做快照。每个只读命令至少一条。拦截点封装在一个夹具里，第 1 阶段传输层换掉之后只需要改这一个夹具。
4. **写命令的 dry-run 快照**：`post`、`follow`、`x-list` 等不带 `--yes` 时的输出。
5. **CI**：一个 GitHub Actions 工作流，在 push 和 PR 上跑 `pytest`，Python 3.10 和最新稳定版。

**fixture 怎么来。** 需要用所有者的真实账号抓，所以这一步必须所有者在场并明确同意后才能执行。写一个开发脚本 `tools/record_fixtures.py`（不进 wheel），包住 `_api_request` 把原始响应落盘。规则：

- 只调只读接口。
- 只录公开内容：`UserByScreenName`、`UserTweets`、`UserTweetsAndReplies`、`UserMedia`、`UserArticlesTweets`、`UserHighlightsTweets`、`TweetDetail`、`TweetResultByRestId`、`TweetResultsByRestIds`、`SearchTimeline`（Top、Latest、People）、`ListLatestTweetsTimeline`（公开列表）、`Followers` / `Following`（公开大号）、`ExplorePage`、`GenericTimelineById`、`TrendRelevantUsers`。
- 不录带个人信息的接口原文：首页时间线、书签、点赞、`fetch_me`、推荐关注、自定义时间线。这些接口和上面的走同一个解析器，只是 `instructions` 的路径不同，用已录的公开响应手工改外层包装来构造 fixture 即可。
- 场景要覆盖解析器的分支：普通推文、长推（note tweet）、文章（含图片和标题）、引用推文、转推、带图和带视频、推广内容、可见性包装（`TweetWithVisibilityResults`）、墓碑或已删除、2026-10 之后拆分 legacy 字段的新版用户对象、带游标和不带游标的页。
- 每个文件裁到几条 entry，够覆盖分支就行，单文件尽量在 100KB 以内。
- 落盘前检查：响应体里不应出现 cookie、`auth_token`、`ct0`；出现所有者自己账号的 ID 或用户名时替换成占位值。

**验收：** `pytest` 全绿且新增测试都在离线环境通过；随便把 `parser.py` 里一个字段名改错，至少有一个黄金测试失败（自己做一次这个变异检查，然后还原）。

### 第 1 阶段：传输层

**目标：** 把"怎么发请求"从 `TwitterClient` 里抽出来，变成一个可以被替换和测试的对象。

**做什么：**

- 新建 `core/transport.py`，一个 `Transport` 类持有：cookie、curl_cffi 会话、ClientTransaction、当前的 features、queryId 缓存。原来的模块级全局（`_cffi_session`、`FEATURES` 的可变副本、`_cached_query_ids`、`_bundles_scanned`）都变成它的实例状态。`_DEFAULT_FEATURES` 作为不可变常量保留。
- 三个通道合并成一个底层 `request()` 加三个薄入口（GraphQL、REST、上传）。合并的是 cookie 组装、会话获取、状态码到异常的映射、429 退避；保留的是 3.2 表里每个通道各自的请求头集合和重试策略。上传通道继续只发那 5 个头，不要"顺便"给它补全套。
- ClientTransaction 改成第一次真正发请求时才初始化。顺手修掉 3.3 里那个调用不存在方法的潜伏崩溃。
- queryId 落盘缓存：路径通过 `core/paths.py` 新增一个函数给出，只存"与内置表不同的、在线解析出来的 ID"，带时间戳，24 小时过期，遇到 404/422 时作废对应条目。缓存里记下写入时的包版本，版本变了整体作废，避免升级后旧缓存盖过新的内置表。文件权限 0600，读写失败只记 debug 日志，不影响主流程。
- `explore.py` 和 `me.py` 改调公开入口，不再碰下划线方法。

**允许的行为变化（都要写进 PR 描述）：**

- GraphQL GET 的网络异常从 `TwitterAPIError(0)`（错误码 `api_error`）改为 `NetworkError`（错误码 `network_error`），并按现有退避参数重试。GraphQL POST 的网络异常也改成 `NetworkError`，但不重试。
- 构造 client 不再联网，所以 `--help` 之外的 dry-run 也不再发请求。

**验收：** 第 0 阶段的快照逐字节不变（只改了夹具的拦截点）；新增传输层单测覆盖 429 退避、88/348/349 错误码映射、404 后刷新 queryId 重试一次、GET 网络错误重试而 POST 不重试、落盘缓存的过期与版本作废；用一个断言证明构造 `TwitterClient` 时没有任何 HTTP 调用。

### 第 2 阶段：操作表与分页器

**目标：** 加一个新的只读端点应该是"在表里加一行"，而不是复制四十行。

**做什么：**

- 新建 `core/operations.py`，用数据声明每个 GraphQL 操作：操作名、GET 还是 POST、基础 variables、是否覆盖基础 variables、field toggles、响应里 `instructions` 的路径、条目解析成推文还是用户。`FALLBACK_QUERY_IDS` 可以并进这张表，也可以留在原处由表引用，选改动小的那个。
- 一个通用分页器取代 3.3 提到的四个循环。它们之间的细微差别要先读清楚再合并，现有行为里至少有这些：每页请求数是 `min(剩余 + 5, 40)`；最大页数是 `ceil(count / 20) + 2`；"这一页有内容但全是重复"时停止；游标不变时停止；页间延时只在还没取够时才睡；`_fetch_timeline` 支持 `start_cursor` 和 `return_cursor`（`timeline_io` 的 mix gate 依赖它）。合并后这些都要保持。
- `TwitterClient` 的公开方法名和签名不变（命令层和测试都依赖），内部改成"查表 + 分页器"。写操作和媒体上传各自拆到单独模块，`TwitterClient` 通过组合或 mixin 暴露它们，选哪种看哪种让文件更好读。
- 把核心库整理成正式的 Python 接口：`x_cli/__init__.py` 导出 client 类、一个按 profile 构造 client 的工厂函数、`core.models` 里的数据类、异常类。`build_client` 从 `core/output.py` 挪到这个工厂的位置；`core/output.py` 只留输出相关的东西。命令模块里 `build_client` 这个名字要继续存在（重导出即可），否则 118 个测试的 patch 目标全部失效。
- 把 150 处 `# type:` 注释改成正常的类型标注。这是纯机械改动，单独一个提交。

**不要做：** 不要引入 async，不要引入 pydantic，不要把 dataclass 模型改名或改字段。

**验收：** 快照逐字节不变；`core/` 下没有超过约 500 行的文件（这是目标，不是硬指标，为了凑数字而硬拆不如留着）；在 PR 描述里用一个真实例子演示"新增一个时间线类端点需要改哪几行"；分页器有独立单测，覆盖上面列的每一条停止条件。

### 第 3 阶段：命令层

**目标：** 消掉命令层的复制粘贴，统一推文的序列化出口。

**做什么：**

- 一个公共的命令包装（装饰器或上下文管理器，选对 typer 签名干扰小的那个），负责：取 `CliCtx`、把 `InvalidInputError` / `ValueError` 映射成退出码 2、把其他 `XQueryError` 映射成退出码 1、调 `emit_error`。13 份 `_ctx`、4 份 `_serialize`、23 处 `except XQueryError` 收敛到这一处。
- 所有输出推文的命令走同一个序列化函数（现在 `timeline_io._tweet_to_dict` 的逻辑）。
- 删掉 3.3 列出的死代码：`_probe_mentions` 里走不到的探测循环（保留搜索兜底）、`core/timeutil.py`、`output.py` 里没人调的函数、没用到的 `PinTweet` / `UnpinTweet` ID。删之前各自 grep 确认一次没有引用，包括 `skills/` 目录下的文档。
- `auth.py`：子进程兜底改成用 `python -m` 调包内的一个小模块，删掉内嵌的脚本字符串，浏览器列表只保留一份定义。子进程这条路存在是因为某些环境下进程内读 Keychain 会卡住或失败，所以兜底本身要保留，只是去掉重复。
- 修正过期文案：`auth.py` 里指向 `scripts/profile.py` 的两条报错改成现在真实可用的命令（先跑 `x-cli auth --help` 确认命令名）；源码注释和 docstring 里的 `x-query`、`scripts/`、`argparse` 字样按实际情况更新。用这条命令找：`grep -rn "scripts/\|x-query\|XQ_\|profile.py\|argparse" src skills README.md SPEC.md`，逐条判断，`core/paths.py` 的迁移逻辑除外。
- 重写 `SPEC.md`，以实现为准，错误信封改对。

**允许的行为变化：**

- 3.3"输出不一致"一条列出的那些命令，输出的推文多出 `content_kind` 字段。这是纯增量，`schema_version` 保持 `"1"`，同步更新 `skills/x-research/schema.json`。
- 不要给这些命令加 `you_follow_author` 标注。那个标注要额外拉一次关注列表，`search` 默认带上会让每次搜索多一串请求。

**验收：** 除上面这一个字段外快照不变；`grep -rn "def _ctx\|def _serialize" src/x_cli/commands` 无结果（4 份序列化函数名字不完全相同：`_serialize`、`_serialize_list`、`_serialize_users`，都会被这条匹配到）；每个命令模块里不再有手写的 `except XQueryError`。

### 第 4 阶段：补回丢失的能力

**目标：** skill 文档里教 LLM 用的东西，CLI 里都真的有。

**做什么：**

- `search` 加 `--auto-window`，接到 `core/window.adaptive_search`。`--since` / `--until` 缺省时用 `window.derive_since_until` 推出来。输出格式与普通 `search` 相同。`adaptive_search` 最坏会拆成 64 个子窗口，每个子窗口都是一轮分页请求，所以帮助文本里要写明它会发很多请求，并加一个子窗口数上限参数。
- 新增 `rank` 命令，把 `core/rank.py` 暴露出来。它从 stdin 读 JSON（接受完整信封，也接受裸数组），按参数过滤排序后输出同样的信封，这样可以写成 `x-cli search ... | x-cli rank ...`。参数与 `rank.py` 的函数一一对应：语言集合、垃圾模式（正则列表，从文件或重复参数传入）、互动阈值、是否丢弃推广和转推、权重和加成（JSON 字符串或文件）、作者多样性的 `decay` 和 `floor`、`--top`。
- `rank.py` 的设计原则是没有内置默认值，权重和垃圾模式必须由调用方给出，因为不同领域的标准不同。`rank` 命令要保持这一点：没传权重就不排序，没传模式就不过滤，不要替调用方发明默认值。
- 更新 skill 文档：`references/LLMs.md`、`read-mode.md`、`spam-patterns.md`、`search-plan.md`、`ranking-weights.md` 里所有 `from ... import rank` 的 Python 片段改成 `x-cli rank` 的命令行用法；核对文档里出现的每一个 `x-cli` 参数都真实存在。
- 加一个文档一致性测试：从 `skills/` 下的 markdown 里抽出所有 `x-cli <命令> --<参数>` 形式的片段，断言每个参数都能在对应命令的 `--help` 里找到。上次 `--auto-window` 就是这样丢的，这个测试能防止再发生。

**验收：** 一致性测试通过；`rank` 有单测，覆盖信封和裸数组两种输入、空输入、非法 JSON（退出码 2）；`--auto-window` 有离线测试，用假的抓取函数验证拆分和去重。

### 第 5 阶段：命令表面清理（未批准，不要做）

记录在此只为说明边界。内容是统一 `--top` 与 `--max`、把 `feed list` 改名、把 block 和 mute 从 `follow` 下移出、把 `user` 的 9 个互斥布尔参数改成子命令。它会破坏下游（独立仓库 `x-cli-skill`、`grok-x-skills`），需要所有者单独决定并发大版本。前四个阶段里如果发现某处"顺手改个参数名会更干净"，不要改，记到 PR 描述的"留给第 5 阶段"一节。

## 5. 每个 PR 的描述要包含

- 这个阶段改了什么，一段话。
- 行为变化清单：与本文"允许的行为变化"逐条对应；清单之外不应有任何变化。
- 快照差异：`git diff --stat tests/` 里快照文件的变化，逐个解释，或者写明"无"。
- 没做和没验证的：比如"未联网冒烟"、"某某场景缺 fixture"。
- 留给后续阶段或第 5 阶段的发现。

## 6. 什么时候停下来问

- 需要改测试断言、或快照出现本文未列出的差异。
- 需要联网，尤其是需要用真实账号。
- 发现本文描述与代码不符（文档基于 `afc8feb`，之后的提交可能改变了事实）。
- 发现现有行为看起来是 bug。默认做法是保持行为并在 PR 里报告，不要在重构 PR 里夹带修复，除非本文已明确列出。
- 一个阶段做下来发现改动量远超预期，或者需要动本文说"不要动"的东西。
