# Optional backend setup

The core and visual production example run without GPUs. Configure only the
backends needed by your benchmark; keep SDKs in separate environments. Copy
`config.example.json` to `config.local.json`. Secrets belong in environment
variables named by `token_env`, not in committed JSON.

| Component | Upstream | Configuration |
|---|---|---|
| DSH | https://github.com/deepseek-ai/deepseek-harness | launcher pins a tested revision; existing built checkout can be reused |
| Qwen/VLM | OpenAI-compatible deployed endpoint | `models.qwen` for evaluation; `services.llm_local` for category proposals |
| SAM3 | https://github.com/facebookresearch/sam3 | service wrapper uses `SAM3_REPO`, `SAM3_CHECKPOINT` |
| YOLOE | https://github.com/THU-MIG/yoloe | `YOLOE_REPO`, `YOLOE_CHECKPOINT`, `YOLOE_MOBILECLIP`, `YOLOE_DEVICE` |
| Depth Anything 3 | https://github.com/ByteDance-Seed/Depth-Anything-3 | upstream `da3 backend --model-dir /path/to/model`; service URL |
| Data-Juicer | https://github.com/modelscope/data-juicer | isolated installation and `cleaning.command: ["/env/bin/dj-process"]` |
| Habitat | https://github.com/facebookresearch/habitat-sim | SDK Python, scene assets and dataset config supplied through collector arguments |
| LIBERO | https://github.com/Lifelong-Robot-Learning/LIBERO | SDK Python, configured BDDL/init states; demos optional |
| CARLA | https://github.com/carla-simulator/carla | matching server/SDK versions, host/port; current map unless explicitly selected |
| Isaac Sim | https://docs.isaacsim.omniverse.nvidia.com/ | Isaac Python launcher; independent cuboid/camera scene program |

Follow each upstream's installation and model/dataset terms. BenchForge bundles
its adapters and the original BenchClaw algorithms, not GPU frameworks, weights or
licensed datasets. Installed PyTorch must match the machine's NVIDIA driver.

Configure collector commands as argv lists, for example:

```json
{"collectors":{"habitat":{"command":["/envs/habitat/bin/python"]}}}
```

Supply normal collector arguments in `{"argv":["--help"]}` to inspect the
installed adapter. LIBERO uses `--action-source zeros` or `demo`. A zero-action
capture proves observation/state integration, not successful manipulation.
CARLA capture changes the simulation while collecting; use a dedicated server.
Its `--restart-per-map --server-script ...` option explicitly owns the servers it
starts. No existing server is silently restarted.

Annotation service wrappers are installed under
`benchforge_core/vendor/benchclaw/annotation-tool/`. Locate them without copying a
machine path: `python -c "from benchforge_core.artifacts import VENDOR; print(VENDOR)"`.
SAM3/YOLOE wrapper CLIs accept `--port`. DA3 uses its upstream CLI. A backend can be
registered for explicit startup:

```json
{"backends":{"depthanything3":{
  "command":["/envs/da3/bin/da3","backend","--model-dir","/models/DA3","--host","127.0.0.1","--port","8008"],
  "health_url":"http://127.0.0.1:8008/status",
  "env":{"CUDA_VISIBLE_DEVICES":"0"}
}}}
```

Call `backend` with `{"name":"depthanything3","action":"start"}` and then
`action=status` after initialization. The command runs independently with its
own log and returned PID. Status only establishes service availability; acceptance
requires masks/raw arrays from actual inference. Startup never substitutes for
model execution. For offline use, download weights beforehand and give a local
model directory. A user-selected `HF_ENDPOINT` mirror may be supplied in `env`.

`annotate` composes VLM → YOLOE → SAM3 → DA3, retains per-image intermediate
outputs, candidate annotations and review failures. Service-visible image paths
must exist on the backend host. Predictions remain predictions, even when all
four services complete. Native simulation labels bypass this prediction chain.

After upgrading the plugin, start a new project-local DSH process so cached preset
definitions are refreshed. Existing user DSH sessions need not be restarted.
