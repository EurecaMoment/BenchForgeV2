# BenchClaw 图像/视频题型模板与指标外挂参考库

## 1. 使用边界

本参考库只服务于 `template-metric-code-generation` skill 在 BenchClaw 图像/视频数据上的模板选择、指标编译、答案程序生成和契约检查。它不是替代 `BENCHCLAW_ROOT/templates/` 统一模板包的主来源，而是对统一模板包的 **适配过滤层**：只有当统一模板包中的模板能映射到本参考库保留的题型、答案类型、GT 来源和自动评分指标时，才应被编译为 enabled runtime template。

BenchClaw 原始数据边界：

```text
image/video observation
+ simulator or semi-supervised GT
+ deterministic answer
+ automatic evaluator
+ auditable provenance
```

允许来源包括：

- 仿真器图像：RGB、depth、semantic/instance segmentation、camera pose、object pose、visibility、occlusion、interaction/affordance state。
- 仿真器连续视频：frame-level object state、tracking id、visibility log、camera trajectory、action log、distance/occlusion/interaction state。
- 真实图像：semi-supervised bbox、mask、depth、relative-depth、object category、visibility、count、relation labels。
- 真实连续视频：tracking、segmentation、depth/SLAM/pose、semi-supervised object trajectory、event labels。

每个 enabled item 必须能追溯到 `provenance.gt_source` 与 `provenance.gt_evidence`，且 `answer` 能由 evidence record 或可复现计算得到。

---

## 2. 保留 Answer Types

```python
BENCHCLAW_ANSWER_TYPES = {
    "choice",           # 多选题
    "bool",             # True/False
    "number",           # 距离、面积、角度、计数、顺序编号
    "point2d",          # 2D 点，例如点击目标中心/可放置点
    "bbox2d",           # 2D 框
    "mask",             # 2D mask 或 mask path
    "ordered_list",     # 物体出现顺序、距离排序、面积排序
    "action_sequence",  # 视频路径/转向序列
    "relation_tuple"    # 结构化关系三元组，例如 [object_a, relation, object_b]
}
```

这些 answer type 是本 skill 在 BenchClaw 图像/视频适配模式下的主库集合。运行时 enabled 模板的 `answer_format` / `answer.type` 必须映射到上述集合之一。

---

## 3. 保留 Evaluator Registry

```python
BENCHCLAW_EVALUATOR_REGISTRY = {
    ("choice", "accuracy"): eval_choice_accuracy,
    ("choice", "chance_adjusted_accuracy"): eval_caa,
    ("choice", "circular_eval"): eval_circular_eval,
    ("choice", "flip_eval"): eval_flip_eval,

    ("bool", "accuracy"): eval_bool_accuracy,

    ("number", "exact_numeric_accuracy"): eval_exact_numeric_accuracy,
    ("number", "mae"): eval_mae,
    ("number", "rmse"): eval_rmse,
    ("number", "abs_rel_error"): eval_abs_rel,
    ("number", "delta_success"): eval_delta_success,
    ("number", "mra"): eval_mra,

    ("point2d", "point_in_mask"): eval_point_in_mask,
    ("point2d", "normalized_l2_error"): eval_normalized_l2_error,

    ("bbox2d", "iou_2d"): eval_iou_2d,
    ("bbox2d", "acc_iou_2d"): eval_acc_iou_2d,

    ("mask", "mask_iou"): eval_mask_iou,
    ("mask", "point_in_mask"): eval_point_in_mask,

    ("ordered_list", "order_exact_accuracy"): eval_order_exact_accuracy,
    ("ordered_list", "kendall_tau"): eval_kendall_tau,

    ("action_sequence", "sequence_exact_match"): eval_action_sequence_em,
    ("action_sequence", "step_accuracy"): eval_step_accuracy,

    ("relation_tuple", "relation_accuracy"): eval_relation_tuple_accuracy
}
```

主指标必须来自上述 registry 或显式声明为同义兼容映射；否则该模板不能 enabled。

---

## 4. 最终保留的 10 类模板

