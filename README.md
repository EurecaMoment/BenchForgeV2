# BenchForgeV2

空间能力图谱、27 项能力模板、程序真值数据、课程训练和实时监控见 [空间学习指南](docs/spatial-learning.md)。可用 `examples/spatial_learning_demo.py` 在 CPU 上验证小 Transformer 的实际训练、开发评分和断点续训。

BenchForge 的 DSH 应用、基准构建算法与 SpatialForge 场景生产工具集成。
八个独立模型 API 客户端及 SpatialForge 运行时热更新见 [服务调用与热更新](docs/MODEL_SERVICES.md)。
本仓库包含可安装的 Python 核心、DSH 启动器、预设生成器、离线示例及
SpatialForge 服务端、PostgreSQL 数据引擎、生成 worker、Windows Isaac 执行器、
工具注册和交付复审实现。

## 启动应用

安装 Python 3.10+、Git 和 Node.js 22.19+ 或 24+：

```bash
git clone https://github.com/EurecaMoment/BenchForgeV2.git
cd BenchForgeV2
python benchforge.py setup
python benchforge.py start
```

setup 下载固定版本的 DSH，安装依赖、构建前端与运行时；需要网络。
启动后在 DSH 页面配置自己的模型供应商，新建会话选择 **BenchForge**。
已构建的 DSH 可通过 `setup --dsh-root /path/to/deepseek-harness` 复用。
配置位于本仓库，官方 DSH 预设与其他安装不会被改写。
Debian/Ubuntu 需安装与所选 Python 对应的 `python3-venv` 包。

## 无模型运行示例

```bash
python benchforge.py demo
python -m pip install -e ".[production,research]"
python examples/production_demo.py --workspace runs/production
```

Windows 请使用较短的工作目录（例如 `C:\\bfv2`）；深层目录可能触发系统路径长度限制。

第一个命令不需要安装、网络、API 密钥或 GPU，生成公开题包、独立答案包和
真实程序评分。第二个示例画出四张测试图，并实际执行设计、编译、生成、筛选、
评分控制及打包。这些是程序示例，不是 Isaac 场景或照片还原验收。

## 从零启动 SpatialForge

Linux 服务机安装 Python 3.11、Docker Compose、bubblewrap，执行：

```bash
python3.11 spatialforge_app.py setup
python3.11 spatialforge_app.py init
python3.11 spatialforge_app.py db
python3.11 spatialforge_app.py serve
```

Windows 桌面安装 Isaac Sim，从同一仓库运行 worker。完成连接后，
`examples/push_box_scene.json` 可直接渲染、执行真实外力推动并导出场景。
完整的桌面配置、扩散模型、DSH 启动与产物位置见
[逐步安装说明](docs/SPATIALFORGE_INSTALL.md) 和 [模型安装](docs/SPATIALFORGE_MODELS.md)。

## 接入已有 SpatialForge

已有 SpatialForge 后端和桌面 worker 时，复制
`config/spatialforge.example.json` 为 `config/spatialforge.local.json`，
填写服务 URL 与 `operator_token`，然后执行：

```bash
python integrations/spatialforge/cli.py status --config config/spatialforge.local.json
python benchforge.py setup --spatialforge-config config/spatialforge.local.json
python benchforge.py start
```

选择 **BenchForgeV2**，即可在同一会话调用扩散参考、SAM3/SAM3D、资产导入、
SceneProgram、Isaac 采集、证据查看与复审工具。DSH 和 SpatialForge 应部署在
同一服务机，证据图片使用服务机文件路径；Windows 桌面 worker 负责唯一 Isaac 实例。

接入说明见 [SpatialForge](integrations/spatialforge/README.md)。
后端组件位于 [components](components/README.md)，运行配置均由用户本地生成。

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

```bash
python -m unittest discover -s tests -v
python integrations/spatialforge/smoke.py
```

SpatialForge smoke 执行真实 HTTP 客户端及交付复审代码的回归，覆盖实际 POST
路由、认证、失败交互、不可见演示、图片反馈和损坏引用；不依靠手写的成功布尔值。
不调用目标模型 API，也不启动 Isaac。

- [本次发布修复](docs/PUBLICATION_REPAIR.md)
- [生产工具](docs/PRODUCTION.md) · [后端配置](docs/BACKENDS.md)
- [BenchForge 上游历史验收](docs/VALIDATION.md)（不代表 V2 的新 GPU 验收）
- [原始能力映射](docs/SKILL_PARITY.md)

GT 来自官方标注、程序或仿真；模型预测不会成为 GT。公开问题与权威答案分开。
模型权重、Isaac 软件/资产和密钥需要按其授权与安装要求另行提供。
