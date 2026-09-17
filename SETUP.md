<!-- ABOUTME: 本机安装与配置的完整步骤；README 只放最短路径，细节全部在这里。 -->
<!-- ABOUTME: 步骤顺序有依赖关系，第 3 步与第 4 步不可交换，原因见该步说明。 -->

# Setup

面向第一次跑这个项目的人。全程在本机，不连任何外部数据库。

平台：macOS 或 Linux（前置检查脚本用到 `nc`、`lsof`）。

## 1. 装前置

| 工具 | 用途 | 缺了会怎样 |
|---|---|---|
| Node 22+ | 前端 | `make doctor` 报错 |
| [uv](https://docs.astral.sh/uv/) | Python 依赖与运行 | 后端起不来 |
| Docker | 跑本机 Supabase 栈 | `supabase start` 失败 |
| [Supabase CLI](https://supabase.com/docs/guides/cli) | 本机 Postgres + 认证 + 存储 | 无数据库 |
| LibreOffice（可选） | 导出时预先算好目录页码 | 页码改由阅读器打开时解析 |
| pandoc（可选） | 重生成合成语料的 docx | 只影响重建语料 |

LibreOffice 只用于**预先算好**目录页码，是增强项不是硬依赖。目录项是指向同文档书签的
`PAGEREF` 域并带脏标记，Word 与 LibreOffice 打开时会自行解析出页码（实测与预计算逐条一致）。
差别只在页码是打开前就在那里、还是打开那一刻算出来；要把文档发给外部、希望对方打开即完整时，
装上它即可。

### 先看清占多少地方

仓库本身只有约 13 MB（一千余个文件，基本都是源码），但**跑起来要准备约 5.6 GB 磁盘**。
大头落在仓库目录之外——`du` 看项目文件夹是看不到的：

| 位置 | 项 | 约占 |
|---|---|---|
| 仓库外 | Supabase 容器镜像（首次 `supabase start` 拉取，7 个） | 3.2 GB |
| 仓库外 | Supabase 数据卷 | 1.5 GB |
| 仓库外 | LibreOffice（可选，见上） | 800 MB |
| 仓库内 | 前端依赖（npm install 产物） | 560 MB |
| 仓库内 | 后端虚拟环境（uv sync 产物） | 170 MB |
| 仓库内 | 前端构建缓存（随使用增长） | 150 MB 起 |

首次安装以网络下载为主，约 **15–30 分钟**，其中拉镜像占大头。

本项目已按实际用量裁掉三个 Supabase 组件（Studio、Edge Runtime 及其连带件，合计约 3 GB）：
产品不依赖它们，仓库内也没有 Edge Function。需要数据库管理界面时，把
`supabase/config.toml` 的 `[studio] enabled` 改回 `true` 再重起栈。

两项**默认不装**，需要时再说：

- **扫描件 OCR**（约 220 MB）：`uv sync --extra ocr`。不装时文字版 PDF、Word、Excel 照常解析，
  只有**扫描成图片的 PDF** 会明确报错提示缺该组件，不会静默跳过。
- **Playwright 浏览器**（约 540 MB）：只有跑 `npm run test:e2e` 才需要，
  用 `npx playwright install chromium` 装。

macOS 装法：

```bash
brew install node uv docker supabase/tap/supabase pandoc
brew install --cask libreoffice   # 可选：导出时预先算好目录页码
```

装完跑一次检查：

```bash
make doctor
```

## 2. 起本机 Supabase 栈

```bash
supabase start
```

首次运行要拉约 3.2 GB 镜像，按网络情况 10–20 分钟；之后再起是秒级。
完成后 `supabase status` 会打印一组连接参数，下一步要用。

## 3. 配置环境变量

```bash
cp backend/.env.example backend/.env
```

然后按 `supabase status` 的输出填三个值：

| `.env` 里的变量 | 取 `supabase status` 的哪一项 |
|---|---|
| `SUSTAINABILITY_DESK_SUPABASE_JWT_SECRET` | `JWT_SECRET` |
| `SUSTAINABILITY_DESK_SUPABASE_SERVICE_KEY` | `SERVICE_ROLE_KEY` |
| `SUSTAINABILITY_DESK_PUBLIC_SUPABASE_ANON_KEY` | `ANON_KEY` |

数据库与 API 地址（`DATABASE_URL`、`SUPABASE_URL`）模板里已经是本机默认值，通常不用改。

还要填一个模型凭据。默认走 Azure OpenAI：

```
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://<资源名>.cognitiveservices.azure.com/
```

也可以用任何 OpenAI 兼容服务（自建 vLLM、Ollama、代理网关），把 `.env.example` 里
`OPENAI_COMPAT_*` 三项注释打开即可，不用改代码。

## 4. 跑测试

```bash
make verify
```

**这一步必须在第 2、3 步之后**，顺序不能换。原因：`make verify` 直接跑 pytest，本身不检查
数据库是否可达；栈没起来时，账户、报告、生成运行、导出这些持久化用例会走 `pytest.skip`
静默跳过。结果是**你会看到全绿，但数据库层一条都没验证过**。先起栈再跑，才是真的通过。

## 5. 起服务

```bash
./scripts/dev/local-acceptance-stack.sh up
```

这一条会起三个进程：后端（:8010）、资料处理 worker、前端（:3000），并等到就绪再返回。
查看状态与停止：

```bash
./scripts/dev/local-acceptance-stack.sh status
./scripts/dev/local-acceptance-stack.sh down
```

也可以手动分三个终端起（调试时更方便看日志）：

```bash
make dev-backend     # http://127.0.0.1:8010
make dev-worker      # 队列消费进程
make dev-frontend    # http://localhost:3000
```

**worker 不能省**。资料处理与报告生成都经 Postgres 队列由 worker 消费；只起后端和前端的话，
页面能登录、能上传，但点「生成报告」会一直停在「等待开始」。

## 6. 建第一个账号

认证栈关闭了公开注册（界面没有注册页），所以第一个账号用命令建：

```bash
# 先看将要做什么
make provision-owner ARGS="--email you@example.com"

# 确认后执行
SUSTAINABILITY_DESK_OWNER_PASSWORD='<12 位以上，含大小写与数字>' \
SUSTAINABILITY_DESK_CONFIRM_PROVISION_OWNER=YES \
  make provision-owner ARGS="--email you@example.com --apply"
```

口令要求至少 12 位且同时含小写、大写与数字。缺变量时会明确报错，不会静默建出无法登录的账号；
已存在的账号一律复用，不重置密码。

然后打开 <http://localhost:3000> 登录。**用 `localhost` 而不是 `127.0.0.1`**：Next dev server
会拦截启动 hostname 之外的 origin 请求，用 `127.0.0.1` 访问会卡在「认证服务未配置」。

## 常见问题

**点「生成报告」一直在等待** — worker 没起。`./scripts/dev/local-acceptance-stack.sh status`
确认 `material-worker` 在运行。

**目录页码显示为 0 或需要刷新** — 没装 LibreOffice 时页码由阅读器打开时解析，属预期；
装上 LibreOffice 即可在导出时就算好。

**`make verify` 全绿但不确定数据库验过没有** — 见第 4 步。栈没起时持久化用例静默跳过；
`supabase status` 确认栈在跑，再重跑一次。

**页面显示「当前报告基于旧版契约创建」** — 该报告是更早的契约版本建的，新建一份即可。

**改了后端代码但行为没变** — 后端进程不自动重载栈脚本起的实例。`down` 再 `up`。
