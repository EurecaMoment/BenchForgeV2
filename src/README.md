# src 目录组织

源码先按业务能力划分，再按业务内部的职责分层。目录是代码实际归属，不是旧目录的别名。

| 模块 | 范围 |
| --- | --- |
| `scene_production` | 场景编写、资产处理、队列、Isaac 仿真、采集验收、场景库 |
| `benchmark_workflows` | 评测设计、数据来源、出题与数据集、流水线、评分与报告 |
| `spatial_learning` | 能力图、训练数据、课程、训练实验、评估与训练监控 |
| `service_access` | 配置、外部服务客户端、请求上下文、工作区作业记录 |
| `dsh` | 单一预设、Host 公共能力、Client 装配与构建 |

三个业务模块使用相同层级规则：

- `contracts/`：公开数据、工具和 Remote 契约；不导入服务端实现。
- `server/`：业务实现，按业务步骤继续分组。
- `dsh/`：业务的 DSH 工具注册和 Host 适配。
- `client/`：浏览器视图与交互，不导入 `server/` 或持有服务端凭据。
- `resources/`：业务的静态目录、模板和素材。
- `api.py`：Python 跨业务调用公开入口。
- `deploy/`：只有场景模块需要的部署文件，不创建空目录凑层级。

DSH 只注册一个 `benchforge` 预设。Client 通过原生右侧栏展开、收起工作台，
两个显示状态共用同一会话、工具集和生产状态。评测 Host 通过场景查询适配器装配
场景视图。跨业务 Python 调用只使用 `api.py` 或 `contracts/`。
各业务 DSH 源码由统一构建打包发布，无需堆回集成目录。

下方展示全部有效源码层级。同类 JSON 配方及图片超过五个时只显示前五个。
模型推理部署不在这些目录中；HTTP/OpenAI 提供方和 Isaac 连接由统一配置指定。
Isaac 本地常驻、进程接管和 mock gRPC 保留。空缓存目录不属于源码。

