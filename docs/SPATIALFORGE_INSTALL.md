# 从仓库部署 SpatialForge

服务、持久任务队列、生成工具、DSH 插件与桌面执行器均在本仓库。
服务机运行 Linux/Python 3.11、Docker Compose 和 Node.js 22.19+；Windows 桌面运行
Isaac Sim。DSH 与服务放在同一 Linux 用户下，便于直接查看产物。
桌面只运行一个 worker/Isaac 实例。生成模型按任务临时加载，不停止机器上的其他服务。

## 1. 安装服务和独立数据库

```bash
git clone https://github.com/EurecaMoment/BenchForgeV2.git
cd BenchForgeV2
sudo apt-get install bubblewrap
python3.11 spatialforge_app.py setup
python3.11 spatialforge_app.py init
python3.11 spatialforge_app.py db
python3.11 spatialforge_app.py serve
```

Python 需要 venv/ensurepip。Debian/Ubuntu 可安装与所用 Python 版本匹配的 `python3.11-venv`。
`setup` 在 `.spatialforge/venv` 安装本仓库的两个组件；没有依赖未公开的 BenchClaw/Pic2Sim 工程。
`init` 生成随机凭据及配置，重复运行保留已有文件。PostgreSQL 只绑定本机 55432，
API 只绑定本机 3841；端口冲突时首次初始化使用 `--port 3856 --db-port 55546`。
数据库使用独立 Compose 项目和卷。不要让第二个服务连接已有生产数据库。

配置在 `.spatialforge/server.local.json`。可改为现有 **专用 PostgreSQL** 的
`database_url`；SQLite 不支持本服务的任务和设备锁。`gpu_candidates` 是获准使用的
GPU 索引，以逗号分隔，默认只用 0。不要把共享服务占用的 GPU 加入候选列表。

另一个终端运行 `python3.11 spatialforge_app.py status`，应返回实际目录数据。
任务代码运行于 bubblewrap：只写任务目录，不能写 Harness/配置/GT，也不能直接联网。
若主机禁用了非特权 user namespace，需要管理员为 bubblewrap 启用所需能力；保留此隔离。

## 2. 连接唯一 Windows 桌面

安装 NVIDIA 官方 Isaac Sim（本版本真实执行器使用 6.0.1）和 Isaac 资产包。
原生资源目录采用 Isaac 4.5 资产包布局，根目录下应有 `Props`、`Environments`、`Robots`。
软件安装参考 [Isaac Sim 文档](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/index.html)。
模型与软件/资产按各自条款获取，不随本仓库打包。

在 Windows 克隆同一个仓库到短路径，例如 `D:\BenchForgeV2`，安装普通 Python 3.11。
把服务机生成的 `.spatialforge/worker.local.json` 安全复制到 Windows 仓库根目录，填写：

```json
{
  "url": "http://127.0.0.1:3841",
  "worker_token": "复制服务机生成的 worker_token",
  "worker_id": "desktop-isaac-main",
  "isaac_root": "D:/isaac-sim",
  "isaac_asset_root": "D:/isaac-assets/Assets/Isaac/4.5/Isaac",
  "runs": "D:/BenchForgeV2-runs",
  "ssh_host": "user@server",
  "ssh_forward": "3841:127.0.0.1:3841"
}
```

`isaac_root` 是包含 `python.bat` 的软件目录。先在 Windows 执行 `ssh user@server`，
完成主机指纹确认和密钥登录；worker 使用非交互 SSH。可以填 SSH config 中的主机别名，
也可指定 `ssh_config` 文件。配置的 SSH 本地端口和服务端口须一致。
若已有外部隧道，在配置中删除 `ssh_host`、`ssh_forward`。

```powershell
cd D:\BenchForgeV2
python spatialforge_app.py worker --config worker.local.json
```

worker 保留 Windows 单实例互斥锁，按任务用 Isaac 自带 Python 启动执行器。
无需在 Isaac 环境中安装服务端的 PostgreSQL、DSH 或生成模型依赖。
请勿同时运行旧 SpatialForge worker 与本仓库 worker。

## 3. 执行实际渲染和物理交互

在 Linux 仓库执行：

```bash
python3.11 spatialforge_app.py capture \
  --program examples/push_box_scene.json \
  --request-key first-install-push-box --wait 900
```

该示例创建桌台、固定红色标记及可推动蓝盒，渲染三个视角，施加真实外力并导出 USD。
不需要模型权重或语言模型。记录返回的 `run_id`；网络中断后使用相同的请求键和文件
重连原任务。修改场景时使用新请求键，旧产物保留。退出码 2 表示等待窗口结束、任务仍在运行。