| 模板 ID | 名称 | 输入 | GT 来源 | Answer Type | 主指标 |
|---|---|---|---|---|---|
| T1 | 单图空间关系判断 | image | simulator state / bbox / mask / depth | choice / bool | Accuracy / CAA |
| T2 | 多图 / 多视角空间推理 | multi-image | camera pose / object correspondence / simulator state | choice / ordered_list | Accuracy / Grouped Accuracy |
| T3 | 视频时空关系推理 | video | tracking / simulator logs / frame-level labels | choice / ordered_list / action_sequence | Accuracy / Order Acc / Step Acc |
| T4 | 2D 指代定位 | image / video frame | mask / bbox / simulator projection | point2d / bbox2d / mask | Point-in-mask / IoU |
| T5 | 目标计数与可见性 | image / video | instance mask / tracking / simulator visibility | number / choice | Exact / MAE / Accuracy |
| T6 | 定量空间度量估计 | image / video | simulator metric state / calibrated depth / 3D reconstruction | number | MRA / δ / MAE / AbsRel |
| T7 | 深度/距离/大小排序 | image / video | depth / 3D state / bbox area / mask area | choice / ordered_list | Accuracy / Kendall Tau |
| T8 | 视角变换与自我中心推理 | image / video | camera pose / object pose / simulated ego state | choice / action_sequence | Accuracy / Step Acc |
| T9 | 交互/可供性空间题 | image / video | simulator affordance / contact / reachability / containment | choice / bool | Accuracy |
| T10 | 对称增强与鲁棒性题 | image / video + transformed pair | deterministic transform / simulator counterfactual | choice / bool | FlipEval / CircularEval |

---

## 5. 统一样本 Schema 参考

```json
{
  "id": "bc_sample_id",
  "media": {
    "type": "image | multi_image | video | image_pair | video_clip",
    "paths": [],
    "frame_range": null,
    "camera": {
      "pose": null,
      "intrinsics": null,
      "extrinsics": null
    }
  },
  "task": {
    "family": "single_image_spatial_relation | multi_view_spatial_reasoning | video_spatiotemporal_reasoning | 2d_referring_grounding | object_counting_visibility | quantitative_metric_estimation | depth_distance_size_ordering | egocentric_perspective_reasoning | spatial_affordance_reasoning | robustness_pair",
    "subtype": "specific_task_type",
    "relation": null,
    "objects": [],
    "difficulty": {
      "num_objects": null,
      "num_steps": null,
      "num_frames": null,
      "occlusion_level": null,
      "viewpoint_shift": null
    }
  },
  "prompt": {
    "question": "question text",
    "options": [],
    "instruction": "answer format instruction"
  },
  "answer": {
    "type": "choice | bool | number | point2d | bbox2d | mask | ordered_list | action_sequence | relation_tuple",
    "value": null,
    "unit": null,
    "mask_path": null,
    "bbox": null,
    "valid_aliases": []
  },
  "eval": {
    "primary_metric": "accuracy | chance_adjusted_accuracy | mae | delta_success | point_in_mask | acc_iou_2d | order_exact_accuracy | sequence_exact_match | flip_eval | circular_eval",
    "secondary_metrics": [],
    "thresholds": {},
    "group_by": ["task.subtype", "task.relation", "task.difficulty"]
  },
  "provenance": {
    "gt_source": "simulator_state | simulator_depth | simulator_segmentation | simulator_action_log | simulator_camera_pose | semi_supervised_bbox | semi_supervised_mask | semi_supervised_depth | calibrated_measurement | tracking_annotation",
    "gt_evidence": {},
    "generation_rule": "rule_id_or_template_id",
    "scene_id": null,
    "frame_ids": []
  }
}
```

---

## 6. 模板 T1：单图空间关系判断

### 6.1 适用 GT

```text
2D bbox
instance mask
depth map
simulator object 3D position
camera pose
object visibility
object category
```

### 6.2 可生成问题类型

