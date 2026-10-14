# 独立模型服务客户端与 SpatialForge 热更新

新模式的集成代码统一维护于 FIT 的 `/home/maqiang/GitHub/BenchForgeV2`，
公开仓库为 EurecaMoment/BenchForgeV2，开发分支为 SpatialForge。

## 模型服务边界

`src/benchforge_core/model_services` 是仅依赖 Python 标准库的客户端包。
八个模块均可独立导入或使用 `python -m` 调用，不导入 Torch、Diffusers、
Transformers、Pic2Sim，不下载权重，不探测或分配 GPU，不启动模型进程。

模型加载、权重路径、Python 环境和 GPU 调度由现有外部推理服务负责。
FIT 上的 API 地址目前为 `http://127.0.0.1:3951`，通过既有连接到 g3022。
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

本次新增的接口不复制八个旧 worker 或它们的启动器。现有部署的模型服务
继续使用其自己的实现；旧版可选模型执行代码的历史保留不等于新客户端
会导入它。场景后端、现有模型服务和桌面 Isaac 不由热更新脚本迁移或重启。

## 调用协议

- `submit`（默认）：POST /jobs；只提交一次，返回 job_id 和 inference_status。
- `status`、`result`：GET /jobs/{id}；保留 queued/running/completed/failed/canceled 真实状态。
- `wait`：有界查询同一任务，默认最多 300 秒；超时后任务继续，不重复提交。
- `cancel`：DELETE /jobs/{id}，只取消指定任务。
- `health`：GET /health，不加载模型；当前服务的 health 是路由健康状态，
  不代表八个模型都已驻留或每种产物质量均通过。

复制根目录的 `model-services.example.json` 到
`.deployment/model-services.json`，设置 `model_services.url`。
可在 `model_services.tools.<服务端tool>.request_defaults` 保存该工具的
模型路径等参数；这些是外部 API 请求默认值，不是客户端的模型启动配置。
私有配置、token 和机器路径不提交 GitHub。生产模型不得编辑这份操作员配置。

独立调用示例：

```bash
export PYTHONPATH=/home/maqiang/GitHub/BenchForgeV2/src
python -m benchforge_core.model_services.lama \
  --config /home/maqiang/GitHub/BenchForgeV2/.deployment/model-services.json \
  --action submit --input /shared/lama-request.json --work /shared/lama-job

python -m benchforge_core.model_services.lama \
  --config /home/maqiang/GitHub/BenchForgeV2/.deployment/model-services.json \
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
receipt = lama.call(config={"url": "http://127.0.0.1:3951"},
                    request=request, work="/shared/lama-job")
result = lama.call(config={"url": "http://127.0.0.1:3951"},
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
- `.deployment/model-services.json`：外部推理 API 及操作员请求默认值。
- `.deployment/spatialforge.local.json`：既有 SpatialForge 服务的客户端配置。

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
