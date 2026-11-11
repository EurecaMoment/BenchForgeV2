# BenchForgeV2

BenchForgeV2 develops a modular harness for spatial benchmark production and model evaluation. It supports two product lines: the framework that plans and runs evidence-backed workflows, and services that deliver evaluation or training data to RSI models. The official DSH source remains an external dependency.

```mermaid
flowchart TB
  subgraph framework[Harness framework]
    UX[DSH workbench and review UI]
    Plan[Planning, schemas and pipeline catalog]
    Orchestrate[Persistent runs, stage gates and recovery]
    Adapters[Provider and simulator adapters]
    Evidence[Evidence lineage and delivery gates]
    UX --> Plan --> Orchestrate --> Adapters
    Adapters --> Evidence
  end
  subgraph providers[External providers]
    LLM[Multimodal models]
    Sim[Isaac Sim and other simulators]
    Vision[Vision and geometry models]
  end
  Adapters --> LLM
  Adapters --> Sim
  Adapters --> Vision
  subgraph services[Evaluation and training services]
    Capture[Scene and evidence capture]
    Annotate[Evidence annotation]
    Dataset[Question and dataset production]
    Eval[Model evaluation]
    Train[Training data and experiment handoff]
  end
  Evidence --> Capture --> Annotate --> Dataset
  Dataset --> Eval
  Dataset --> Train
  Eval --> Report[RSI model results]
  Train --> RSI[RSI model training]
```

The diagram shows the intended boundaries. Some adapters, scene capture, dataset production, evaluation, and local training utilities exist today; the roadmap below separates those from planned work.

## 独立部署与三个 Agent 预设