```text
A 是否在 B 左边？
A 是否在 B 前方？
A 是否比 B 更靠近相机？
A 是否遮挡了 B？
哪个物体离相机最近？
哪个物体在桌子上？
哪个物体位于沙发和柜子之间？
```

### 6.3 标准模板

```json
{
  "id": "bc_img_rel_000001",
  "benchmark": "BenchClaw",
  "split": "test",
  "media": {
    "type": "image",
    "paths": ["images/scene_0001.png"]
  },
  "task": {
    "family": "single_image_spatial_relation",
    "subtype": "left_right",
    "relation": "left_of",
    "objects": ["mug", "plate"]
  },
  "prompt": {
    "question": "Is the mug to the left of the plate?",
    "options": [
      {"id": "A", "text": "Yes"},
      {"id": "B", "text": "No"}
    ],
    "instruction": "Answer with A or B."
  },
  "answer": {
    "type": "choice",
    "value": "A"
  },
  "eval": {
    "primary_metric": "accuracy",
    "secondary_metrics": ["chance_adjusted_accuracy"]
  },
  "provenance": {
    "gt_source": "simulator_state",
    "gt_evidence": {
      "mug_center_px": [320, 220],
      "plate_center_px": [470, 225],
      "rule": "x_mug < x_plate"
    }
  }
}
```

### 6.4 GT 规则

```python
def relation_left_of(obj_a, obj_b):
    return obj_a["center_px"][0] < obj_b["center_px"][0]

def relation_right_of(obj_a, obj_b):
    return obj_a["center_px"][0] > obj_b["center_px"][0]

def relation_above(obj_a, obj_b):
    return obj_a["center_px"][1] < obj_b["center_px"][1]

def relation_below(obj_a, obj_b):
    return obj_a["center_px"][1] > obj_b["center_px"][1]

def relation_closer_depth(obj_a, obj_b):
    return obj_a["depth_mean"] < obj_b["depth_mean"]

def relation_farther_depth(obj_a, obj_b):
    return obj_a["depth_mean"] > obj_b["depth_mean"]

def relation_larger_area(obj_a, obj_b):
    return obj_a["mask_area"] > obj_b["mask_area"]
```

---

## 7. 模板 T2：多图 / 多视角空间推理

### 7.1 适用 GT

```text
multi-view simulator capture
same scene from several camera poses
real multi-view photos with estimated pose/correspondence
video frames sampled as pseudo-multi-view
```

### 7.2 可生成问题类型

```text
同一物体在不同视角中的位置变化
从相机 2 的视角看，A 在 B 哪一侧？
哪张图最接近目标视角？
哪个视角能看到被遮挡物体？
跨视角匹配同一对象
```

### 7.3 标准模板

```json
{
  "id": "bc_multiview_000001",
  "benchmark": "BenchClaw",
  "split": "test",
  "media": {
    "type": "multi_image",
    "paths": [
      "scene_0001/view_0.png",
      "scene_0001/view_1.png",
      "scene_0001/view_2.png"
    ],
    "camera": {
      "pose": [
        {"view_id": "view_0", "position": [0, 0, 1.5], "yaw": 0},
        {"view_id": "view_1", "position": [2, 0, 1.5], "yaw": 90},
        {"view_id": "view_2", "position": [0, 2, 1.5], "yaw": 180}
      ]
    }
  },
  "task": {
    "family": "multi_view_spatial_reasoning",
    "subtype": "viewpoint_transform",
    "requires": ["object_correspondence", "camera_pose_reasoning"]
  },
  "prompt": {
    "question": "From the viewpoint of image 2, where is the chair relative to the table?",
    "options": [
      {"id": "A", "text": "left"},
      {"id": "B", "text": "right"},
      {"id": "C", "text": "in front"},
      {"id": "D", "text": "behind"}
    ]
  },
  "answer": {
    "type": "choice",
    "value": "B"
  },
  "eval": {
    "primary_metric": "accuracy",
    "group_by": ["viewpoint_transform", "num_views"]
  },
  "provenance": {
    "gt_source": "simulator_camera_pose_and_object_state"
  }
}
```

