# 独立模型服务客户端与 SpatialForge 热更新

新模式的集成代码统一维护于 FIT 的 `/home/maqiang/GitHub/BenchForgeV2`，
公开仓库为 EurecaMoment/BenchForgeV2，开发分支为 SpatialForge。

本文件描述轻量客户端和外部服务边界，不是模型部署手册。权重、模型启动器、GPU
分配、远程隧道和生产服务均由部署方维护；客户端不会复制权重或启动重模型。

## 模型服务边界

`src/benchforge_core/model_services` 是仅依赖 Python 标准库的客户端包。
各模块均可独立导入或使用 `python -m` 调用，不导入 Torch、Diffusers、
Transformers、Pic2Sim，不下载权重，不探测或分配 GPU，不启动模型进程。

模型加载、权重路径、Python 环境和 GPU 调度由现有外部推理服务负责。
FIT 上的生产 API 为 `http://127.0.0.1:4960`：外部适配层把常驻模型请求转给 g3024，
其余工具和旧 job 保留原 g3022 的 3951/3952 路由。
客户端与服务使用已挂载的共享文件路径；这不是上传图像字节的接口。
任务代码应提供服务端可见的绝对输入和输出路径。

| 独立模块 | DSH 工具 | 服务端 tool |
| --- | --- | --- |
| yoloe | benchforge_model_yoloe | yoloe |
| sam3 | benchforge_model_sam3 | sam3 |
| moge | benchforge_model_moge | moge |
| lama | benchforge_model_lama | lama |
| flux_fill | benchforge_model_flux_fill | flux |
| osor_flux_fill | benchforge_model_osor_flux_fill | osor_flux |
| objectclear_fill | benchforge_model_objectclear_fill | objectclear |
| qwen_image_edit | benchforge_model_qwen_image_edit | qwen_image_edit |
| diffusion | benchforge_model_diffusion | diffusion |
| depth_anything | benchforge_model_depth_anything | depth_anything |
| sam3d | benchforge_model_sam3d | sam3d |
| blender | benchforge_model_blender | blender |

常驻模型位于 g3024 GPU4–7：FLUX.2 Klein、DA3METRIC-LARGE、SAM3、SAM3D。
输入规格为 1024×1024。DA3 请求必须提供输入图像像素坐标下的相机 `intrinsics`
或校准的 `focal_length_px`；输出为米制深度估计，不能当作 GT。
SAM3D 同一请求输出 Mesh 与 Gaussian；默认 `texture_baking=false`，Mesh 使用顶点颜色。
当前纹理烘焙依赖不可用，显式开启会在提交前返回原因。
原 `spatialforge_diffusion/sam3/depth/sam3d` 场景工具使用同一常驻路由。
远程场景请求不再读取本地模型路径配置，模型部署依然独立于本仓库。

Blender Cycles is a separate FIT provider exposed as `model_blender`. It runs the
official Blender 5.2.2 LTS binary with CUDA on the dedicated GPU 4. Submit an
absolute FIT-visible `blend_file` or `scene_file`, an absolute `output` path (or
let the provider write `render.png` under the job workspace), and optional
`width`, `height`, `samples`, and `frame`. The provider returns the rendered
image and timing metadata. It does not provide Isaac PhysX state, robot
interaction evidence, or benchmark GT.

Blender request example (the `.blend` file must already exist on FIT):

```json
{
  "workspace": "/home/maqiang/blender/dsh-workspace",
  "work": "/home/maqiang/blender/dsh-workspace/render-01",
  "request": {
    "blend_file": "/home/maqiang/blender/renders/smoke-scene.blend",
    "width": 1024,
    "height": 1024,
    "samples": 16,
    "frame": 1
  }
}
```

Call `benchforge_model_blender` with this input, then use `action="wait"` and
the returned `job_id`. The completed result contains `output` and `log` paths.
Each job writes into its own work directory. Availability first checks the
external service and the requested scene; a submitted job is not a rendered
image. These client definitions do not prove the external Blender deployment
or a real DSH render has passed acceptance.

适配层的 `/tools/{tool}/health` 查询常驻模型就绪状态；`/jobs` 在 FIT 保存任务与产物回执，
通过现有 SSH 连接访问 g3024 的 `/infer`。既有 job ID 仍可查询。
常驻 `/infer` 在派发后不支持中断，`cancel` 对此明确返回 409，不伪报取消。
四个既有常驻模型已通过真实 DSH 原生工具与 PTC 读回验收；
其 64 并发、每请求一秒的指标未达成。新增 Blender 需单独验收。

本次新增的接口不复制八个旧 worker 或它们的启动器。现有部署的模型服务
继续使用其自己的实现；旧版可选模型执行代码的历史保留不等于新客户端
会导入它。场景后端、现有模型服务和桌面 Isaac 不由热更新脚本迁移或重启。

## 调用协议

- `submit`（默认）：先向外部可用性接口 POST /tools/{tool}/health，带上合并默认值后的实际 request。
  只有同一 tool 明确返回 available=true 才 POST /jobs；失败会报出具体原因，不提交任务。
  提交只进行一次，返回 job_id 和 inference_status，并保存本次可用性回执。
