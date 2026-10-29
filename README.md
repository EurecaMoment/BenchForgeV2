# BenchForgeV2

BenchForgeV2 is the maintained repository for the second-generation DSH mode,
SpatialForge integrations, composable benchmark pipelines, and spatial-learning
tools. New integration work belongs here; the official `deepseek-harness` source
is an external dependency and is not modified by this repository.

## Modes and deployment

The DSH preset names identify separate modes in the same deployment:

| Mode | Purpose | DSH profile binding |
| --- | --- | --- |
| `BenchForge` | Retained first-generation benchmark mode | Legacy mode |
| `BenchForgev2` | Second-generation published mode | `.deployment/published` on FIT |
| `SpatialForge` | Second-generation development mode with scene tools | Repository checkout on FIT |

The maintained FIT checkout is `/home/maqiang/GitHub/BenchForgeV2`, branch
`SpatialForge`; the public repository is
[EurecaMoment/BenchForgeV2](https://github.com/EurecaMoment/BenchForgeV2).
The active production simulation route is DSH on FIT → the FIT SpatialForge
service and queue → the external `a800-remote-fit` dispatcher → FIT's local
reverse-SSH endpoint `127.0.0.1:18766` → `thunlp-node1` running Isaac Sim 6.2.0
on A800 → capture and evidence returned to FIT. `desktop-isaac` is a retained
database lease name; it does not identify the active remote worker. The A800
dispatcher and its server-side Isaac deployment are outside this repository.

```mermaid
flowchart LR
  DSH[DSH on FIT] -->|BenchForgev2 / SpatialForge preset| Plugin[BenchForgeV2 plugins]
  Plugin -->|benchmark, pipeline, learning tools| Core[BenchForgeV2 Python package]
  Plugin -->|scene tools| SF[FIT SpatialForge service and queue]
  SF --> Dispatcher[External a800-remote-fit dispatcher]
  Dispatcher -->|FIT 127.0.0.1:18766 reverse SSH| Isaac[thunlp-node1 A800 / Isaac Sim 6.2.0]
  Isaac -->|capture and evidence| SF
  Plugin -->|independent model API clients| Models[External model services]
  Desktop[Optional self-hosted Windows Isaac worker] --> SF
```

The Windows worker is a supported self-hosted deployment option, not the active
FIT production route. External model services, weights, simulator installations,
assets, credentials, and production artifacts remain in their own deployment
locations. The lightweight clients in this repository do not start or migrate
those services.

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

## DSH setup


已有 SpatialForge 后端和桌面 worker 时，复制
`config/spatialforge.example.json` 为 `config/spatialforge.local.json`，
填写服务 URL 与 `operator_token`，然后执行：

```bash
python integrations/spatialforge/cli.py status --config config/spatialforge.local.json
python benchforge.py setup --spatialforge-config config/spatialforge.local.json
=======
The simple launcher below builds a private DSH runtime and installs the retained
first-generation `BenchForge` mode for local use. It does not reproduce FIT's
current SpatialForge/A800 deployment:

```bash
python benchforge.py setup

python benchforge.py start
```

To attach the second-generation bundle to an existing DSH profile, follow
[integration installation and preset selection](integrations/README.md). To run
the bundled SpatialForge server and a self-hosted desktop worker, use the
[self-hosted installation guide](docs/SPATIALFORGE_INSTALL.md); it is an
alternative deployment, not a migration recipe for FIT's A800 worker.


## 全流程启动（数据库 + SpatialForge + DSH）

以下命令全部在仓库根目录执行，配置只读取本仓库的 `config/` 目录，不需要设置任何
配置类环境变量。示例端口为：SpatialForge `3856`、PostgreSQL `55546`、DSH `3081`。

### 1. 安装依赖

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e ".[dsh,production,research]"
npm ci --prefix integrations
```

`npm ci --prefix integrations` 不能省略：DSH 插件以裸包名导入
`@deepseek-ai/dsh-tools` 等模块，缺少该目录时插件无法加载。
DSH 本身可用 `python benchforge.py setup` 安装，或用
`python benchforge.py setup --dsh-root /path/to/deepseek-harness` 复用已构建的
DSH。

### 2. 生成或填写配置

首次使用由 init 生成私密配置（文件权限 600，且被 `.gitignore` 忽略）：

```bash
.venv/bin/python spatialforge_app.py init --port 3856 --db-port 55546
```

已有配置时跳过本步。需要手工调整的位置：

| 文件 | 关键字段 | 说明 |
|---|---|---|
| `config/benchforge.local.json` | `services.*`、`models.qwen`、`model_services.url` | 外部模型地址；`model_services` 默认复用 4960 网关 |
| `config/spatialforge.local.json` | `service_url`、`operator_token` | 客户端视角 |
| `config/spatialforge-server.local.json` | `port`、`database_url`、`artifacts`、`harness`、`model_url`、`models_config` | 服务端视角 |
| `config/database.env` | `POSTGRES_PORT` | PostgreSQL 宿主机端口 |
| `config/worker.local.json` | `url`、`worker_token` | Windows 采集 worker |
| `config/models.local.json` | 解释器与权重路径 | 本地模型 |

必须保持一致的项：

- `spatialforge-server.local.json` 的 `port` = `spatialforge.local.json` 的
  `service_url` 端口 = `worker.local.json` 的 `url` 端口。
- 客户端与服务器端的 `operator_token` 相同；服务器端与 worker 的
  `worker_token` 相同。
- `database.env` 的 `POSTGRES_PORT` = 服务端 `database_url` 中的端口。

### 3. 启动 PostgreSQL

```bash
.venv/bin/python spatialforge_app.py db
docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}' | grep benchforgev2
```

### 4. 启动 SpatialForge 服务

首次需安装服务端私有 venv：

```bash
python3.11 spatialforge_app.py setup
.spatialforge/venv/bin/python -m spatialforge.service --config config/spatialforge-server.local.json
```

该命令占用当前终端；验证另开一个终端：

```bash
.venv/bin/python spatialforge_app.py status
```

`status` 会同时检查数据库、服务端 `/catalog` 与令牌，成功即表示前两步均正常。

### 5. 生成预设并启动 DSH

配置改动后需要重新生成预设。重新生成前先备份旧文件，保留原内容便于对比：

```bash
cp -p config/benchforge.local.yml config/benchforge.local.yml.bak-$(date +%Y%m%d)
.venv/bin/python integrations/spatialforge/build_preset.py \
  --dsh-root /path/to/deepseek-harness \
  --node "$(command -v node)" \
  --python .venv/bin/python \
  --config config/benchforge.local.json \
  --service-config config/spatialforge.local.json \
  --output config/benchforge.local.yml
```

然后启动 Web（`benchforge.py start` 会自动加载上面生成的
`config/benchforge.local.yml`）：

```bash
.venv/bin/python benchforge.py start --port 3081 --no-open
```

终端会输出带 token 的访问地址，例如
`http://127.0.0.1:3081/?token=...`，浏览器打开后新建会话选择
**BenchForgeV2**，即可使用 `benchforge-tools` 与 `spatialforge-tools`。

### 6. 启动后检查

```bash
.venv/bin/python spatialforge_app.py status      # 数据库 + 服务 + 认证
.venv/bin/python benchforge.py demo              # 不依赖模型与 GPU 的离线链路
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3856/catalog -H "Authorization: Bearer <operator_token>"
```

模型能力还需外部服务：4960 网关（`model_services`）、29002 Qwen（`models.qwen`）、
8765/8766/8008（SAM3/YOLOE/DepthAnything，按需启动）。网关可用时
`sam3d` 应返回就绪；`lama`/`flux` 返回 502 表示其上游 worker 未启动，与本仓库配置无关。

### 7. 端口冲突处理

```bash
ss -ltnp | grep -E ':(3856|55546|3081)\b'
```

若端口被占用，按组件修改后重启：

- SpatialForge：改 `spatialforge-server.local.json` 的 `port`，同步修改
  `spatialforge.local.json` 的 `service_url` 与 `worker.local.json` 的 `url`。
- PostgreSQL：改 `database.env` 的 `POSTGRES_PORT`，同步修改服务端
  `database_url` 端口，然后重新执行 `spatialforge_app.py db`。
- DSH：启动时传 `--port`，例如 `benchforge.py start --port 3081`。

本机若已有现网服务，常见占用为：`3841`（另一套 SpatialForge）、`4960`（共享模型
网关，应当复用）、`29002`（Qwen）、`3080`（另一套 DSH）、`32768`（旧 harness 的
PostgreSQL）。这也是示例配置使用 `3856`/`55546`/`3081` 的原因。

### 8. 停止

- 前台运行的 SpatialForge 与 DSH 分别按 `Ctrl+C`。
- 停止数据库：

```bash
docker compose -p benchforgev2-spatialforge --env-file config/database.env \
  -f components/spatialforge/deploy/compose.yml down
```

### 9. 常见问题

- DSH 日志出现 `ENOSPC: file watchers`：只影响热更新，页面仍可正常使用；需要热更新时
  提高系统 inotify 上限。
- 插件加载报 `Cannot find module '@deepseek-ai/...'`：执行
  `npm ci --prefix integrations` 后重启 DSH。
- 页面提示未配置模型：在 DSH 设置中填 OpenAI 兼容地址
  `http://127.0.0.1:29002/v1` 与模型名 `Qwen/Qwen3.8-Flash-Next`。
- `config/benchforge.local.yml` 是生成物，不要手改；改配置后重新执行第 5 步。

## 验证与文档
=======
## Tests and documentation

```bash
python -m unittest discover -s tests -v
python integrations/spatialforge/smoke.py
```

The SpatialForge smoke test checks its HTTP request contract and delivery-review
logic without starting Isaac or calling a target-model API. A passing local test
does not establish current remote service health.

- [Pipeline catalog and evidence requirements](docs/pipelines.md)
- [Spatial learning, training and monitoring](docs/spatial-learning.md)
- [Model-service client boundary](docs/MODEL_SERVICES.md)
- [Self-hosted SpatialForge install](docs/SPATIALFORGE_INSTALL.md)
- [Validation scope and history](docs/VALIDATION.md)