### 7.4 GT 规则

```python
import numpy as np

def world_to_camera_xy(point_world, camera_pose):
    p = np.array(point_world[:2]) - np.array(camera_pose["position"][:2])
    yaw = camera_pose["yaw"]
    rot = np.array([
        [np.cos(-yaw), -np.sin(-yaw)],
        [np.sin(-yaw),  np.cos(-yaw)]
    ])
    return rot @ p

def relative_direction_in_view(obj_a_world, obj_b_world, camera_pose):
    a = world_to_camera_xy(obj_a_world, camera_pose)
    b = world_to_camera_xy(obj_b_world, camera_pose)
    delta = a - b

    if abs(delta[0]) > abs(delta[1]):
        return "right" if delta[0] > 0 else "left"
    return "in_front" if delta[1] > 0 else "behind"
```

---

## 8. 模板 T3：视频时空关系推理

### 8.1 适用 GT

```text
simulator continuous capture
real video + tracking
real video + segmentation + depth + manual/semi-supervised correction
```

### 8.2 可生成问题类型

```text
哪个物体最先出现？
A 是否在 B 之前被看到？
A 从左向右移动还是从右向左移动？
目标物体最后出现在哪个区域？
机器人到达目标前需要转几次？
视频中哪个物体被遮挡后再次出现？
```

### 8.3 Appearance Order 模板

```json
{
  "id": "bc_video_order_000001",
  "benchmark": "BenchClaw",
  "split": "test",
  "media": {
    "type": "video",
    "paths": ["videos/scene_0001.mp4"],
    "frame_sampling": {"num_frames": 16, "strategy": "uniform"}
  },
  "task": {"family": "video_spatiotemporal_reasoning", "subtype": "first_appearance_order"},
  "prompt": {
    "question": "What is the first-time appearance order of the following objects: sofa, table, sink, bed?",
    "instruction": "Return the objects in order."
  },
  "answer": {"type": "ordered_list", "value": ["bed", "sofa", "table", "sink"]},
  "eval": {"primary_metric": "order_exact_accuracy", "secondary_metrics": ["kendall_tau"]},
  "provenance": {
    "gt_source": "simulator_visibility_log",
    "gt_evidence": {"first_visible_frame": {"bed": 3, "sofa": 7, "table": 11, "sink": 15}}
  }
}
```

### 8.4 Route / Turn 模板

```json
{
  "id": "bc_video_route_000001",
  "benchmark": "BenchClaw",
  "split": "test",
  "media": {"type": "video", "paths": ["videos/route_0001.mp4"]},
  "task": {
    "family": "video_spatiotemporal_reasoning",
    "subtype": "route_planning",
    "requires": ["egocentric_direction", "landmark_transition"]
  },
  "prompt": {
    "question": "The camera starts near the sofa facing the TV and needs to reach the sink. Which turn sequence is correct?",
    "options": [
      {"id": "A", "text": "turn left, then turn right"},
      {"id": "B", "text": "turn right, then turn left"},
      {"id": "C", "text": "go straight, then turn back"},
      {"id": "D", "text": "turn back, then turn right"}
    ]
  },
  "answer": {"type": "choice", "value": "B"},
  "eval": {"primary_metric": "accuracy"},
  "provenance": {"gt_source": "simulator_action_log_or_camera_trajectory"}
}
```

### 8.5 Ordered List 算法

```python
def parse_ordered_list(text, candidates):
    norm = normalize_text(text)
    found = []
    for c in candidates:
        pos = norm.find(normalize_text(c))
        if pos >= 0:
            found.append((pos, c))
    found.sort()
    return [c for _, c in found]

def eval_order_exact_accuracy(samples, predictions):
    correct = 0
    for s, pred in zip(samples, predictions):
        gt = s["answer"]["value"]
        pred_order = parse_ordered_list(pred, gt)
        correct += int(pred_order == gt)
    return {"order_exact_accuracy": correct / len(samples)}
```

---

## 9. 模板 T4：2D 指代定位 / 区域定位

