# 统一模型配置

操作员只维护 **`config/benchforge.local.json`**。首次 `spatialforge_app.py init`
从 [完整模板](../config/benchforge.example.json) 创建；DSH、规划/审查、标注和生成工具
都读取这份文件或其自动投影。Isaac Sim 继续使用独立的 gRPC 协议，入口也在该文件的
`isaac.grpc` 段声明，不恢复本地 Kit 启动参数。

| 字段 | 内容与读取者 |
| --- | --- |
| `models.<名称>` | 大模型的 `url/model/token_env`，或本地视觉模型的 `python/path` |
| `model_roles.dsh` | 引用 `models` 中的名称，生成 DSH 提供方和新会话默认模型 |
| `model_roles.scene` | 场景规划、视觉审查与服务端标注所用模型 |
| `model_roles.annotation` | 第一代 BenchForge 标注链及 `llm_local` 的模型 |
| `services.sam3/yoloe/depthanything3/trellis2` | 原生 HTTP 模型接口，保留各自请求协议 |
| `model_services` | HTTP 异步模型网关、可用性接口、认证引用和超时 |
| `model_services.tools.<工具>.request_defaults` | 外部模型客户端的请求默认值 |
| `generation.mode` | `remote` 调网关；`local` 使用已安装的本地模型 |
| `sources` | 本地模型源码路径，仅本地执行需要 |
| `isaac.grpc` | Isaac 的 `host/port/timeout_seconds`，同步到 worker |

模型按需配置；示例地址和路径不意味着服务已经运行。模板已列出 Qwen、FLUX、SAM3、
深度模型、三维生成及现有各外部工具。DA3 标注接口与可选 Depth Anything V2 本地模型
具有不同的输出语义，不能把相对深度当成米制真值。

## 共用同一个大模型

在已有文件中修改以下条目，保留其他配置段。不要复制整个对象后产生重复 JSON 字段。

```json
{
  "models": {
    "qwen": {
      "url": "http://127.0.0.1:9001/v1",
      "model": "YOUR_DEPLOYED_QWEN_VL_MODEL",
      "token_env": "QWEN_RELAY_API_KEY",
      "context_window": 65536,
      "max_tokens": 4096,
      "input": ["text", "image"],
      "timeout_seconds": 180,
      "retries": 1
    }
  },
  "model_roles": {
    "dsh": "qwen",
    "scene": "qwen",
    "annotation": "qwen"
  }
}
```

将模型 ID、地址和模型容量改成部署方给出的真实值；使用视觉审查时，模型必须支持图片。
角色可以引用不同模型，无需重复相同模型的地址。DSH 的协议默认是
`openai-completions`，可按实际提供方在模型条目中设置 `api`、`compat`、
`reasoning_efforts` 和 `reasoning_effort`。DSH 容量字段来自
`context_window/max_tokens/input`；具体生产阶段的输出预算仍由该阶段的任务合同决定。

密钥值放在本地 `config/dsh.env`，例如：

```dotenv
QWEN_RELAY_API_KEY=替换为实际密钥
BENCHFORGE_INFERENCE_API_KEY=替换为实际推理服务密钥
```

JSON 只保存 `token_env` 的变量名。此文件和本地 JSON 已被 Git 忽略。
模型参数应在统一 JSON 中修改，旧的地址环境变量不覆盖已声明的统一模型。
DSH 网页仍可为某个会话选择模型，该操作不会重写已有会话的身份或工作区。

## 图像、深度和三维模型

`model_services` 沿用已有的异步 HTTP 接口，统一存放 `url`、可选
`availability_url`、`token_env`、`http_timeout_seconds`、`health_timeout_seconds`，
以及 `tools` 下各工具的请求默认值。独立客户端在仓库根目录默认读取同一份 JSON；
其他目录使用 `--config /绝对路径/config/benchforge.local.json`。

统一配置不改变已有服务的请求协议。三维服务的实际模型由部署端实现决定，
声明 TRELLIS2 地址不等于它已经接入现有 `sam3d` 作业协议。
不要仅凭配置文件或在线状态宣称完成真实模型验收。

如果选择 `generation.mode=local`，在同一文件中填写已有 `models.flux/sam3/sam3d/depth_anything`
的 `python/path` 及 `sources`。相对路径以统一 JSON 所在目录为基准；
使用远程服务不需要在 BenchForge 客户端安装这些模型或复制权重。

## 修改和迁移

```bash
# 首次创建；已有配置不会被模板覆盖。
.venv/bin/python spatialforge_app.py init

# 更新模型引用和 Isaac worker 参数；端口文件缺失也可同步模型。
.venv/bin/python spatialforge_app.py sync

# 重新启动本实例；保留自己的 Web 端口设置。
./restart.sh
```

`init/sync` 把旧模型文件中的解释器、权重、源码路径及服务端的
`model_url/model_id/model_api_key_env` 补入统一文件。已有统一字段优先；
相对路径迁移时保留原指向，旧文件不删除。服务端配置随后只保存 `models_config` 引用，
不再保留第二套模型地址。旧本地执行配置迁移后继续使用本地模式。

DSH 的生成 YAML 是运行快照，不是另一份手工配置。通过 `benchforge.py start`
或 `start.sh` 启动时自动从统一 JSON 刷新提供方和默认模型，保留三个预设、其他提供方、
UI 配置和历史会话。占位模型不会覆盖 DSH 原来的默认选择。