产物在 `.spatialforge/artifacts/<task_id>/revision_0/capture/`：
`view_*.png/json`、交互前后图和轨迹、`evidence.json`、`report.json`、成对 USD 场景文件。
以实际交互 `success`、轨迹和前后画面判断推动效果；`SUCCEEDED` 只表示采集任务完成。
打开 USD 时保持整个 capture 目录一起移动。这个例子的几何全部程序生成；
使用原生资产的其他场景，其导出依赖以 `scene_export` 清单为准。

需要连续交互演示时，在对应 `apply_force` 或 `robot_push` 中增加
`"recording": {"every_steps": 2}`。每隔指定物理步渲染当前真实状态，输出
`interaction_0.mp4`、`interaction_0_recording.json` 和原始 PNG 的
`interaction_0_frames.zip`；按动作序号递增。时间线包含物理步、仿真时间和目标位置，
解压 PNG 包后可与其逐帧对照。视频 FPS 为 `1/(every_steps*dt)`，例如 60 Hz
物理步隔 2 步录制为 30 FPS。`recording:{}` 自动选择约 30 FPS；省略则只采交互端点。
渲染会增加实际耗时，不推进额外物理步，也不插值或拼接端点制造运动。动作最后时刻若不在
采样网格内，仍由独立 after 图记录。视频编码使用 Isaac Python 的 OpenCV；若该安装缺少
它，执行 `python.bat -m pip install opencv-python-headless`。MP4、PNG 包与时间线随正常
worker 上传，可用 evidence 读取路径或复制至任务工作区。

## 4. 配置扩散、分割、生成资产和深度

按 [模型安装](SPATIALFORGE_MODELS.md) 安装需要的模型，编辑
`.spatialforge/models.local.json` 中的解释器、权重、源码路径。
每种工具只需要自己的配置；采集及已有网格导入无需先安装 SAM3D 或全部模型。
`models.flux` 是 FLUX.2 Klein 图像生成模型；这里不调用旧 Pic2Sim 的图像剥离流水线。

需要服务端自动规划和视觉修正时，在 `server.local.json` 增加自己的 OpenAI 兼容视觉模型设置：

```json
{
  "model_url": "http://127.0.0.1:8000/v1",
  "model_id": "your-vision-model-id",
  "model_api_key_env": "SPATIALFORGE_MODEL_API_KEY"
}
```

这些字段应合并到已有配置，保留数据库、目录和两个 token；在启动服务的终端设置
`SPATIALFORGE_MODEL_API_KEY`。该模型用于生产与修复，不作为目标评测模型，也不生成 GT。
仅 `/capture` 和 SceneProgram 路径不需要该模型。

## 5. 启动完整 DSH 界面

在服务机的新终端运行：

```bash
python3.11 spatialforge_app.py dsh-setup
python3.11 spatialforge_app.py dsh-start
```

已有构建的 DSH 可用 `dsh-setup --dsh-root /path/to/deepseek-harness`。
包装入口自动把本服务的 operator token 传给 DSH，无需复制进插件源码。
在网页配置生产模型，创建 **BenchForgeV2** 会话。例如：

> 请先生成一张全新的写实书房参考图，再创建尽量还原布局、材质和自然光的三维场景。
> 加入一个可真实推动的桌面物件，提供多视角渲染、交互演示和可加载的场景文件。

工具可组合调用扩散参考、原生/已有资产复用、SAM3/SAM3D 生成、任务代码、采集、
证据和修复。生成资产不是每个任务的必选步骤。收尾复审会把原始请求、像素和实际
交付依赖接回模型；可修复缺口应继续工作，不能用 TODO 全勾选或 README 的“局限”替代。

## 6. 验证与排障

- 服务启动失败：查看启动终端，确认数据库容器健康和端口、凭据一致。
- 任务停在 `capture`：查看桌面的 `<runs>/worker.log`、该 attempt 的 `isaac.log`。
  在模型使用的 `/observe` 中可读取阶段和具体失败；不要重复提交相同任务。
- 模型工具失败：查看该任务 `generation_stage/worker/worker.log`，修复实际缺失依赖。
  已有本地模型权重可直接配置路径，不必再下载。
- 重新生成配置不会迁移已有数据；保留 `.spatialforge` 和桌面 runs 目录。

新隔离数据库、没有桌面 worker 的环境可运行服务回归：

```bash
.spatialforge/venv/bin/python components/spatialforge/tests/service_roundtrip.py \
  --config .spatialforge/server.local.json --output runs/service-roundtrip
```

它实际测试 HTTP 认证、PostgreSQL、沙箱写文件、重复请求、重启续接和取消，
最终留下已取消任务；它不是 Isaac 或视觉质量验收。