### 9.1 适用 GT

```text
simulator instance segmentation
SAM/Mask2Former 等半监督 mask
GroundingDINO/YOLO bbox + 人工校正
simulator 3D object projected to 2D bbox
```

### 9.2 可生成问题类型

```text
请指出离门最近的椅子
请框出桌子上的杯子
请点击最靠近相机的物体
请指出被沙发部分遮挡的物体
请指出可以放置杯子的区域
```

### 9.3 Point-in-Mask 模板

```json
{
  "id": "bc_point_000001",
  "benchmark": "BenchClaw",
  "split": "test",
  "media": {"type": "image", "paths": ["images/scene_0001.png"]},
  "task": {"family": "2d_referring_grounding", "subtype": "point_to_object", "relation": "nearest_to"},
  "prompt": {"question": "Point to the chair closest to the table.", "instruction": "Return one point as (x, y)."},
  "answer": {"type": "point2d", "mask_path": "masks/chair_target.png"},
  "eval": {"primary_metric": "point_in_mask"},
  "provenance": {"gt_source": "simulator_instance_mask"}
}
```

### 9.4 Bbox 模板

```json
{
  "id": "bc_bbox_000001",
  "benchmark": "BenchClaw",
  "split": "test",
  "media": {"type": "image", "paths": ["images/scene_0001.png"]},
  "task": {"family": "2d_referring_grounding", "subtype": "bbox_grounding"},
  "prompt": {"question": "Draw a bounding box around the mug on the left side of the plate.", "instruction": "Return [x1, y1, x2, y2]."},
  "answer": {"type": "bbox2d", "value": [120, 200, 180, 260]},
  "eval": {"primary_metric": "acc_iou_2d", "iou_threshold": 0.5},
  "provenance": {"gt_source": "semi_supervised_bbox"}
}
```

### 9.5 2D IoU 算法

```python
def iou_2d(box_a, box_b):
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0

def eval_acc_iou_2d(samples, predictions, threshold=0.5):
    correct = 0
    ious = []
    for s, pred in zip(samples, predictions):
        gt_box = s["answer"]["value"]
        pred_box = pred["bbox2d"]
        iou = iou_2d(pred_box, gt_box)
        ious.append(iou)
        correct += int(iou >= threshold)
    return {f"acc@{threshold}iou_2d": correct / len(samples), "mean_iou_2d": sum(ious) / len(ious)}
```

---

## 10. 模板 T5：目标计数与可见性

### 10.1 适用 GT

```text
instance segmentation
simulator object list
visibility ratio
tracking ID
occlusion state
```

### 10.2 可生成问题类型

```text
图中有几个可见杯子？
视频中一共出现过几个椅子？
当前帧中有几个物体被部分遮挡？
哪些物体在整段视频中从未完全可见？
```

### 10.3 模板

```json
{
  "id": "bc_count_000001",
  "benchmark": "BenchClaw",
  "split": "test",
  "media": {"type": "image", "paths": ["images/scene_0001.png"]},
  "task": {"family": "object_counting_visibility", "subtype": "visible_object_count", "target_category": "chair"},
  "prompt": {"question": "How many chairs are visible in the image?", "instruction": "Answer with a single integer."},
  "answer": {"type": "number", "value": 3},
  "eval": {"primary_metric": "exact_numeric_accuracy", "secondary_metrics": ["mae"]},
  "provenance": {
    "gt_source": "simulator_visibility_state",
    "gt_evidence": {"visible_chair_ids": ["chair_1", "chair_3", "chair_5"], "visibility_threshold": 0.1}
  }
}
```

### 10.4 Count GT 规则

```python
def count_visible_objects(objects, category, visibility_threshold=0.1):
    return sum(
        1 for obj in objects
        if obj["category"] == category and obj["visibility_ratio"] >= visibility_threshold
    )
```

---

## 11. 模板 T6：定量空间度量估计

### 11.1 适用 GT

```text
simulator metric coordinates
camera pose + object pose
depth map
calibrated real-world reconstruction
semi-supervised scale calibration
```