- `status`、`result`：GET /jobs/{id}；保留 queued/running/completed/failed/canceled 真实状态。
- `wait`：有界查询同一任务，默认最多 300 秒；超时后任务继续，不重复提交。
- `cancel`：DELETE /jobs/{id}，只取消指定任务。
- `health`：调用同一个逐工具可用性接口，不加载模型。
  泛化的 GET /health 在线状态不能代替此检查。status/result/wait/cancel 可在模型不可用时继续查询或取消既有任务。

旧工具的外部检查服务由模型部署方运行在 g3022，FIT 经独立连接访问 3952。
它核对推理服务、实际 Python/worker 与依赖位置、请求对应的模型文件和允许 GPU 的当前剩余显存。
检查代码与部署目录位于已有模型部署树，独立于 BenchForgeV2：
`/home/maqiang/GitHub/SpatialForge/runtime/compute-g3022/model_availability.py`。
BenchForgeV2 不包含其部署/启动实现。检查成功表示当前可受理，
不表示权重已加载、推理已完成或所有依赖的二进制兼容性已验证。
扩散模型检查模型入口清单，不做完整权重扫描或冷加载；实际加载问题仍由任务状态返回。
显存检查不预留 GPU；最终分配及运行失败仍以推理服务返回的真实任务状态为准。
如果接口离线、工具缺失、权重路径错误或 GPU 不够，DSH 必须先解决该原因再继续依赖它的步骤。

模型服务配置是统一配置文件 `config/benchforge.local.json` 的 `model_services` 段
（从 `config/benchforge.example.json` 复制），设置 `model_services.url`。
需要独立文件时，也可用 `BENCHFORGE_MODEL_SERVICES_CONFIG` 指向任意含 `model_services` 的 JSON。
设置 `model_services.availability_url` 指向部署方的可用性接口；省略时使用同一个推理 API。
若服务没有逐工具可用性接口，客户端会拒绝提交，不降级为通用在线检查。
可在 `model_services.tools.<服务端tool>.request_defaults` 保存该工具的
模型路径等参数；这些是外部 API 请求默认值，不是客户端的模型启动配置。
私有配置、token 和机器路径不提交 GitHub。生产模型不得编辑这份操作员配置。

独立调用示例：

```bash
export PYTHONPATH=/home/maqiang/GitHub/BenchForgeV2/src
python -m benchforge_core.model_services.lama \
  --config /home/maqiang/GitHub/BenchForgeV2/config/benchforge.local.json \
  --action submit --input /shared/lama-request.json --work /shared/lama-job

python -m benchforge_core.model_services.lama \
  --config /home/maqiang/GitHub/BenchForgeV2/config/benchforge.local.json \
  --action result --job-id 返回的任务ID
```

LaMa 原生请求示例（使用部署方给出的实际路径）：

```json
{
  "model_path": "/external/models/lama/big-lama.pt",
  "image": "/shared/input.png",
  "mask": "/shared/mask.png",
  "output": "/shared/lama-job/output.png"
}
```

Python 调用：

```python
from benchforge_core.model_services import lama
config = {"url": "http://127.0.0.1:3951", "availability_url": "http://127.0.0.1:3952"}
receipt = lama.call(config=config,
                    request=request, work="/shared/lama-job")
result = lama.call(config=config,
                   action="result", job_id=receipt["job_id"])
```

DSH 可直接调用八个 `benchforge_model_*` 工具，也可在 PTC 的 `run_code`
中组合调用。每次提供 workspace；提交时提供原生 request，查询时提供 job_id。
模型输出作为预测/处理产物，不能自动作为评测 GT。

## 热更新脚本

脚本：`integrations/spatialforge/hot_update.py`。

```bash
cd /home/maqiang/GitHub/BenchForgeV2
.deployment/python-development integrations/spatialforge/hot_update.py --pull
```

`--pull` 只在当前 SpatialForge 分支做 git pull --ff-only；
省略它则热加载当前已部署的代码，不拉取。
脚本仅修改用户 web profile 中的 spatialforge-standard-ptc 预设，
使用统一仓库内的插件、Python wrapper、模型客户端配置与服务客户端配置。
官方 preset、BenchForge 旧模式、BenchForgev2 发布模式保持原有配置。

本次 FIT 部署的必需文件：

- `.deployment/python-development`：复用已有 Python 环境，业务导入路径指向仓库 src。
- `config/benchforge.local.json`：外部推理 API 及操作员请求默认值（`model_services` 段）。
- `config/spatialforge.local.json`：既有 SpatialForge 服务的客户端配置。

脚本通过 DSH 官方 profile 热加载更新定义，并使用带 revision 的插件 URL
重新导入 SpatialForge 本地辅助模块。不会修改
`/home/maqiang/GitHub/deepseek-harness` 的源码，不执行 systemctl restart，
不启动 GPU、模型或仿真器。40 秒内未确认新预设则还原 profile。

原会话保留已绑定版本；新建 SpatialForge 会话使用新代码和新工具。
热更新不能把运行中的 Agent 偷换成新版本，也不能热替换场景后端进程。

回执位于 `.deployment/spatialforge-hot-update.json`，
上次 profile 备份位于 `.deployment/spatialforge-before-hot-update.yml`。
认证使用当前 DSH 启动日志的 URL，也可从 DSH_ADMIN_URL 环境变量提供；
脚本不会输出认证 token。