```text
src/
├── benchmark_workflows/
│   ├── client/
│   │   ├── components/
│   │   │   ├── products.js
│   │   │   ├── progress.js
│   │   │   └── workbench.js
│   │   ├── DESIGN.md
│   │   ├── api.js
│   │   ├── i18n.js
│   │   ├── primitives.js
│   │   ├── state.js
│   │   └── styles.js
│   ├── contracts/
│   │   ├── remote/
│   │   │   ├── src/
│   │   │   │   ├── index.ts
│   │   │   │   └── types.ts
│   │   │   ├── package.json
│   │   │   └── tsconfig.host.json
│   │   ├── __init__.py
│   │   ├── quantity.py
│   │   └── tools.mjs
│   ├── dsh/
│   │   ├── delivery/
│   │   │   └── delivery_files.mjs
│   │   ├── projections/
│   │   │   ├── preparation_products.mjs
│   │   │   ├── public_artifacts.mjs
│   │   │   └── routes.mjs
│   │   ├── sessions/
│   │   │   ├── execution_control.mjs
│   │   │   └── synthesis.mjs
│   │   ├── host.mjs
│   │   ├── preparation.mjs
│   │   ├── resources.mjs
│   │   └── tools.mjs
│   ├── resources/
│   │   ├── pipelines/
│   │   │   ├── asset.prepare.json
│   │   │   ├── data.capability.json
│   │   │   ├── data.package.json
│   │   │   ├── scene.capture.json
│   │   │   ├── scene.create.json
│   │   │   └── … 另有 2 个同类资源文件
│   │   ├── assessment_template.json
│   │   ├── capabilities.json
│   │   └── task_templates.json
│   ├── server/
│   │   ├── assessment_planning/
│   │   │   ├── __init__.py
│   │   │   ├── assessment.py
│   │   │   ├── catalog.py
│   │   │   ├── plan_edit.py
│   │   │   ├── plan_edit_cli.py
│   │   │   ├── plan_input.py
│   │   │   ├── plan_request_cli.py
│   │   │   ├── plan_versions.py
│   │   │   ├── planner.py
│   │   │   ├── research.py
│   │   │   └── stage_review_cli.py
│   │   ├── dataset_authoring/
│   │   │   ├── scene_capture/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── product_diagnostics.py
│   │   │   │   ├── product_packaging.py
│   │   │   │   ├── products.py
│   │   │   │   └── spatial_tasks.py
│   │   │   ├── __init__.py
│   │   │   ├── adapters.py
│   │   │   ├── answer_contracts.py
│   │   │   ├── production.py
│   │   │   └── question_writing.py
│   │   ├── pipelines/
│   │   │   ├── __init__.py
│   │   │   ├── artifact_graph.py
│   │   │   ├── bindings.py
│   │   │   ├── execution_lock.py
│   │   │   ├── operation_runtime.py
│   │   │   └── … 另有 5 个同类资源文件
│   │   ├── progress/
│   │   │   ├── __init__.py
│   │   │   └── production_observer.py
│   │   ├── scoring/
│   │   │   ├── __init__.py
│   │   │   ├── protocol_scores.py
│   │   │   └── reports.py
│   │   ├── source_acquisition/
│   │   │   ├── collectors/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── carla.py
│   │   │   │   ├── habitat.py
│   │   │   │   ├── isaac.py
│   │   │   │   └── libero.py
│   │   │   ├── measurements/
│   │   │   │   ├── README.md
│   │   │   │   ├── __init__.py
│   │   │   │   ├── geometry.py
│   │   │   │   ├── public_geometry_cache.py
│   │   │   │   ├── public_measurements.py
│   │   │   │   └── public_sensor_cache.py
│   │   │   ├── __init__.py
│   │   │   ├── capture_adapter.py
│   │   │   ├── preparation.py
│   │   │   └── run_collector.py
│   │   ├── storage/
│   │   │   ├── __init__.py
│   │   │   └── artifacts.py
│   │   ├── __init__.py
│   │   ├── cli.py
│   │   └── operations.py
│   ├── __init__.py
│   └── api.py
├── dsh/
│   ├── client/
│   │   ├── client.js
│   │   ├── entry.js
│   │   ├── index.js
│   │   └── package.json
│   ├── host/
│   │   ├── python_tools.mjs
│   │   ├── session_family.mjs
│   │   ├── session_operations.mjs
│   │   ├── session_scope.mjs
│   │   └── subagent_handoff.mjs
│   ├── presets/
│   │   ├── build_preset.py
│   │   ├── build_presets.py
│   │   ├── hot_update.py
│   │   ├── install_preset.py
│   │   ├── preset_definition.py
│   │   ├── profile_migration.py
│   │   └── subagent_policy.mjs
│   ├── README.md
│   ├── build.mjs
│   ├── check_config.py
│   ├── cli.py
│   ├── cordis.patch.yml
│   ├── package-lock.json
│   ├── package.json
│   └── stage_package.mjs
├── scene_production/
│   ├── client/
│   │   └── components/
│   │       └── gallery.js
│   ├── contracts/
│   │   ├── __init__.py
│   │   ├── scene_design.py
│   │   ├── scene_program.py
│   │   ├── tool_names.mjs
│   │   └── tools.mjs
│   ├── deploy/
│   │   ├── dispatcher/
│   │   │   ├── DISPATCHER_OVERLAY.md
│   │   │   ├── deploy_dispatcher_overlay.py
│   │   │   ├── dispatcher_overlay.example.json
│   │   │   ├── dispatcher_overlay.py
│   │   │   ├── dsh_a800_worker-late-cancel.patch
│   │   │   └── worker_cancellation.py
│   │   ├── compose.yml
│   │   └── requirements-preview.txt
│   ├── desktop/
│   │   └── __init__.py
│   ├── dsh/
│   │   ├── capture/
│   │   │   ├── capture_associations.mjs
│   │   │   ├── capture_runtime.mjs
│   │   │   ├── capture_watch.mjs
│   │   │   ├── quality_review.mjs
│   │   │   └── review_images.mjs
│   │   ├── queries.mjs
│   │   ├── request_identity.mjs
│   │   ├── service_client.mjs
│   │   └── tools.mjs
│   ├── resources/
│   │   ├── material_previews/
│   │   │   ├── bamboo_desktop.jpg
│   │   │   ├── fabric_grid.jpg
│   │   │   ├── grass.jpg
│   │   │   ├── office_wall.jpg
│   │   │   ├── rubber_woven.jpg
│   │   │   └── … 另有 4 个同类资源文件
│   │   ├── native_asset_facing.json
│   │   ├── native_assets.json
│   │   └── native_materials.json
│   ├── server/
│   │   ├── asset_generation/
│   │   │   ├── __init__.py
│   │   │   ├── asset_review.py
│   │   │   ├── gaussian_asset.py
│   │   │   ├── generation.py
│   │   │   ├── generation_stage.py
│   │   │   ├── layout.py
│   │   │   ├── mesh_appearance.py
│   │   │   └── mesh_export.py
│   │   ├── capture_evidence/
│   │   │   ├── __init__.py
│   │   │   ├── capture_recovery.py
│   │   │   ├── capture_scope.py
│   │   │   ├── capture_transfer.py
│   │   │   ├── observation.py
│   │   │   ├── operator_evidence.py
│   │   │   └── review.py
│   │   ├── isaac_sim/
│   │   │   ├── appearance/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── gaussian_visual.py
│   │   │   │   ├── imported_appearance.py
│   │   │   │   ├── material_controls.py
│   │   │   │   └── native_appearance.py
│   │   │   ├── capture/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── camera_controls.py
│   │   │   │   ├── capture_images.py
│   │   │   │   ├── interaction_recording.py
│   │   │   │   └── isaac_capture.py
│   │   │   ├── capture_requests/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── camera_trajectory.py
│   │   │   │   ├── robot_contact.py
│   │   │   │   └── trajectory.py
│   │   │   ├── grpc/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── client.py
│   │   │   │   ├── isaac_sim.proto
│   │   │   │   ├── isaac_sim_pb2.py
│   │   │   │   ├── isaac_sim_pb2_grpc.py
│   │   │   │   └── mock_server.py
│   │   │   ├── processes/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── dispatcher_control.py
│   │   │   │   ├── isaac_resident.py
│   │   │   │   └── worker.py
│   │   │   ├── rendering/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── light_geometry.py
│   │   │   │   ├── object_shadows.py
│   │   │   │   └── render_quality.py
│   │   │   ├── scene/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── primitive_geometry.py
│   │   │   │   ├── robot_contact.py
│   │   │   │   ├── scene_export.py
│   │   │   │   └── scene_runtime.py
│   │   │   └── __init__.py
│   │   ├── production_queue/
│   │   │   ├── __init__.py
│   │   │   ├── engine.py
│   │   │   ├── scene_requests.py
│   │   │   ├── scene_scheduler.py
│   │   │   └── task_workspace.py
│   │   ├── scene_library/
│   │   │   ├── __init__.py
│   │   │   ├── observations.py
│   │   │   ├── repair_context.py
│   │   │   ├── repair_library.py
│   │   │   ├── scene_library.py
│   │   │   ├── scene_preview_video.py
│   │   │   └── source_policy.py
│   │   ├── scene_program/
│   │   │   ├── cameras/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── layout.py
│   │   │   │   └── source.py
│   │   │   ├── catalog/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── capabilities.py
│   │   │   │   ├── environments.py
│   │   │   │   ├── native.py
│   │   │   │   └── operators.py
│   │   │   ├── geometry/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── mesh.py
│   │   │   │   ├── native_asset_facing.py
│   │   │   │   ├── parts.py
│   │   │   │   ├── preview.py
│   │   │   │   ├── relations.py
│   │   │   │   └── support_graph.py
│   │   │   ├── validation/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── acceptance.py
│   │   │   │   ├── policy.py
│   │   │   │   ├── preflight.py
│   │   │   │   ├── program.py
│   │   │   │   ├── quality.py
│   │   │   │   └── review_reference.py
│   │   │   ├── __init__.py
│   │   │   ├── planning.py
│   │   │   └── program_submission.py
│   │   ├── storage/
│   │   │   ├── __init__.py
│   │   │   ├── metadata.py
│   │   │   ├── storage.py
│   │   │   └── workbench_queries.py
│   │   ├── __init__.py
│   │   ├── cli.py
│   │   └── http_api.py
│   ├── LICENSE
│   ├── README.md
│   ├── __init__.py
│   └── api.py
├── service_access/
│   ├── __init__.py
│   ├── artifacts.py
│   ├── configuration.py
│   ├── http_tools.py
│   ├── openai_client.py
│   ├── progress.py
│   ├── request_context.py
│   ├── runtime_config.py
│   ├── scene_service.py
│   └── workspace_jobs.py
├── spatial_learning/
│   ├── client/
│   │   ├── index.html
│   │   ├── monitor.js
│   │   └── styles.css
│   ├── contracts/
│   │   └── tools.mjs
│   ├── dsh/
│   │   └── tools.mjs
│   ├── resources/
│   │   ├── capability_graph.json
│   │   └── task_templates.json
│   ├── server/
│   │   ├── capability_catalog/
│   │   │   ├── __init__.py
│   │   │   ├── build_registry.py
│   │   │   └── registry.py
│   │   ├── datasets/
│   │   │   ├── task_generators/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── geometry.py
│   │   │   │   ├── graph.py
│   │   │   │   ├── motion.py
│   │   │   │   └── reasoning.py
│   │   │   ├── __init__.py
│   │   │   ├── conditions.py
│   │   │   ├── environments.py
│   │   │   ├── export.py
│   │   │   ├── generation.py
│   │   │   └── scenes.py
│   │   ├── evaluation/
│   │   │   ├── __init__.py
│   │   │   ├── evaluation.py
│   │   │   └── scoring.py
│   │   ├── training/
│   │   │   ├── __init__.py
│   │   │   ├── curriculum.py
│   │   │   ├── experiments.py
│   │   │   ├── monitor.py
│   │   │   └── training.py
│   │   ├── __init__.py
│   │   └── cli.py
│   ├── __init__.py
│   └── api.py
└── README.md
```

构建生成的 `dsh/dist/` 与 Remote `lib/` 不纳入版本控制；`dsh/client/client.js` 是随仓库交付的浏览器构建产物。