### 11.2 可生成问题类型

```text
A 和 B 之间的距离是多少？
哪个物体离相机最近？
桌子的高度大约是多少？
A 到 B 的水平距离是多少？
目标区域面积是多少？
视频中相机移动了多少米？
```

### 11.3 模板

```json
{
  "id": "bc_metric_000001",
  "benchmark": "BenchClaw",
  "split": "test",
  "media": {"type": "image", "paths": ["images/scene_0001.png"], "depth_path": "depth/scene_0001.exr"},
  "task": {"family": "quantitative_metric_estimation", "subtype": "object_distance", "quantity": "direct_distance", "unit": "meter"},
  "prompt": {"question": "What is the direct distance between the microwave and the sink in meters?", "instruction": "Answer with a number in meters."},
  "answer": {"type": "number", "value": 1.82, "unit": "meter"},
  "eval": {"primary_metric": "delta_success", "delta": 1.25, "secondary_metrics": ["mae", "abs_rel_error", "mra"]},
  "provenance": {
    "gt_source": "simulator_object_coordinates",
    "gt_evidence": {"microwave_xyz": [1.2, 0.4, 1.1], "sink_xyz": [2.9, 1.0, 0.9], "distance_m": 1.82}
  }
}
```

### 11.4 数值题生成条件

```text
绝对距离题：需要 calibrated metric GT
相对距离题：只需要 depth/order/relative annotation
面积大小题：可用 mask area 或 bbox area
角度题：需要 camera pose 或 object pose
轨迹长度题：需要连续相机位姿或里程计
```

---

## 12. 模板 T7：深度 / 距离 / 面积 / 大小排序

### 12.1 适用 GT

```text
depth map
simulator z-buffer
object 3D position
mask area
bbox area
```

### 12.2 可生成问题类型

```text
以下物体按离相机从近到远排序
哪个物体面积最大？
哪个物体最高？
哪个物体更靠近桌子？
A、B、C 中谁最远？
```

### 12.3 模板

```json
{
  "id": "bc_order_000001",
  "benchmark": "BenchClaw",
  "split": "test",
  "media": {"type": "image", "paths": ["images/scene_0001.png"]},
  "task": {"family": "depth_distance_size_ordering", "subtype": "depth_ordering", "quantity": "camera_distance"},
  "prompt": {"question": "Order the following objects from nearest to farthest from the camera: chair, table, sink.", "instruction": "Return an ordered list."},
  "answer": {"type": "ordered_list", "value": ["chair", "table", "sink"]},
  "eval": {"primary_metric": "order_exact_accuracy", "secondary_metrics": ["kendall_tau"]},
  "provenance": {"gt_source": "simulator_depth", "gt_evidence": {"chair_distance": 1.1, "table_distance": 2.3, "sink_distance": 3.4}}
}
```

### 12.4 Kendall Tau

```python
def kendall_tau_score(order_pred, order_gt):
    index_pred = {x: i for i, x in enumerate(order_pred)}
    index_gt = {x: i for i, x in enumerate(order_gt)}
    common = [x for x in order_gt if x in index_pred]
    if len(common) < 2:
        return 0.0
    inversions = 0
    total = 0
    for i in range(len(common)):
        for j in range(i + 1, len(common)):
            a, b = common[i], common[j]
            total += 1
            if (index_pred[a] - index_pred[b]) * (index_gt[a] - index_gt[b]) < 0:
                inversions += 1
    return 1 - 2 * inversions / total
```

---

## 13. 模板 T8：视角变换与自我中心推理

### 13.1 适用 GT

```text
camera pose
ego trajectory
object pose
simulator coordinate system
multi-view video frames
```

### 13.2 可生成问题类型

```text
如果相机面向冰箱，水槽在左边还是右边？
从人物视角看，桌子在椅子的哪一侧？
机器人需要向左转还是向右转才能面向目标？
目标物体位于前左、前右、后左还是后右？
```

### 13.3 模板

