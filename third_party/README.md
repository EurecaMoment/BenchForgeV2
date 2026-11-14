# 第三方依赖

以下八个仓库以 **Git 子模块** 引入，保留各自的源码、许可证和版本历史。
BenchForge 的提交固定每个子模块的具体版本；仓库地址在根目录
[`.gitmodules`](../.gitmodules) 中维护，用途在
[`dependencies.json`](dependencies.json) 中登记。

| 目录 | 源仓库 | 用途 |
| --- | --- | --- |
| `FastTrellis2/` | [EurecaMoment/FastTrellis2](https://github.com/EurecaMoment/FastTrellis2) | TRELLIS.2 三维网格与 PBR 生成 |
| `DSpark4A100/` | [EurecaMoment/DSpark4A100](https://github.com/EurecaMoment/DSpark4A100) | 大模型推理与服务 |
| `IssacSim4A100/` | [EurecaMoment/IssacSim4A100](https://github.com/EurecaMoment/IssacSim4A100) | A100 上的 Isaac Sim 部署与仿真支持 |
| `FastSAM3/` | [EurecaMoment/FastSAM3](https://github.com/EurecaMoment/FastSAM3) | SAM 3 分割与推理服务 |
| `FastFLUX2Klein/` | [EurecaMoment/FastFLUX2Klein](https://github.com/EurecaMoment/FastFLUX2Klein) | FLUX.2 Klein 图像生成与编辑 |
| `FastDA3/` | [EurecaMoment/FastDA3](https://github.com/EurecaMoment/FastDA3) | Depth Anything 3 米制深度、相机位姿和长视频几何推理 |
| `FastQwen/` | [EurecaMoment/FastQwen](https://github.com/EurecaMoment/FastQwen) | Qwen 模型推理与部署源码 |
| `deepseek-harness4BenchForge/` | [EurecaMoment/deepseek-harness4BenchForge](https://github.com/EurecaMoment/deepseek-harness4BenchForge) | DSH Agent 和 Web 运行时 |

`dependencies.json` 的 `provider_submodules` 对应 BenchForge 配置中的提供方。
FastQwen 作为独立部署源码登记在 `optional_submodules`。

## 下载

首次下载主仓库和全部子模块，包括它们的嵌套依赖：

```bash
git clone --branch simulator-access-integration --recurse-submodules --shallow-submodules https://github.com/EurecaMoment/BenchForgeV2.git benchforge
cd benchforge
```

已有 BenchForge 代码，在拉取主仓库更新后执行：

```bash
git submodule sync --recursive
git submodule update --init --recursive --depth 1
```

仅需要某一个库时，可以单独下载，例如：

```bash
git submodule update --init --recursive --depth 1 -- third_party/FastSAM3
```

普通 `git clone` 不会下载子模块内容；GitHub 的 ZIP 下载也不包含子模块源码。
目录为空时运行上面的 `git submodule update`，无需手工复制其他部署的目录。

## 安装与版本更新

下载源码后，按照各子模块自身的 README 配置运行环境、权重和服务。
子模块是独立的可选依赖，按实际需要的服务初始化与部署。
服务调用是否可用还取决于对应适配器、地址配置和服务部署，不能由源码引入推定。
各库及其依赖、权重和资产的许可，以其自身文件为准。

升级某一个库时，在该子模块内检出需要的提交，再从主仓库提交该目录的版本指针。
普通 `git submodule update --init --recursive` 恢复主仓库记录的版本，不会自动追踪上游最新版本。

`benchforge_app.py dsh-setup` 会初始化并构建 DSH 子模块。当前版本为 `0.2.2-rc.3`，
来源和构建要求见 [`config/benchforge.example.json`](../config/benchforge.example.json) 的 `dsh`。
升级 fork 时同时更新子模块指针与配置版本，并重新运行 `dsh-setup`。
