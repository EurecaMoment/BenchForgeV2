# 下载后快速使用

准备 Python 3.10+、Git、Node.js 22.19+ 或 24+：

```bash
git clone https://github.com/EurecaMoment/BenchForgeV2.git
cd BenchForgeV2
python benchforge.py setup
python benchforge.py start
```

安装器将固定版本 DSH 作为第三方依赖下载并构建一次，再安装 BenchForge 的生产依赖、
生成独立模式。界面中配置你的 Qwen 提供方，在新会话选择 **BenchForge**。
已有编译好的 DSH 可用 `python benchforge.py setup --dsh-root 路径` 复用。
项目使用自己的 DSH home，不修改 SpatialForge 或官方预设。升级插件后重启本项目的
DSH 进程，以刷新缓存的工具定义。

## 先确认下载包可用

`python benchforge.py demo` 无网络、无模型地运行两道核心链路题。
更完整的视觉生产示例：

```bash
python -m pip install -e ".[production,research]"
python examples/production_demo.py --workspace runs/production
```

它会实际绘制四张图片，完成能力设计、模板编译、程序出题、筛选、评分对照与可复现
打包。结果写在 `runs/production/result.json`。这是安装与代码链路示例，不是仿真
实测，也不证明正式 benchmark 的质量。

## 接上已部署 Qwen 和数据

复制 `config.example.json` 为 `config.local.json`，填写 `models.qwen` 的 URL、模型名
以及保存 API key 的环境变量名。DSH 对话模型和 benchmark 答题模型分开配置，可以
使用同一个已部署 Qwen。只配置任务需要的标注服务或仿真 Python 环境。

在 BenchForge 模式输入：

> 用这个 Habitat 原生采集目录做 24 道左右、上下、远近空间题。调用已有编译器，
> GT 来自原始仿真状态和确定性程序。先看样例图，再用配置的 qwen 回答公开题包，
> 输出评分、基线、诊断和能换机器复现的完整包。

`benchforge_catalog` 提供请求示例，`benchforge_method` 提供原 BenchClaw 专业方法。
原来的调研、采集、清洗标注、编译、试生产、批量生成、评测能力可按任务需要组合，
没有强制五阶段顺序。任务修复可复用现有产物。

Parquet 数据再安装 `.[datasets]`。SAM3、YOLOE、DA3、Data-Juicer、Habitat、LIBERO、
CARLA、Isaac 环境与模型/数据资产按需准备，见 [后端配置](BACKENDS.md)。首次下载模型
和构建 DSH 需要时间，不能把这些成本算作“几秒启动”。

模型输出只进入候选标注和复核队列，不自动变成 GT。公开包不含答案或原始深度，
完整复现包包含私有原始输入和代码。缺答计零，重复/未知 ID 拒绝；诊断明确标出
小样本和代理基线的限制。

实际完成的验证、失败修复和未验收范围见 [VALIDATION](VALIDATION.md)；55 个原 skill
的映射见 [SKILL_PARITY](SKILL_PARITY.md)。