```json
{
  "id": "bc_ego_000001",
  "benchmark": "BenchClaw",
  "split": "test",
  "media": {
    "type": "image",
    "paths": ["images/ego_0001.png"],
    "camera": {"viewpoint": "ego", "pose": {"position": [0.0, 0.0, 1.5], "yaw": 1.57}}
  },
  "task": {"family": "egocentric_perspective_reasoning", "subtype": "front_left_right_back", "reference_frame": "camera"},
  "prompt": {
    "question": "From the camera's current viewpoint, where is the sink relative to the microwave?",
    "options": [
      {"id": "A", "text": "front-left"},
      {"id": "B", "text": "front-right"},
      {"id": "C", "text": "back-left"},
      {"id": "D", "text": "back-right"}
    ]
  },
  "answer": {"type": "choice", "value": "B"},
  "eval": {"primary_metric": "accuracy"},
  "provenance": {"gt_source": "camera_pose_and_object_state"}
}
```

---

## 14. 模板 T9：交互 / 可供性空间题

### 14.1 适用 GT

```text
reachable
graspable
openable
supportable
containable
on_top_of
inside
collision-free placement
visibility from pose
```

### 14.2 可生成问题类型

```text
哪个物体可以被当前机器人抓取？
杯子可以放在哪个区域？
打开柜门后能看到什么？
哪个容器可以容纳苹果？
从当前位置能否到达桌子？
哪个物体支撑着盘子？
```

### 14.3 模板

```json
{
  "id": "bc_afford_000001",
  "benchmark": "BenchClaw",
  "split": "test",
  "media": {"type": "image", "paths": ["images/scene_0001.png"]},
  "task": {"family": "spatial_affordance_reasoning", "subtype": "supportable_region", "affordance": "supportable"},
  "prompt": {
    "question": "Which surface can support the mug?",
    "options": [
      {"id": "A", "text": "table"},
      {"id": "B", "text": "wall"},
      {"id": "C", "text": "door"},
      {"id": "D", "text": "air"}
    ]
  },
  "answer": {"type": "choice", "value": "A"},
  "eval": {"primary_metric": "accuracy"},
  "provenance": {
    "gt_source": "simulator_physics_and_affordance_state",
    "gt_evidence": {"supportable_candidates": ["table", "countertop"], "collision_free": true}
  }
}
```

---

## 15. 模板 T10：对称增强与鲁棒性题

### 15.1 适用 GT

```text
horizontal flip
camera perturbation
object swap
viewpoint shift
counterfactual simulator scene
option permutation
```

### 15.2 可生成问题类型

```text
翻转前后 left/right 答案是否一致变换
同一题选项顺序改变后模型是否仍答对
相机轻微移动后答案是否稳定
替换无关物体后答案是否不变
```

### 15.3 FlipEval 模板

```json
{
  "id": "bc_flip_000001",
  "benchmark": "BenchClaw",
  "split": "test",
  "media": {"type": "image_pair", "paths": ["images/original.png", "images/flipped.png"]},
  "task": {"family": "robustness_pair", "subtype": "horizontal_flip_left_right"},
  "prompt": {
    "question": "Is the mug on the left or right of the plate?",
    "options": [{"id": "A", "text": "left"}, {"id": "B", "text": "right"}]
  },
  "answer": {"type": "choice", "value_original": "A", "value_transformed": "B"},
  "eval": {"primary_metric": "flip_eval"},
  "provenance": {"gt_source": "deterministic_image_transform"}
}
```

### 15.4 CAA 算法

```python
def eval_caa(samples, predictions):
    num_correct = 0.0
    chance_sum = 0.0
    n = len(samples)
    for s, pred in zip(samples, predictions):
        options = s["prompt"]["options"]
        k = len(options)
        pred_id = parse_choice(pred, options)
        gold = s["answer"]["value"].upper()
        num_correct += float(pred_id == gold)
        chance_sum += 1.0 / k
    return {"chance_adjusted_accuracy": (num_correct - chance_sum) / (n - chance_sum)}
```

---

## 16. 最终指标集

