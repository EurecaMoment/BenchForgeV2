# BenchForgeV2

BenchForgeV2 is the maintained repository for the second-generation DSH mode,
SpatialForge integrations, composable benchmark pipelines, and spatial-learning
tools. New integration work belongs here; the official `deepseek-harness` source
is an external dependency and is not modified by this repository.

## 从 main 独立部署

下方提供 Linux 服务机的完整安装步骤，可在另一台机器或另一目录部署，
不需要已有 FIT 服务、旧 DSH 配置或其他分支的文件。按顺序执行
[独立部署指令](#独立部署指令linux)，先启动 Web、SpatialForge 和独立数据库。

本分支生成的自定义 Agent 预设显示为 **`BenchForgev2`**，内部 ID 为
`benchforgev2`。这是 `main` 当前的名称。已有部署中的 `BenchForge`、
`SpatialForge` 名称及其历史绑定见 [集成说明](integrations/README.md)，
不属于新安装的前置条件。

基础安装不需要 GPU、模型密钥或 Isaac。模型问答、图像生成和仿真采集需要另外
配置对应服务；安装命令不会替你提供这些能力。场景工作台 UI 是可选插件，见
[工作台安装说明](docs/frontend-workbench-v2.md)。

## What is included

- **Composable pipelines:** retrieve 89 user-defined tasks and 267 exact
  measurement-template variants from the 出题模板; interpret an objective into
  explicit template selections; run, resume, inspect and deterministically
  evaluate pipeline artifacts. Only 17 variants currently have built-in
  program generators. Other variants require official, program, or simulation
  evidence and task-specific adapters before they become production data.
- **Spatial learning:** a separate graph of 27 capability nodes, each with 120
  template specifications, plus program-grounded dataset generation, curriculum
  training, experiments, checkpointing and live training monitoring. See
  [Spatial learning](docs/spatial-learning.md).
- **SpatialForge:** reference/layout tools, scene programs, assets, model-service
  clients, capture/evidence review and data export. See the
  [SpatialForge integration guide](integrations/spatialforge/README.md).
- **DSH integration:** installable Node plugin bundles and preset builders. DSH
  source, external model startup code, model weights and simulator deployment
  are not vendored as BenchForgeV2 runtime services.

The capability graph and the 出题模板 catalog are different resources: the
27-node graph is not a relabeling of the 89-task/267-template catalog. Generated
records keep public questions separate from authority data; model predictions
do not become ground truth. Ground truth comes from official sources, task
programs or simulation.

## Local examples

Python 3.10+ can run the offline benchmark example without a model API or GPU:

```bash
git clone https://github.com/EurecaMoment/BenchForgeV2.git
cd BenchForgeV2
python benchforge.py demo
```

For a programmatic production example:

```bash
python -m pip install -e ".[production,research]"
python examples/production_demo.py --workspace runs/production
```

This draws and scores a small set of controlled examples. It is not an Isaac
scene-quality, model-training, or benchmark-approval result. The CPU learning
demo trains only a small controlled Transformer task:

```bash
python examples/spatial_learning_demo.py --workspace runs/cpu-training
```

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
| bubblewrap | 执行隔离任务代码时使用；基础页面验收不调用它 | `bwrap --version` |

本文统一用 `python3.11` 创建环境；已经安装 3.12/3.13 时，只需把下面创建环境的
`python3.11` 换成该命令，后续都使用 `.venv/bin/python`。系统的 `python3` 可能仍是
3.8，不要仅凭命令存在就继续。需要联网下载 GitHub 源码、npm/PyPI 包和 PostgreSQL 镜像。

**已有 Conda 时，推荐创建专用环境，避免修改其他项目的 Git、Node 或 Python：**

```bash
# 新终端找不到 conda 时，先加载自己安装位置的初始化脚本。
# Miniconda 默认位置：
source "$HOME/miniconda3/etc/profile.d/conda.sh"
# Miniforge 用户改用：source "$HOME/miniforge3/etc/profile.d/conda.sh"

conda create -n benchforge-main --override-channels -c conda-forge python=3.11 nodejs=24 'git>=2.26' -y
conda activate benchforge-main
git --version
python3.11 --version
node --version
npm --version
```

没有 Conda 可先按 [Miniforge 官方安装说明](https://github.com/conda-forge/miniforge#install)
安装，然后执行上述创建环境的命令；已有符合版本要求的工具可跳过创建环境。
再次登录服务器后，先 `conda activate benchforge-main`，再进入仓库目录。

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

`benchforge-main-3092` 是这次部署的独立目录名；已有同名目录时换一个新名称。

```bash
cd "$HOME"
git clone --branch main --single-branch https://github.com/EurecaMoment/BenchForgeV2.git benchforge-main-3092
cd benchforge-main-3092
git branch --show-current
```

最后一行应输出 `main`。之后所有服务器命令都在这个目录执行。
不要复制旧部署的 `config/`、`.benchforge/` 或 `.spatialforge/`。

### 2. 安装 Python 后端与 Node 插件

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[dsh,production,research]'
npm ci --prefix integrations
.venv/bin/python spatialforge_app.py setup
```

`.venv/` 是核心与 DSH 辅助程序环境，`.spatialforge/venv/` 是后端环境。
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
  --port 3858 --db-port 55548 --project benchforge-main-3092
```

`--project` 是本实例的数据库项目名，同机不同部署必须不同。它保存为
`config/database.env` 的 `COMPOSE_PROJECT_NAME`，启动和停止会读取同一值；
无需每次再手动指定。不要设置指向其他实例的 `COMPOSE_PROJECT_NAME` 环境变量。

初始化会自动生成随机数据库密码及两种 token，并建立匹配的客户端、服务端与 worker
配置。重复 `init` 会保留已有端口、项目配置和凭据，不会按新参数覆盖；因此首次就应
选好端口。如果默认客户端文件丢失，重跑 `init` 可从已有服务端配置补齐。

| 文件 | 用途 | 基础启动是否需要手改 |
| --- | --- | --- |
| `config/database.env` | 数据库密码、端口、独立项目名 | 否 |
| `config/spatialforge-server.local.json` | API 端口、数据库地址、产物目录、服务凭据 | 否 |
| `config/spatialforge.local.json` | 插件连接 API 的地址和 operator token | 否 |
| `config/models.local.json` | 生成模型的解释器和权重位置 | 用模型时配置 |
| `config/worker.local.json` | Isaac worker 的服务地址和 worker token | 接入 worker 时配置 |

本地配置、虚拟环境、日志、产物都已被 Git 忽略；不要将密码或 token 上传到仓库。
未使用 `--project` 的旧配置仍沿用 `benchforgev2-spatialforge` 项目名。

### 4. 安装 DSH 并生成完整预设

```bash
.venv/bin/python spatialforge_app.py dsh-setup
```

此命令从公开仓库下载锁定版本的 DSH，在 `third_party/deepseek-harness/` 构建，
然后生成 `config/benchforge.local.json`、`config/benchforge.local.yml` 与
`.benchforge/runtime.json`。首次源码构建可能需要数分钟，最后应看到
`Ready. Run: python benchforge.py start`，且命令退出码为 0。

这里必须使用 **`dsh-setup`**（或下方等价命令），它会将第 3 节的服务配置接入预设：

```bash
# 与上一条二选一，不需要重复执行。
.venv/bin/python benchforge.py setup --spatialforge-config config/spatialforge.local.json
```

单独执行 `benchforge.py setup` 不会接入 SpatialForge 工具。
重新生成预设会覆盖手工追加的模型配置，已有修改时先备份本地 YAML。
DSH 本身默认通过锁定的 pnpm 版本安装；不需要复制另一部署的 DSH。

### 5. 启动本实例

```bash
BENCHFORGE_WEB_PORT=3092 ./start.sh
```

脚本依次启动本实例的 PostgreSQL、SpatialForge 和 DSH，日志及 PID 写入当前目录的
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
进入页面后，新建会话应能选择 **`BenchForgev2`**；尚未配置模型时先不要发起生产任务。

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
再确认网页能够登录、`BenchForgev2` 预设可选且没有加载错误。
这些结果验证基础部署；Isaac 画面、生成模型质量和真实生产吞吐需要分别验收。

### 8. 配置自己需要的模型和仿真能力

- **驱动 DSH 对话的模型**：在 DSH 网页的模型/提供方设置中配置自己可访问的提供方、
  模型 ID 和凭据。新安装不会继承另一部署的账号或 Qwen 服务。可使用官方提供方；
  自定义 OpenAI 兼容服务的配置按所用 DSH 提供方支持的字段填写。
- **SpatialForge 自动规划模型**：按
  [服务端模型配置](docs/SPATIALFORGE_INSTALL.md#4-配置扩散分割生成资产和深度)
  填写自己的 `model_url`、`model_id`、密钥环境变量。与 DSH 对话模型是两份独立配置。
- **图像、分割、深度、三维生成服务**：按
  [模型安装](docs/SPATIALFORGE_MODELS.md) 或 [外部模型接口](docs/MODEL_SERVICES.md)
  配置所需服务。示例配置中的 localhost 地址只表示连接位置，不代表相应模型已运行。
- **Isaac 真值与采集**：按 [自托管安装指南](docs/SPATIALFORGE_INSTALL.md)
  接入自己的 Isaac 和 worker，使用本次生成的 `config/worker.local.json`。
  先验收文档中的程序化 capture 例子，再让 Agent 发起生成任务。
- **场景工作台 UI**：基础 Web 是 DSH 对话界面。需要工作台时，继续按
  [工作台安装说明](docs/frontend-workbench-v2.md) 配置相应预设。

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
需要重新生成时先备份 `config/benchforge.local.yml`，生成后合回自己的追加项。
不要通过复制另一套实例的配置来升级，也不要删除 `.spatialforge/` 或数据库卷。

### 10. 常见失败及处理

| 现象 | 原因与处理 |
| --- | --- |
| `Git 2.26 or newer is required` | 当前终端仍使用旧 Git。执行第 0 节环境激活与版本检查，确认 `git --version` 后重跑第 4 节。不要跳过官方安装检查。 |
| `Python 3.10+ is required` / `SpatialForge requires Python 3.11` | 选择了旧系统 Python；按第 0 节准备 3.11，再创建 `.venv`。 |
| `venv` / `ensurepip` 缺失 | Conda 路线包含所需组件；系统 Python 路线需安装对应版本的 venv 包，例如 `python3.11-venv`。 |
| Docker `permission denied` / daemon 不可用 | 完成 Docker 官方安装后配置并重新登录，先让 `docker info` 成功。 |
| 端口占用 | 新部署在初始化前换空闲端口和独立 `--project`；不要让启动脚本误认其他实例的监听端口。 |
| `spatialforge-tools` 的配置文件 `ENOENT` | 先执行第 3 节，再执行第 4 节；文件搬过位置时，修改生成预设里 `serviceConfig` 的实际路径。重跑 `init` 只补齐默认缺失客户端。 |
| `Cannot find module '@deepseek-ai/...'` | 在仓库执行 `npm ci --prefix integrations`，然后重启当前实例。 |
| token 无效 / `dsh web authentication required` | 使用当前进程的新 URL；通过隧道时只替换端口，保留完整 token。 |
| 端口已监听却没有新 token | 查看 `.benchforge/logs/dsh.log` 的真实错误；并非所有情况都是 inotify 问题。 |
| 明确出现 `ENOSPC: file watchers` | 主机文件监视器配额耗尽；可请管理员提高 inotify 配额，或按下方方法在当前实例关闭配置热更新。 |
| 页面无可用模型 / 模型请求失败 | 完成第 8 节，核对提供方、模型 ID、地址与凭据；页面能打开不代表模型已配置。 |

关闭当前实例的配置热更新：在 **`config/benchforge.local.yml` 的顶层列表末尾**追加
以下条目，然后执行第 9 节的重启命令。这是可选修复，生成预设时不会自动追加：

```yaml
- id: hmr
  disabled: true
```

追加前可备份：`cp config/benchforge.local.yml config/benchforge.local.yml.bak-before-hmr`。
禁用后，每次修改配置需重启；重新生成预设也需重新保留这条覆盖。

## 已有后端时的连接方式

这条路线适用于**明确要复用既有服务**的人，独立部署请使用上面的第 0–7 节。
复制示例配置，填写自己的真实服务地址与 operator token，再验证连接和生成预设：

```bash
cp config/spatialforge.example.json config/spatialforge.local.json
# 用编辑器填写 config/spatialforge.local.json 后继续。
.venv/bin/python integrations/spatialforge/cli.py status --config config/spatialforge.local.json
.venv/bin/python benchforge.py setup --spatialforge-config config/spatialforge.local.json
.venv/bin/python benchforge.py start --port 3092 --no-open
```

这条路线不使用 `start.sh` 创建另一数据库。已构建 DSH 可额外传入
`--dsh-root /path/to/deepseek-harness`；新手独立安装无需此选项。

## 开发检查与进一步文档

以下是开发者修改代码后的检查，不是部署者必须跑完的安装步骤：

```bash
.venv/bin/python -m unittest discover -s integrations/tests -v
.venv/bin/python integrations/spatialforge/smoke.py
```

- [Pipeline catalog and evidence requirements](docs/pipelines.md)
- [Spatial learning, training and monitoring](docs/spatial-learning.md)
- [Model-service client boundary](docs/MODEL_SERVICES.md)
- [Self-hosted SpatialForge install](docs/SPATIALFORGE_INSTALL.md)
- [Validation scope and history](docs/VALIDATION.md)