下方提供 Linux 服务机的完整安装步骤，可在另一台机器或另一目录部署，
不需要已有 FIT 服务、旧 DSH 配置或其他分支的文件。按顺序执行
[独立部署指令](#独立部署指令linux)，先启动 Web、BenchForgeV2 和独立数据库。

本分支的完整安装生成三个相对独立的自定义 Agent 预设：

| 显示名称 | 用途 |
| --- | --- |
| **BenchForge** | 第一代评测构建，使用仓库内置的 BenchClaw 能力 |
| **BenchForgeV2** | 场景和数据生产，使用标准对话界面 |
| **BenchForgeV2_UI** | 同一生产能力，附带评测生产工作台 |

UI 版沿用旧会话的内部 ID，已有会话继续关联自己的工作台和历史产物。
基础安装不需要 GPU、模型密钥或 Isaac。模型问答、图像生成和仿真采集需要另外
配置对应服务；安装命令不会替你提供这些能力。工作台随完整预设一起接入，使用方式见
[工作台说明](docs/frontend-workbench-v2.md)。

## Current capabilities

- **Harness and workflows:** DSH plugin integration; a catalog of 89 tasks and 267 measurement templates; persistent pipelines that can resume; stage reviews; model and simulator adapters.
- **BenchForgeV2:** scene programs, asset generation, simulation queue, capture evidence, operator review, and public data export. See the [integration guide](integrations/spatialforge/README.md).
- **Evidence and delivery:** keep model-visible questions separate from authority answers; record source and capture evidence; validate declared public assets before packaging.
- **Evaluation and training:** deterministic local scoring, dataset packaging, spatial capability templates, and controlled training examples. These do not imply that a target RSI model has been evaluated or trained.

The task/template catalog and the separate spatial-learning capability graph serve different purposes. Model predictions are candidate annotations, not ground truth. Ground truth must be derived from an accepted official source, executable task, or simulator evidence.

## Architecture and roadmap

See [architecture and evolution](docs/ARCHITECTURE_AND_ROADMAP.zh-CN.md) for module boundaries, design rules, milestones, and staffing needs.

Near-term work prioritizes clear contracts, configuration ownership, resumable execution, delivery status, and a reproducible package. Follow-on work can add annotation review, evidence lineage, workflow orchestration, multimodal model iteration, performance work, and RSI evaluation/training services behind those boundaries.

## Quick start

Python 3.10+ can run an offline example without a model API, GPU, or simulator:

```bash
git -c http.version=HTTP/1.1 clone --branch main https://github.com/EurecaMoment/BenchForgeV2.git
cd BenchForgeV2
python benchforge.py demo
```

For the controlled dataset example:

```bash
python -m pip install -e ".[production,research]"
python examples/production_demo.py --workspace runs/production
```

To attach BenchForgeV2 tools to an existing DSH profile, follow [integration setup](integrations/README.md). To run the bundled service and a self-hosted desktop worker, use the [installation guide](docs/SPATIALFORGE_INSTALL.md). Neither path migrates or restarts an existing production deployment.

## Configuration

Start from the checked-in examples under `config/`. Copy an example to a matching ignored `*.local.json` file for machine-specific values. Keep credentials, local model paths, runtime databases, generated datasets, logs, and backups outside version control.

BenchForgeV2 uses one server configuration as the source for its execution mode and scene policy. In `production` mode, a valid scene policy is required. The client and DSH plugin read the resolved service URL and credentials without changing the server's environment. See [configuration and deployment boundaries](docs/SPATIALFORGE_INSTALL.md).

The root `.gitignore` excludes local configuration and generated output. CI also checks tracked path names for private configuration and disposable artifacts; this is a repository hygiene check, not a content-based secret scan.

## Verification

Run the [portable verification steps](docs/VALIDATION.md) locally. CI covers Windows and Linux on Python 3.10 and 3.12, with additional BenchForgeV2 tests on Python 3.12. A passing offline test does not certify live service availability, GPU throughput, simulator fidelity, or model quality. Those require acceptance on the named target system.

## 独立部署指令（Linux）

以下命令在 **Linux 服务器的 Bash 终端**执行，只有第 6 节的 SSH 隧道在自己的
电脑上执行。每一组成功后再执行下一组；失败时先处理错误，避免拿半安装状态启动。
示例选择 Web `3092`、API `3858`、数据库 `55548`，可在第 3 节改成自己的空闲端口。

### 0. 准备运行环境

| 软件 | 要求 | 检查命令 |
| --- | --- | --- |
| Git | **2.26 或更新**，DSH 安装脚本有此要求 | `git --version` |
| Python | 完整部署用 3.11、3.12 或 3.13，并包含 venv/ensurepip | `python3.11 --version` |
| Node.js / npm | Node 22.19+ 或 24+；建议 24 LTS | `node --version`、`npm --version` |
| Docker Engine / Compose | 当前用户可使用 Docker；Compose v2 支持 `--wait` | `docker info`、`docker compose version` |
| 系统工具 | `bash`、`ss`、`curl`、`setsid`、C/C++ 编译工具 | `command -v bash ss curl setsid cc make` |
| bubblewrap | 执行隔离任务代码时使用；基础页面验收不调用它 | `command -v bwrap` |

本文统一用 `python3.11` 创建环境；已经安装 3.12/3.13 时，只需把下面创建环境的
`python3.11` 换成该命令，后续都使用 `.venv/bin/python`。系统的 `python3` 可能仍是
3.8，不要仅凭命令存在就继续。需要联网下载 GitHub 源码、npm/PyPI 包和 PostgreSQL 镜像。

**已有 Conda 时，推荐创建专用环境，避免修改其他项目的 Git、Node 或 Python：**

```bash
# 新终端找不到 conda 时，先加载自己安装位置的初始化脚本。
# Miniconda 默认位置：
source "$HOME/miniconda3/etc/profile.d/conda.sh"
# Miniforge 用户改用：source "$HOME/miniforge3/etc/profile.d/conda.sh"

conda create -n benchforge --override-channels -c conda-forge \
  --repodata-fn current_repodata.json python=3.11 nodejs=24 'git>=2.26' -y
conda activate benchforge
git --version
python3.11 --version
node --version
npm --version
```

如果长时间停在 `Collecting package metadata`，先按 Ctrl+C 结束这次创建，再用
[TUNA 的 conda-forge 镜像](https://mirrors.tuna.tsinghua.edu.cn/help/anaconda/) 重试。
下列命令只为本次创建选择镜像，不修改其他项目的全局 Conda 配置：

```bash
conda create -n benchforge --override-channels \
  -c https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge \
  --repodata-fn current_repodata.json python=3.11 nodejs=24 'git>=2.26' -y
conda activate benchforge
git --version
python3.11 --version
node --version
npm --version
```

若提示 `benchforge` 已存在，先激活并检查版本；已有环境符合要求时直接使用，
不符合时为新环境换一个名字，保留旧环境。

没有 Conda 可先按 [Miniforge 官方安装说明](https://github.com/conda-forge/miniforge#install)
安装，然后执行上述创建环境的命令；已有符合版本要求的工具可跳过创建环境。
再次登录服务器后，先 `conda activate benchforge`，再进入仓库目录。

Ubuntu/Debian 缺少系统工具时，管理员可执行：

```bash
sudo apt-get update
sudo apt-get install -y build-essential curl ca-certificates iproute2 util-linux bubblewrap
```

Docker 尚未安装时，按 [Docker 官方 Linux 安装说明](https://docs.docker.com/engine/install/)
选择系统，安装 Engine 和 Compose plugin。普通用户访问权限按
[安装后配置](https://docs.docker.com/engine/install/linux-postinstall/) 设置；
重新登录后确认下面两条命令成功，再继续。不要为了绕过权限问题用 sudo 运行整套 Python/DSH。

```bash
docker info
docker compose version
```

### 1. 下载 main 到新目录

`benchforge-3092` 是示例部署的独立目录名；已有同名目录时换一个新名称。

```bash
cd "$HOME"
git -c http.version=HTTP/1.1 clone --branch main --single-branch https://github.com/EurecaMoment/BenchForgeV2.git benchforge-3092
cd benchforge-3092
git branch --show-current
```

最后一行应输出 `main`。之后所有服务器命令都在这个目录执行。
不要复制旧部署的 `config/`、`.benchforge/` 或 `.deployment/`。
`-c http.version=HTTP/1.1` 仅对本次克隆生效，用于减少部分网络链路上的 GitHub
连接中断，不修改全局 Git 配置。若下载仍失败，保留错误并检查网络；重试前确认目标
目录尚未创建，已有目录则换新名称，不要删除已有部署。

### 2. 安装 Python 后端与 Node 插件

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[dsh,production,research]'
npm ci --prefix integrations
.venv/bin/python spatialforge_app.py setup
```

`.venv/` 是核心与 DSH 辅助程序环境，`.deployment/venv/` 是后端环境。
`npm ci --prefix integrations` 安装插件依赖，不能用 Python 安装替代。
这一步完成后还没有启动服务，也没有配置模型或仿真器。

### 3. 选择端口并生成本实例配置

先检查这三个端口；没有输出表示当前未被监听。如有输出，换三个空闲端口，并在
后面的初始化、启动和隧道命令中使用对应数值。不要停止别人占用端口的进程。

```bash
ss -ltnp | grep -E ':(3092|3858|55548)\b' || true
```

```bash
.venv/bin/python spatialforge_app.py init \
  --port 3858 --db-port 55548 --project benchforge-3092
```

`--project` 是本实例的数据库项目名，同机不同部署必须不同。它保存为
`config/database.env` 的 `COMPOSE_PROJECT_NAME`，启动和停止会读取同一值；
无需每次再手动指定。不要设置指向其他实例的 `COMPOSE_PROJECT_NAME` 环境变量。

初始化会自动生成随机数据库密码及两种 token，并建立匹配的客户端、服务端与 worker
配置。重复 `init` 会保留已有端口、项目配置和凭据，不会按新参数覆盖；因此首次就应
选好端口。如果默认客户端文件丢失，重跑 `init` 可从已有服务端配置补齐。

| 文件 | 用途 | 基础启动是否需要手改 |
| --- | --- | --- |
| `config/database.env` | 数据库密码、端口、独立项目名和连接地址 | 否 |
| `config/spatialforge-server.local.json` | API 端口、数据库环境变量引用、产物目录、服务凭据和生产策略 | 否 |
| `config/spatialforge.local.json` | 引用服务端配置，继承地址、operator token 和生产策略 | 否 |
| `config/models.local.json` | 生成模型的解释器和权重位置 | 用模型时配置 |
| `config/worker.local.json` | 引用服务端配置，另设本机 Isaac 路径和 worker 参数 | 接入 worker 时配置 |

服务端配置是唯一连接信息来源；客户端和同机 worker 不重复保存 token 或端口。
本地配置、虚拟环境、日志、产物都已被 Git 忽略；不要将密码或 token 上传到仓库。
未使用 `--project` 的旧配置仍沿用 `benchforgev2-spatialforge` 项目名。

### 4. 安装 DSH 并生成完整预设

```bash
.venv/bin/python spatialforge_app.py dsh-setup
```

此命令从公开仓库下载锁定版本的 DSH，在 `third_party/deepseek-harness/` 构建，
然后生成 `config/benchforge.local.json`、含三个预设和工作台插件的
`.deployment/benchforge.local.yml` 与
`.benchforge/runtime.json`。首次源码构建可能需要数分钟，最后应看到
`Ready. Run: python benchforge.py start`，且命令退出码为 0。

这里必须使用 **`dsh-setup`**（或下方等价命令），它会将第 3 节的服务配置接入预设：

```bash
# 与上一条二选一，不需要重复执行。
.venv/bin/python benchforge.py setup --spatialforge-config config/spatialforge.local.json
```

单独执行 `benchforge.py setup` 只安装第一代 `BenchForge`，不会接入另外两个 BenchForgeV2 预设。
重新生成预设会覆盖手工追加的模型配置，已有修改时先备份本地 YAML。
DSH 本身默认通过锁定的 pnpm 版本安装；不需要复制另一部署的 DSH。

如果此步骤在下载 DSH 时出现 `unexpected eof`、`SSL_read` 或 `schannel` 连接错误，
先确认网络恢复。使用 Git 2.31+（上方推荐的 Conda 环境满足要求），可按下面的方式
重试，让本次安装调用的 Git 也使用 HTTP/1.1；这些环境变量只在该命令中生效：

```bash
GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=http.version GIT_CONFIG_VALUE_0=HTTP/1.1 \
  .venv/bin/python spatialforge_app.py dsh-setup
```

该命令仍从锁定的公开仓库版本安装，不需要手工复制 DSH 文件或改全局配置。

### 5. 启动本实例

```bash
BENCHFORGE_WEB_PORT=3092 ./start.sh
```

脚本依次启动本实例的 PostgreSQL、BenchForgeV2 和 DSH，日志及 PID 写入当前目录的
`.benchforge/`。成功时会打印带 token 的 Web 地址，例如：

```text
http://127.0.0.1:3092/?token=本次启动的实际令牌
```

后台服务与终端分离，安装成功后关闭 SSH 终端不会结束服务。
每次启动或重启都应显式写 `BENCHFORGE_WEB_PORT=3092`；省略时脚本使用 `3081`。
DSH 的会话和设置保存在当前目录 `.benchforge/dsh-home/`。

如果没有正常结束或没有新地址，先查看本实例日志；仅端口监听不能证明插件加载完成：

```bash
tail -n 40 .benchforge/logs/spatialforge.log
tail -n 60 .benchforge/logs/dsh.log
```

### 6. 在自己的电脑上打开网页

在**自己的电脑**新开终端，将 `your-user@your-server` 替换为服务器账号与地址
（也可使用已有 SSH 别名）：

```bash
ssh -N -o ExitOnForwardFailure=yes -L 13092:127.0.0.1:3092 your-user@your-server
```

此命令持续运行、不返回提示符是正常现象，保持终端打开。在浏览器中使用第 5 节
输出的完整 URL，把端口 `3092` 改为本地 `13092`，保留原 token：

```text
http://127.0.0.1:13092/?token=第5节输出的实际令牌
```

本地 `13092` 被占用时只改隧道左侧端口，并同步改浏览器 URL。
直接打开不带 token 的根地址可能返回 `dsh web authentication required`。
进入页面后，新建会话应能选择 **`BenchForge`、`BenchForgeV2`、`BenchForgeV2_UI`**。
选择 `BenchForgeV2_UI` 查看工作台；尚未配置模型时先不要发起生产任务。

### 7. 验收基础安装

回到**服务器的仓库目录**执行：

```bash
# 检查该实例的数据库容器，状态应为 healthy。
docker compose --env-file config/database.env -f components/spatialforge/deploy/compose.yml ps

# 发起真实、带认证的 POST /catalog，不需要手动复制 token。
.venv/bin/python spatialforge_app.py status
.venv/bin/python integrations/spatialforge/cli.py status --config config/spatialforge.local.json

# 只运行一次不需要 GPU/模型的离线例子。
.venv/bin/python benchforge.py demo
```

两次目录查询应返回 `catalog_schema: spatialforge.operator-catalog/v2` 和 `sections`，
不应返回认证错误。`model: unconfigured` 表示还没有配置后端规划模型，基础安装允许此状态。
不要用普通 `GET /catalog` 的 HTTP 200 代替检查：GET 会返回介绍页，实际目录接口是 POST。

离线例子应输出 `Offline demo complete: 2 items, exact-match accuracy 0.5`，
其中一个预测故意错误，0.5 是预期结果。产物在 `runs/quickstart/`。
再确认网页能够登录、三个预设均可选，且 `BenchForgeV2_UI` 能显示工作台、没有加载错误。
页面验收必须新建并选择 **`BenchForgeV2_UI`** 会话、绑定本实例的独立工作区，确认
“评测计划、场景预览、标注预览、评测配置与题目表、最终报告”五个阶段可以打开。
只看到 DSH 默认 Standard 对话页面，不能算工作台安装成功。新实例应显示空的生产状态，
不应读取其他实例的历史任务；原有样板对话在各自实例中继续保留原工作区和产物关联。
这些结果验证基础部署；Isaac 画面、生成模型质量和真实生产吞吐需要分别验收。

### 8. 配置自己需要的模型和仿真能力

- **驱动 DSH 对话的模型**：在 DSH 网页的模型/提供方设置中配置自己可访问的提供方、
  模型 ID 和凭据。新安装不会继承另一部署的账号或 Qwen 服务。可使用官方提供方；
  自定义 OpenAI 兼容服务的配置按所用 DSH 提供方支持的字段填写。
- **BenchForgeV2 自动规划模型**：按
  [服务端模型配置](docs/SPATIALFORGE_INSTALL.md#4-配置扩散分割生成资产和深度)
  填写自己的 `model_url`、`model_id`、密钥环境变量。与 DSH 对话模型是两份独立配置。
- **图像、分割、深度、三维生成服务**：按
  [模型安装](docs/SPATIALFORGE_MODELS.md) 或 [外部模型接口](docs/MODEL_SERVICES.md)
  配置所需服务。示例配置中的 localhost 地址只表示连接位置，不代表相应模型已运行。
- **Isaac 真值与采集**：按 [自托管安装指南](docs/SPATIALFORGE_INSTALL.md)
  接入自己的 Isaac 和 worker，使用本次生成的 `config/worker.local.json`。
  先验收文档中的程序化 capture 例子，再让 Agent 发起生成任务。
- **场景工作台 UI**：完整安装已经接入。选择 `BenchForgeV2_UI` 使用，见
  [工作台说明](docs/frontend-workbench-v2.md)；另外两个预设使用标准对话界面。

模型凭据可存放在被忽略的 `config/dsh.env` 中，`start.sh` 启动 DSH 时会加载它；
仅在所用提供方确实读取对应环境变量时才有作用。

### 9. 停止、重启和更新

以下命令仍在**本实例目录**执行，已安装的运行环境应处于激活状态：

```bash
# 修改本地配置后，保留数据库并重启应用。
BENCHFORGE_WEB_PORT=3092 ./restart.sh

# 只停止应用，保留数据库运行。
BENCHFORGE_WEB_PORT=3092 ./shutdown.sh --keep-db

# 停止本实例全部服务；数据库数据卷仍然保留。
BENCHFORGE_WEB_PORT=3092 ./shutdown.sh
```

更新 main 时先保留自己的本地配置和数据，再停止应用、拉取代码、更新依赖：

```bash
BENCHFORGE_WEB_PORT=3092 ./shutdown.sh --keep-db
git pull --ff-only origin main
.venv/bin/python -m pip install -e '.[dsh,production,research]'
npm ci --prefix integrations
.venv/bin/python spatialforge_app.py setup
BENCHFORGE_WEB_PORT=3092 ./start.sh
```

除非确实需要重新生成预设，否则不要再次运行 `dsh-setup` 覆盖自己的模型配置。
需要重新生成时先备份 `.deployment/benchforge.local.yml`，生成后合回自己的追加项。
不要通过复制另一套实例的配置来升级，也不要删除 `.deployment/` 或数据库卷。

### 10. 常见失败及处理

| 现象 | 原因与处理 |
| --- | --- |
| `Git 2.26 or newer is required` | 当前终端仍使用旧 Git。执行第 0 节环境激活与版本检查，确认 `git --version` 后重跑第 4 节。不要跳过官方安装检查。 |
| `Python 3.10+ is required` / `BenchForgeV2 requires Python 3.11` | 选择了旧系统 Python；按第 0 节准备 3.11，再创建 `.venv`。 |
| `venv` / `ensurepip` 缺失 | Conda 路线包含所需组件；系统 Python 路线需安装对应版本的 venv 包，例如 `python3.11-venv`。 |
| Docker `permission denied` / daemon 不可用 | 完成 Docker 官方安装后配置并重新登录，先让 `docker info` 成功。 |
| 端口占用 | 新部署在初始化前换空闲端口和独立 `--project`；不要让启动脚本误认其他实例的监听端口。 |
| `spatialforge-tools` 的配置文件 `ENOENT` | 先执行第 3 节，再执行第 4 节；文件搬过位置时，修改生成预设里 `serviceConfig` 的实际路径。重跑 `init` 只补齐默认缺失客户端。 |
| `Cannot find module '@deepseek-ai/...'` | 在仓库执行 `npm ci --prefix integrations`，然后重启当前实例。 |
| token 无效 / `dsh web authentication required` | 使用当前进程的新 URL；通过隧道时只替换端口，保留完整 token。 |
| 端口已监听却没有新 token | 查看 `.benchforge/logs/dsh.log` 的真实错误；并非所有情况都是 inotify 问题。 |
| 明确出现 `ENOSPC: file watchers` | 主机文件监视器配额耗尽；可请管理员提高 inotify 配额，或按下方方法在当前实例关闭配置热更新。 |
| 页面无可用模型 / 模型请求失败 | 完成第 8 节，核对提供方、模型 ID、地址与凭据；页面能打开不代表模型已配置。 |

关闭当前实例的配置热更新：在 **`.deployment/benchforge.local.yml` 的顶层列表末尾**追加
以下条目，然后执行第 9 节的重启命令。这是可选修复，生成预设时不会自动追加：

```yaml
- id: hmr
  disabled: true
```

追加前可备份：`cp .deployment/benchforge.local.yml .deployment/benchforge.local.yml.bak-before-hmr`。
禁用后，每次修改配置需重启；重新生成预设也需重新保留这条覆盖。

## 已有后端时的连接方式

这条路线适用于**明确要复用既有服务**的人，独立部署请使用上面的第 0–7 节。
同机复用时，复制客户端示例，将 `service_config` 改为既有服务端 JSON 的实际路径；
地址、operator token 和生产策略从该文件继承，再验证连接和生成预设：

```bash
cp config/spatialforge.example.json config/spatialforge.local.json
# 用编辑器将 service_config 改为既有服务端配置的路径后继续。
.venv/bin/python integrations/spatialforge/cli.py status --config config/spatialforge.local.json
.venv/bin/python benchforge.py setup --spatialforge-config config/spatialforge.local.json
.venv/bin/python benchforge.py start --port 3092 --no-open
```

跨机器连接时，可改用独立客户端 JSON，移除 `service_config`，填写 `service_url`、
`operator_token_env`、`execution_mode` 和本机可读的 `scene_policy_path`；生产模式必须提供
与后端一致的有效策略文件。将 token 注入指定环境变量后再执行上述验证与启动。

这条路线不使用 `start.sh` 创建另一数据库。已构建 DSH 可额外传入
`--dsh-root /path/to/deepseek-harness`；新手独立安装无需此选项。

## 开发检查与进一步文档

以下是开发者修改代码后的检查，不是部署者必须跑完的安装步骤：

```bash
.venv/bin/python -m unittest discover -s integrations/tests -v
.venv/bin/python integrations/spatialforge/smoke.py
```

- [Pipeline catalog and evidence requirements](docs/pipelines.md)
- [Spatial learning and training utilities](docs/spatial-learning.md)
- [Model-service boundary](docs/MODEL_SERVICES.md)
- [Self-hosted BenchForgeV2 installation](docs/SPATIALFORGE_INSTALL.md)