| 指标 ID | 指标名称 | 适用 Answer Type | 用途 |
|---|---|---|---|
| M1 | Accuracy | choice / bool | 分类题、判断题主指标 |
| M2 | Chance-Adjusted Accuracy | choice | 扣除随机猜测 |
| M3 | Exact Numeric Accuracy | number | 计数、离散数值 |
| M4 | MAE / RMSE | number | 连续距离、面积、角度 |
| M5 | AbsRel | number | 跨尺度数值误差 |
| M6 | δ≤阈值 | number | 定量空间估计 |
| M7 | MRA | number | 多阈值相对准确率 |
| M8 | Point-in-Mask | point2d / mask | 2D 指代定位 |
| M9 | 2D IoU / Acc@IoU | bbox2d / mask | 2D grounding |
| M10 | Order Exact Accuracy | ordered_list | 出现顺序、距离排序 |
| M11 | Kendall Tau | ordered_list | 排序部分正确性 |
| M12 | Sequence EM | action_sequence | 路径/动作序列 |
| M13 | Step Accuracy | action_sequence | 单步动作诊断 |
| M14 | CircularEval | choice | 选项顺序鲁棒性 |
| M15 | FlipEval | choice / bool | left/right 偏置检测 |

---

## 17. 题目生成准入规则

### 17.1 GT 可追溯

每道题必须包含：

```json
{
  "gt_source": "...",
  "gt_evidence": "...",
  "generation_rule": "..."
}
```

### 17.2 答案可自动评分

正式题目允许的答案类型：

```text
choice
bool
number
point2d
bbox2d
mask
ordered_list
action_sequence
relation_tuple
```

### 17.3 题面不依赖隐藏状态

错误例子：

```text
What is the object id of the target chair?
```

正确例子：

```text
Which visible chair is closest to the table?
```

### 17.4 真实图像任务边界

真实图像可稳定生成：

```text
left/right
above/below
bbox/mask grounding
visible count
relative depth
area comparison
occlusion relation
```

真实图像需要额外 GT 才能生成：

```text
absolute metric distance
room size
camera trajectory length
3D orientation
```

所需额外 GT 包括 calibrated depth、SLAM、尺度标定、人工测量或可靠 3D reconstruction。

---

## 18. 推荐模板库目录

```text
benchclaw_templates/
  T1_single_image_relation/
    schema.json
    generator.py
    evaluator.py
    examples.jsonl

  T2_multiview_reasoning/
    schema.json
    generator.py
    evaluator.py
    examples.jsonl

  T3_video_spatiotemporal/
    schema.json
    generator.py
    evaluator.py
    examples.jsonl

  T4_2d_grounding/
    schema.json
    generator.py
    evaluator.py
    examples.jsonl

  T5_count_visibility/
    schema.json
    generator.py
    evaluator.py
    examples.jsonl

  T6_metric_estimation/
    schema.json
    generator.py
    evaluator.py
    examples.jsonl

  T7_depth_distance_ordering/
    schema.json
    generator.py
    evaluator.py
    examples.jsonl

  T8_egocentric_perspective/
    schema.json
    generator.py
    evaluator.py
    examples.jsonl

  T9_affordance_spatial/
    schema.json
    generator.py
    evaluator.py
    examples.jsonl

  T10_robustness_pairs/
    schema.json
    generator.py
    evaluator.py
    examples.jsonl
```

---

## 19. 最终原则

```text
image/video observable
+ GT from simulator or semi-supervised annotation
+ answer is closed-form or structured
+ evaluator is deterministic
+ provenance is auditable
```

最终保留的核心模板：

```text
single-image relation
multi-view reasoning
video temporal reasoning
2D point/bbox/mask grounding
counting and visibility
metric estimation
depth/distance/size ordering
egocentric perspective reasoning
spatial affordance reasoning
robustness and counterfactual pairs
```

这套模板库适合 BenchClaw 的制造逻辑：用仿真器或半监督工具产生可靠 GT，再把 GT 编译成可自动评分的图像/视频空间智能题目。
