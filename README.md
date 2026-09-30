# BenchForgeV2

空间能力图谱、27 项能力模板、程序真值数据、课程训练和实时监控见 [空间学习指南](docs/spatial-learning.md)。可用 `examples/spatial_learning_demo.py` 在 CPU 上验证小 Transformer 的实际训练、开发评分和断点续训。

BenchForge 的 DSH 应用、基准构建算法与 SpatialForge 场景生产工具集成。
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
`integrations/spatialforge/config.example.json` 为 `spatialforge.local.json`，
填写服务 URL，设置 `SPATIALFORGE_OPERATOR_TOKEN` 环境变量，然后执行：

```bash
python integrations/spatialforge/cli.py status --config spatialforge.local.json
python benchforge.py setup --spatialforge-config spatialforge.local.json
python benchforge.py start
```

选择 **BenchForgeV2**，即可在同一会话调用扩散参考、SAM3/SAM3D、资产导入、
SceneProgram、Isaac 采集、证据查看与复审工具。DSH 和 SpatialForge 应部署在
同一服务机，证据图片使用服务机文件路径；Windows 桌面 worker 负责唯一 Isaac 实例。

接入说明见 [SpatialForge](integrations/spatialforge/README.md)。
后端组件位于 [components](components/README.md)，运行配置均由用户本地生成。

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
