#!/usr/bin/env python3
"""
单图 -> 视觉 LLM/VLM 读图生成候选名词 -> YOLOE 仅做标签存在性验证 -> SAM3 text-only 实体/语义分割 -> Depth Anything 3 原分辨率深度
输出:
  - <out_dir>/result.json
  - <out_dir>/semantic_entity_segmentation.png
  - <out_dir>/depth_map.png
  - <out_dir>/da3_export/ (DA3 原始导出, 含绝对深度)

调用的本地服务 (必须已启动):
  - YOLOE       http://127.0.0.1:8766
  - SAM3        http://127.0.0.1:8765
  - DA3 backend http://127.0.0.1:8008
  - VLM/LLM (qwen, OpenAI-compatible multimodal)  http://127.0.0.1:9001
"""

import argparse
import base64
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

_THIS_FILE = Path(__file__).resolve()
_DEFAULT_BENCHCLAW_ROOT = _THIS_FILE.parents[2]
BENCHCLAW_ROOT = Path(
    os.environ.get("BENCHCLAW_ROOT", str(_DEFAULT_BENCHCLAW_ROOT))
).resolve()
ANNOT_ROOT = BENCHCLAW_ROOT / "annotation-tool"

YOLOE_CLIENT = Path(
    os.environ.get("YOLOE_CLIENT", str(ANNOT_ROOT / "yoloe" / "yoloe_client.py"))
).resolve()
SAM3_CLIENT = Path(
    os.environ.get("SAM3_CLIENT", str(ANNOT_ROOT / "sam3" / "sam3_client.py"))
).resolve()
DA3_CLIENT = Path(
    os.environ.get(
        "DA3_CLIENT", str(ANNOT_ROOT / "depthanything3" / "depthanything3_client.py")
    )
).resolve()
LLM_CLIENT = Path(
    os.environ.get("LLM_CLIENT", str(ANNOT_ROOT / "llm-local" / "llm_local_client.py"))
).resolve()

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:9001")
LLM_MODEL_ID = os.environ.get("LLM_MODEL_ID", "qwen3.5-0.8b")


# ----------------------------- stage3 contract finalizer ----------------------


def _stage3_db_schema_sql() -> str:
    return """
    CREATE TABLE IF NOT EXISTS semi_gt_candidates (
      record_id TEXT NOT NULL,
      candidate_id TEXT NOT NULL,
      branch TEXT NOT NULL,
      source_type TEXT,
      artifact_paths_json TEXT,
      candidate_json TEXT NOT NULL,
      PRIMARY KEY (record_id, candidate_id)
    );
    """


def finalize_stage3_contract(
    *,
    workspace_root: Path,
    branch: str,
    group_name: str,
    split_name: Optional[str],
    record_id: str,
    image_path: Path,
    sem_image_path: Path,
    depth_image_path: Path,
    result_json_path: Path,
    instances: List[Dict[str, Any]],
    out_dir: Path,
) -> Dict[str, Any]:
    """Materialize Stage3 artifact subtree + manifest + SQLite candidate source.

    Layout for non-simulator branches:

        WORKSPACE_ROOT/stage3/artifacts/<data_17|data_18>/default_annotation/
            <group>[/<split>]/<record_id>/
            original/<record_id>.<ext>
            semantic_entity_segmentation/<record_id>.png
            depth/<record_id>.png
            gt/<record_id>.json   (fused candidate record)

    Also appends one manifest record to:
        WORKSPACE_ROOT/stage3/artifacts/<data_17|data_18>/default_annotation_manifest.jsonl

    And inserts each candidate into stage3.db:
        WORKSPACE_ROOT/stage3/stage3.db, table semi_gt_candidates
    """
    if branch not in ("realdata", "benchmarkdataset"):
        raise ValueError(f"unsupported branch: {branch!r}")

    workspace_root = workspace_root.resolve()
    for field, value in (("group_name", group_name), ("record_id", record_id), ("split_name", split_name or "default_split")):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value) or value in (".", ".."):
            raise ValueError(f"unsafe {field}: {value!r}")
    for source in (image_path, sem_image_path, depth_image_path, result_json_path):
        if not source.is_file() or source.stat().st_size == 0:
            raise ValueError(f"missing Stage3 source: {source}")

    stage3_root = workspace_root / "stage3"
    if branch == "realdata":
        bundle_root = stage3_root / "artifacts" / "data_17_annotated_real_image_bundle"
        record_root = bundle_root / "default_annotation" / group_name / record_id
    else:
        split_part = split_name or "default_split"
        bundle_root = (
            stage3_root
            / "artifacts"
            / "data_18_annotated_existing_benchmark_bundle"
        )
        record_root = bundle_root / "default_annotation" / group_name / split_part / record_id

    if not record_root.resolve().is_relative_to(workspace_root):
        raise ValueError("Stage3 output escapes workspace")
    for parent in [record_root, *record_root.parents]:
        if parent == workspace_root:
            break
        if parent.is_symlink():
            raise ValueError("Stage3 symlink output is forbidden")

    subdirs = {
        name: record_root / name
        for name in ("original", "semantic_entity_segmentation", "depth", "gt")
    }
    for d in subdirs.values():
        d.mkdir(parents=True, exist_ok=True)

    original_target = subdirs["original"] / f"{record_id}{image_path.suffix or '.jpg'}"
    sem_target = subdirs["semantic_entity_segmentation"] / f"{record_id}.png"
    depth_target = subdirs["depth"] / f"{record_id}.png"
    gt_target = subdirs["gt"] / f"{record_id}.json"

    for src, dst in [
        (image_path, original_target),
        (sem_image_path, sem_target),
        (depth_image_path, depth_target),
    ]:
        if src.exists():
            shutil.copy2(src, dst)

    def _ws_rel(p: Path) -> str:
        try:
            rel = p.relative_to(workspace_root)
        except ValueError:
            return f"WORKSPACE_ROOT/{p}"
        return f"WORKSPACE_ROOT/{rel}"

    artifact_paths = {
        "original": _ws_rel(original_target),
        "semantic_entity_segmentation": _ws_rel(sem_target),
        "depth": _ws_rel(depth_target),
        "gt": _ws_rel(gt_target),
    }

    fused_record: Dict[str, Any] = {
        "record_id": record_id,
        "branch": branch,
        "source_type": "tool_generated_candidate",
        "is_final_gt": False,
        "artifact_paths": artifact_paths,
        "tool_chain": [
            {"tool": "llm-local", "role": "vlm_candidate_terms"},
            {"tool": "yoloe", "role": "label_existence_verification"},
            {"tool": "sam3", "role": "text_prompt_entity_segmentation"},
            {"tool": "depthanything3", "role": "absolute_depth"},
        ],
        "instances": instances,
        "result_json_path": _ws_rel(result_json_path),
        "out_dir": _ws_rel(out_dir),
    }
    gt_target.write_text(
        json.dumps(fused_record, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    candidates_for_db: List[Dict[str, Any]] = []
    for idx, inst in enumerate(instances):
        candidate_id = inst.get("instance_id") or f"{record_id}_cand_{idx:04d}"
        candidate_obj = {
            "record_id": record_id,
            "candidate_id": candidate_id,
            "branch": branch,
            "source_type": "tool_generated_candidate",
            "semantic_label": inst.get("semantic_label"),
            "segmentation": inst.get("segmentation"),
            "depth": inst.get("depth"),
            "yoloe_confidence": inst.get("yoloe_confidence"),
            "artifact_paths": artifact_paths,
            "is_final_gt": False,
        }
        candidates_for_db.append(candidate_obj)

    bundle_root.mkdir(parents=True, exist_ok=True)
    manifest_path = bundle_root / "default_annotation_manifest.jsonl"
    with manifest_path.open("a", encoding="utf-8") as f:
        manifest_row = {
            "record_id": record_id,
            "branch": branch,
            "gt_candidates": candidates_for_db,
            "artifact_paths": artifact_paths,
            "source_type": "tool_generated_candidate",
            "out_dir": _ws_rel(out_dir),
        }
        f.write(json.dumps(manifest_row, ensure_ascii=False) + "\n")

    db_path = stage3_root / "stage3.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_stage3_db_schema_sql())
        for cand in candidates_for_db:
            conn.execute(
                "INSERT OR REPLACE INTO semi_gt_candidates "
                "(record_id, candidate_id, branch, source_type, artifact_paths_json, candidate_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    cand["record_id"],
                    cand["candidate_id"],
                    cand["branch"],
                    cand["source_type"],
                    json.dumps(artifact_paths, ensure_ascii=False),
                    json.dumps(cand, ensure_ascii=False),
                ),
            )
        conn.commit()
    finally:
        conn.close()

    return {
        "branch": branch,
        "record_id": record_id,
        "record_root": str(record_root),
        "artifact_paths": artifact_paths,
        "manifest_path": str(manifest_path),
        "stage3_db_path": str(db_path),
        "num_candidates": len(candidates_for_db),
    }


# ----------------------------- low level utils -----------------------------


def run_client(cmd: List[str], timeout: int = 600) -> Dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, *cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "client call failed: "
            + " ".join(cmd)
            + "\nstdout:\n"
            + proc.stdout
            + "\nstderr:\n"
            + proc.stderr
        )
    text = proc.stdout.strip()
    if not text:
        return {}
    last_obj: Optional[Dict[str, Any]] = None
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(text):
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            idx += 1
            continue
        if isinstance(obj, dict):
            last_obj = obj
        idx = end
        while idx < len(text) and text[idx] in " \t\r\n":
            idx += 1
    if last_obj is not None:
        return last_obj
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}


def http_post_json(
    url: str, payload: Dict[str, Any], timeout: int = 120
) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_stream_delta(event: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """从 OpenAI-compatible /v1/chat/completions stream event 中提取增量文本。"""
    choices = event.get("choices") or []
    if not choices:
        return "", None
    choice = choices[0]
    finish_reason = choice.get("finish_reason")

    # ChatCompletions streaming: {"choices": [{"delta": {"content": "..."}}]}
    delta = choice.get("delta") or {}
    content = delta.get("content")

    # 有些兼容实现可能返回 text 字段
    if content is None:
        content = choice.get("text")

    if isinstance(content, list):
        # 极少数多模态实现会把 content 切成 list；这里只保留 text 段。
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, str):
                parts.append(item)
        content = "".join(parts)

    return str(content or ""), finish_reason


class CandidateTermStreamParser:
    """实时解析 VLM 输出中的 candidate_terms。

    目标：
      - 不等完整 JSON 结束；
      - 一边收到 SSE delta，一边从 candidate_terms 数组里抽取字符串标签；
      - 最多保留 max_unique_terms 个不同标签；
      - 如果连续解析到 stop_repeat_count 个相同标签，认为模型开始复读，立即停止。
    """

    def __init__(self, max_unique_terms: int = 100, stop_repeat_count: int = 3):
        self.max_unique_terms = max(1, min(int(max_unique_terms), 100))
        self.stop_repeat_count = max(2, int(stop_repeat_count))

        self._pre_key_buffer = ""
        self._seen_candidate_key = False
        self._in_candidate_array = False
        self._in_string = False
        self._escape = False
        self._current_chars: List[str] = []

        self.terms: List[str] = []
        self._seen_terms = set()
        self.raw_label_count = 0
        self.duplicate_label_count = 0
        self.ignored_label_count = 0

        self.last_label: Optional[str] = None
        self.consecutive_same_count = 0
        self.should_stop = False
        self.stop_reason: Optional[str] = None

    def feed(self, chunk: str) -> List[str]:
        new_terms: List[str] = []
        if not chunk or self.should_stop:
            return new_terms

        for ch in chunk:
            if self.should_stop:
                break

            if not self._in_candidate_array:
                self._pre_key_buffer = (self._pre_key_buffer + ch)[-256:]
                if (
                    not self._seen_candidate_key
                    and "candidate_terms" in self._pre_key_buffer
                ):
                    self._seen_candidate_key = True
                if self._seen_candidate_key and ch == "[":
                    self._in_candidate_array = True
                continue

            if not self._in_string:
                if ch == '"':
                    self._in_string = True
                    self._escape = False
                    self._current_chars = []
                elif ch == "]":
                    self.should_stop = True
                    self.stop_reason = "json_candidate_terms_array_closed"
                    break
                else:
                    continue
                continue

            # inside a JSON string
            if self._escape:
                self._current_chars.append(ch)
                self._escape = False
            elif ch == "\\":
                self._escape = True
            elif ch == '"':
                raw_label = "".join(self._current_chars)
                self._in_string = False
                self._current_chars = []
                parsed = normalize_detection_terms([raw_label], max_terms=1)
                if not parsed:
                    self.ignored_label_count += 1
                    continue

                label = parsed[0]
                self.raw_label_count += 1

                if label == self.last_label:
                    self.consecutive_same_count += 1
                else:
                    self.last_label = label
                    self.consecutive_same_count = 1

                if label in self._seen_terms:
                    self.duplicate_label_count += 1
                else:
                    self._seen_terms.add(label)
                    self.terms.append(label)
                    new_terms.append(label)

                if self.consecutive_same_count >= self.stop_repeat_count:
                    self.should_stop = True
                    self.stop_reason = (
                        f"consecutive_same_label_{self.stop_repeat_count}:{label}"
                    )
                    break

                if len(self.terms) >= self.max_unique_terms:
                    self.should_stop = True
                    self.stop_reason = f"max_unique_terms_{self.max_unique_terms}"
                    break
            else:
                self._current_chars.append(ch)

        return new_terms


def _salvage_terms_from_broken_json(text: str, max_terms: int) -> List[str]:
    """从被截断的不完整 JSON 中抢救 candidate_terms。"""
    if not text or "candidate_terms" not in text:
        return []
    tail = text.split("candidate_terms", 1)[-1]
    quoted = re.findall(r'"([^"\n\r]{1,96})"', tail)
    bad = {"candidate_terms", "term1", "term2"}
    terms = []
    for item in quoted:
        item = item.strip().lower()
        if item and item not in bad:
            terms.append(item)
    return normalize_detection_terms(terms, max_terms=max_terms)


def http_post_vlm_stream_terms(
    url: str,
    payload: Dict[str, Any],
    timeout: int,
    max_unique_terms: int = 100,
    stop_repeat_count: int = 3,
) -> Tuple[List[str], Dict[str, Any]]:
    """向 vLLM 发起 stream=True 请求，并实时解析 candidate_terms。"""
    payload = dict(payload)
    payload["stream"] = True
    payload['stream_options']={'include_usage':True}

    parser = CandidateTermStreamParser(
        max_unique_terms=max_unique_terms,
        stop_repeat_count=stop_repeat_count,
    )
    raw_chunks: List[str] = []
    reasoning_chunks: List[str] = []
    response_model = None
    event_count = 0
    usage = None
    finish_reason: Optional[str] = None

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        while True:
            line = resp.readline()
            if not line:
                break
            text_line = line.decode("utf-8", errors="replace").strip()
            if not text_line:
                continue
            if not text_line.startswith("data:"):
                continue

            data = text_line[len("data:") :].strip()
            if data == "[DONE]":
                finish_reason = finish_reason or "done"
                break

            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue

            event_count += 1
            if event.get('model'):response_model=event['model']
            for choice in event.get('choices',[]):
                delta=choice.get('delta',{})
                thought=delta.get('reasoning_content') or delta.get('reasoning')
                if thought:reasoning_chunks.append(thought)
            if event.get('usage') is not None:
                usage=event['usage']
            delta_text, delta_finish_reason = _extract_stream_delta(event)
            if delta_finish_reason:
                finish_reason = delta_finish_reason
            if not delta_text:
                continue

            raw_chunks.append(delta_text)
            new_terms = parser.feed(delta_text)
            if new_terms:
                print(
                    f"[stream] VLM labels +{len(new_terms)} total={len(parser.terms)}: {new_terms}",
                    file=sys.stderr,
                    flush=True,
                )

            if parser.should_stop:
                # 关闭 HTTP 连接，停止继续等待 vLLM 生成。
                break

    raw_content = "".join(raw_chunks)
    terms = parser.terms

    if not terms:
        # 兜底：如果服务没有按预期 stream 出 array 内字符串，就尝试完整/半截解析。
        obj = _extract_json_object(raw_content)
        if isinstance(obj, dict) and isinstance(obj.get("candidate_terms"), list):
            terms = normalize_detection_terms(
                obj["candidate_terms"], max_terms=max_unique_terms
            )
        else:
            terms = _salvage_terms_from_broken_json(
                raw_content, max_terms=max_unique_terms
            )

    info = {
        "streaming": True,
        "response_model": response_model,
        "reasoning_content": ''.join(reasoning_chunks),
        "usage": usage,
        "usage_complete": usage is not None,
        "stream_event_count": event_count,
        "stream_finish_reason": finish_reason,
        "stream_stop_reason": parser.stop_reason or finish_reason or "stream_exhausted",
        "raw_content": raw_content,
        "raw_label_count": parser.raw_label_count,
        "duplicate_label_count": parser.duplicate_label_count,
        "ignored_label_count": parser.ignored_label_count,
        "max_unique_terms": parser.max_unique_terms,
        "stop_repeat_count": parser.stop_repeat_count,
        "stopped_early": bool(parser.should_stop),
    }
    return terms, info


# ----------------------------- VLM helpers ---------------------------------


def image_to_data_url(image_path: Path) -> str:
    suffix = image_path.suffix.lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }.get(suffix, "image/png")
    b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """尽量从模型输出里提取 JSON object，兼容 code fence / 前后废话。"""
    if not text:
        return None
    stripped = text.strip()

    candidates = [
        stripped,
        stripped.removeprefix("```json").removesuffix("```").strip(),
        stripped.removeprefix("```").removesuffix("```").strip(),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
            return obj if isinstance(obj, dict) else None
        except Exception:
            pass

    match = re.search(r"\{[\s\S]*\}", stripped)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def normalize_detection_terms(terms: List[Any], max_terms: int) -> List[str]:
    banned = {
        "image",
        "photo",
        "picture",
        "scene",
        "view",
        "background",
        "foreground",
        "object",
        "thing",
        "stuff",
        "area",
        "region",
        "left",
        "right",
        "front",
        "back",
        "near",
        "far",
        "distance",
        "danger",
        "traffic",
        "roadway",
        "walkability",
        "occlusion",
    }
    seen = set()
    cleaned: List[str] = []
    for raw in terms:
        term = str(raw).strip().lower()
        term = re.sub(r"^[\s\-•*\d.)]+", "", term)
        term = re.sub(r"[^a-z0-9 /_-]+", " ", term)
        term = term.replace("_", "-")
        term = re.sub(r"\s+", " ", term).strip()
        term = re.sub(r"^(a|an|the) ", "", term)
        if not term or term in banned:
            continue
        words = term.split()
        if len(words) > 4:
            continue
        if any(w in banned for w in words):
            continue
        if term not in seen:
            seen.add(term)
            cleaned.append(term)
        if len(cleaned) >= max_terms:
            break
    return cleaned


def _build_vlm_messages(
    image_path: Path,
    user_hint: Optional[str],
    max_terms: int,
    attempt_idx: int,
    last_error: Optional[str],
) -> List[Dict[str, Any]]:
    system = (
        "You are a vision-language assistant for open-vocabulary object detection and semantic segmentation. "
        "You must inspect the provided image directly and output JSON only. "
        "The output schema must be exactly: "
        '{"candidate_terms": ["term1", "term2"]}. '
        "Critical rule: list ONLY things that are actually visible in the image. "
        "Do not guess, infer, assume, hallucinate, or add objects that are merely common for this scene type. "
        "If a category is uncertain, tiny beyond recognition, hidden, implied, or not directly supported by visual evidence, omit it. "
        "The list is for downstream detection/segmentation, so every term must correspond to a visible localizable object, stuff region, surface, or infrastructure element. "
        "Include both countable objects and stuff/background categories only when visible. "
        "Examples of valid visible labels include car, truck, road, building, tree, field, roof, bridge, power line, utility pole, grass, water, sky, shadow, fence, sidewalk, lane marking. "
        "Examples of invalid labels include possible hidden objects, generic scene captions, actions, relations, abstract concepts, intentions, risks, and objects not directly visible. "
        "Use canonical detector-friendly English nouns or short noun phrases. "
        "Each label must be lowercase and appear at most once. "
        "Do not repeat a label even if there are many instances of that category. "
        "Do not pad the list to reach the maximum; fewer accurate visible labels are better than many guessed labels. "
        "No markdown. No explanation. No code fence. JSON only."
    )

    hint = f"User hint: {user_hint}" if user_hint else "No user hint."
    retry_block = ""
    if attempt_idx > 0:
        retry_block = (
            f"\nThis is retry attempt #{attempt_idx + 1}. "
            "Your previous response could not be parsed as valid JSON or had unusable content. "
            "Return a single valid JSON object only. "
        )
        if last_error:
            retry_block += f"Previous parser error summary: {last_error}\n"

    user_text = (
        f"{hint}\n"
        f"Inspect the image carefully and list up to {max_terms} visible semantic labels.\n"
        "Only include categories that are directly visible in this exact image. "
        "Do not include anything inferred from context, scene type, common sense, or prior knowledge. "
        "Do not include duplicates, near-duplicate repetitions, captions, actions, spatial-only descriptions, or uncertain objects.\n"
        "Return one JSON object with exactly one top-level key: candidate_terms.\n"
        'Example valid output: {"candidate_terms": ["road", "car", "building", "tree", "field"]}\n'
        "Do not output markdown, comments, prose, or any extra keys."
        f"{retry_block}"
    )

    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {
                    "type": "image_url",
                    "image_url": {"url": image_to_data_url(image_path)},
                },
            ],
        },
    ]


def _call_vlm_for_terms(
    image_path: Path,
    user_hint: Optional[str],
    max_terms: int,
    attempt_idx: int,
    last_error: Optional[str],
    timeout: int,
) -> Tuple[List[str], Dict[str, Any]]:
    """stream=True 调 vLLM，实时解析 candidate_terms，满足停止条件后立即进入后续流程。"""
    hard_max_terms = min(int(max_terms), 100)
    payload = {
        "model": LLM_MODEL_ID,
        "messages": _build_vlm_messages(
            image_path=image_path,
            user_hint=user_hint,
            max_terms=hard_max_terms,
            attempt_idx=attempt_idx,
            last_error=last_error,
        ),
        "temperature": 0,
        # 给足上限，但不会等它生成完：达到 100 个不同标签或连续 3 个相同标签会主动关闭 stream。
        "max_tokens": 32000,
        "repetition_penalty": 1.1,
        "stream": True,
    }

    if os.environ.get("BENCHCLAW_DISABLE_THINKING") == "1":
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    if os.environ.get('BENCHCLAW_VLM_GENERATION'):
        payload.update(json.loads(os.environ['BENCHCLAW_VLM_GENERATION']))
        timeout=int(os.environ.get('BENCHCLAW_VLM_TIMEOUT',timeout))
    terms, stream_info = http_post_vlm_stream_terms(
        f"{LLM_BASE_URL}/v1/chat/completions",
        payload=payload,
        timeout=timeout,
        max_unique_terms=hard_max_terms,
        stop_repeat_count=3,
    )

    terms = normalize_detection_terms(terms, max_terms=hard_max_terms)
    if not terms:
        raise RuntimeError(
            "streaming VLM produced no usable candidate terms. "
            f"stream_stop_reason={stream_info.get('stream_stop_reason')}; "
            f"raw_content={stream_info.get('raw_content')!r}"
        )

    return terms, {
        "source": "vision_llm_image_inspection_streaming",
        "model": LLM_MODEL_ID,
        "endpoint": LLM_BASE_URL+'/v1/chat/completions',
        "generation_parameters": {k:v for k,v in payload.items() if k!='messages'},
        "raw_content": stream_info.get("raw_content"),
        "num_terms": len(terms),
        "fallback_used": False,
        "attempt_index": attempt_idx,
        "parsed_json": {"candidate_terms": terms},
        **stream_info,
    }


def vlm_extract_candidate_terms(
    image_path: Path,
    user_hint: Optional[str],
    max_terms: int = 100,
    allow_generic_fallback: bool = False,
    max_retries: int = 3,
    timeout: int = 180,
) -> Tuple[List[str], Dict[str, Any]]:
    """让多模态 VLM 真正读取图片，尽可能输出严格 JSON；解析失败则自动重试。"""
    attempt_logs: List[Dict[str, Any]] = []
    last_error: Optional[str] = None
    total_attempts = max(1, max_retries + 1)

    for attempt_idx in range(total_attempts):
        try:
            terms, info = _call_vlm_for_terms(
                image_path=image_path,
                user_hint=user_hint,
                max_terms=max_terms,
                attempt_idx=attempt_idx,
                last_error=last_error,
                timeout=timeout,
            )
            info["attempt_count"] = attempt_idx + 1
            info["max_retries"] = max_retries
            info["attempt_logs"] = attempt_logs
            return terms, info
        except Exception as exc:
            last_error = str(exc)
            attempt_logs.append(
                {
                    "attempt_index": attempt_idx,
                    "error": last_error,
                }
            )
            print(
                f"[warn] VLM candidate-term attempt {attempt_idx + 1}/{total_attempts} failed: {last_error}",
                file=sys.stderr,
            )
            if attempt_idx + 1 < total_attempts:
                time.sleep(min(2 * (attempt_idx + 1), 5))

    if not allow_generic_fallback:
        raise RuntimeError(
            "VLM image-based candidate generation failed after retries. Refusing to use a generic text-only "
            "vocabulary because that would be fake image understanding. Start a multimodal OpenAI-compatible "
            "Qwen/VLM endpoint at LLM_BASE_URL, or pass --allow-generic-fallback if you explicitly want a weak fallback. "
            f"Last error: {last_error}"
        )

    fallback = [
        "person",
        "car",
        "bus",
        "truck",
        "bicycle",
        "motorcycle",
        "traffic light",
        "traffic sign",
        "tree",
        "building",
        "road",
        "sky",
        "sidewalk",
        "chair",
        "table",
        "sofa",
        "bed",
        "tv",
        "laptop",
        "cup",
        "bottle",
        "plant",
        "dog",
        "cat",
    ]
    terms = normalize_detection_terms(fallback, max_terms=max_terms)
    return terms, {
        "source": "generic_fallback_vocabulary",
        "model": LLM_MODEL_ID,
        "raw_content": None,
        "num_terms": len(terms),
        "fallback_used": True,
        "fallback_reason": last_error,
        "attempt_count": total_attempts,
        "max_retries": max_retries,
        "attempt_logs": attempt_logs,
    }


# ----------------------------- YOLOE ---------------------------------------


def run_yoloe_text_infer(
    image_path: Path, class_names: List[str], conf: float, work_dir: Path
) -> Dict[str, Any]:
    annotated_path = work_dir / "yoloe_annotated.png"
    names = ",".join(class_names)
    cmd = [
        str(YOLOE_CLIENT),
        "text-infer",
        "--image-path",
        str(image_path),
        "--names",
        names,
        "--conf",
        str(conf),
        "--annotated-output-path",
        str(annotated_path),
    ]
    return run_client(cmd, timeout=600)


def collect_yoloe_verified_labels(
    detections: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """把 YOLOE 检测结果压缩成“存在性验证后的标签”。

    注意：这里的 box 只作为存在性证据写入 JSON，不再作为 SAM3 的 prompt。
    后续分割只使用 SAM3 text prompt。
    """
    label_to_info: Dict[str, Dict[str, Any]] = {}
    for det in detections:
        label = str(det.get("class_name") or "").strip().lower()
        if not label:
            continue
        conf_raw = det.get("confidence")
        try:
            conf = float(conf_raw) if conf_raw is not None else None
        except Exception:
            conf = None
        box = det.get("box_xyxy")

        if label not in label_to_info:
            label_to_info[label] = {
                "semantic_label": label,
                "yoloe_verified": True,
                "yoloe_detection_count": 0,
                "yoloe_max_confidence": conf,
                "yoloe_boxes": [],
            }
        info = label_to_info[label]
        info["yoloe_detection_count"] += 1
        if conf is not None:
            old = info.get("yoloe_max_confidence")
            info["yoloe_max_confidence"] = (
                conf if old is None else max(float(old), conf)
            )
        if box is not None:
            info["yoloe_boxes"].append(box)

    return sorted(
        label_to_info.values(),
        key=lambda x: (-(x.get("yoloe_max_confidence") or 0.0), x["semantic_label"]),
    )


def build_sam3_label_plan(
    vlm_terms: List[str],
    yoloe_verified_labels: List[Dict[str, Any]],
    max_labels: int = 160,
) -> List[Dict[str, Any]]:
    """构造最终送给 SAM3 的 text prompt 标签集合。

    关键策略：
      - VLM 标签全部送给 SAM3；
      - YOLOE 验证到的标签也全部送给 SAM3；
      - 两者取并集并去重；
      - YOLOE 只提供存在性证据，不给 SAM3 传 box。
    """
    plan: Dict[str, Dict[str, Any]] = {}

    for term in normalize_detection_terms(vlm_terms, max_terms=max_labels):
        plan[term] = {
            "semantic_label": term,
            "vlm_proposed": True,
            "yoloe_verified": False,
            "yoloe_confidence": None,
            "yoloe_detection_count": 0,
            "yoloe_boxes": [],
            "sam3_prompt_source": "vlm_only",
        }

    for item in yoloe_verified_labels:
        label = str(item.get("semantic_label") or "").strip().lower()
        norm = normalize_detection_terms([label], max_terms=1)
        if not norm:
            continue
        label = norm[0]
        if label not in plan:
            plan[label] = {
                "semantic_label": label,
                "vlm_proposed": False,
                "yoloe_verified": True,
                "yoloe_confidence": item.get("yoloe_max_confidence"),
                "yoloe_detection_count": item.get("yoloe_detection_count", 0),
                "yoloe_boxes": item.get("yoloe_boxes", []),
                "sam3_prompt_source": "yoloe_only",
            }
        else:
            plan[label].update(
                {
                    "yoloe_verified": True,
                    "yoloe_confidence": item.get("yoloe_max_confidence"),
                    "yoloe_detection_count": item.get("yoloe_detection_count", 0),
                    "yoloe_boxes": item.get("yoloe_boxes", []),
                    "sam3_prompt_source": "vlm_and_yoloe",
                }
            )

    # 排序：YOLOE 验证过的标签优先；同组内按置信度和原始顺序/字母序稳定输出。
    def _rank(item: Dict[str, Any]) -> Tuple[int, float, str]:
        verified_rank = 0 if item.get("yoloe_verified") else 1
        conf = float(item.get("yoloe_confidence") or 0.0)
        return (verified_rank, -conf, item["semantic_label"])

    return sorted(plan.values(), key=_rank)[:max_labels]


# ----------------------------- SAM3 ----------------------------------------


def _unwrap_client_result(resp: Dict[str, Any]) -> Dict[str, Any]:
    """兼容 annotation-tool client 的返回格式。

    sam3_client.py 实际返回通常是：
      {"ok": true, "result": {"pred_masks": ..., "pred_scores": ...}}
    旧代码直接从顶层 resp["pred_masks"] 取，导致明明有 mask 却被误判为空。
    """
    if isinstance(resp, dict) and isinstance(resp.get("result"), dict):
        return resp["result"]
    return resp if isinstance(resp, dict) else {}


def _decode_coco_compressed_rle_counts(counts: str) -> Optional[List[int]]:
    """Pure-Python decoder for COCO compressed RLE counts strings.

    This removes the runtime dependency on pycocotools.  The algorithm mirrors
    pycocotools/_mask.pyx + maskApi.c rleFrString(): each run length is stored
    in 5-bit chunks with continuation/sign bits, and runs after the second one
    are delta-coded against the run two positions before.
    """
    if not isinstance(counts, str):
        return None

    decoded: List[int] = []
    p = 0
    m = 0
    n = len(counts)

    try:
        while p < n:
            x = 0
            k = 0
            more = True
            while more:
                c = ord(counts[p]) - 48
                p += 1
                x |= (c & 0x1F) << (5 * k)
                more = (c & 0x20) != 0
                # sign extension for negative delta values
                if not more and (c & 0x10):
                    x |= -1 << (5 * (k + 1))
                k += 1

            if m > 2:
                x += decoded[m - 2]
            if x < 0:
                return None
            decoded.append(int(x))
            m += 1
    except Exception:
        return None

    return decoded


def _counts_to_mask(counts: List[int], h: int, w: int) -> Optional[np.ndarray]:
    """Convert uncompressed COCO RLE run lengths to an HxW bool mask."""
    total = int(h) * int(w)
    flat = np.zeros(total, dtype=np.uint8)
    idx = 0
    val = 0

    for raw_count in counts:
        try:
            count = int(raw_count)
        except Exception:
            return None
        if count < 0:
            return None

        end = idx + count
        if end > total:
            return None
        if val == 1 and count > 0:
            flat[idx:end] = 1
        idx = end
        val = 1 - val

    if idx != total:
        return None

    # COCO RLE is column-major.  reshape as (w, h).T to recover HxW.
    return flat.reshape((w, h)).T.astype(bool)


def _rle_to_mask(
    rle: Any, h: Optional[int] = None, w: Optional[int] = None
) -> Optional[np.ndarray]:
    """Decode SAM3 RLE into an HxW bool mask.

    Supported formats:
      1. COCO dict: {"size": [h, w], "counts": list|str}
      2. Bare COCO compressed RLE string returned by sam3_client.py.

    This function intentionally does not require pycocotools.  Your environment
    may not have pycocotools installed, and SAM3 still returns valid compressed
    COCO RLE strings that can be decoded directly.
    """
    size = None
    counts: Any = None

    if isinstance(rle, dict):
        size = rle.get("size") or rle.get("size_hw") or rle.get("shape")
        counts = rle.get("counts")
        if size is not None:
            h, w = int(size[0]), int(size[1])
    elif isinstance(rle, str):
        counts = rle
    else:
        return None

    if counts is None or h is None or w is None:
        return None

    h = int(h)
    w = int(w)

    if isinstance(counts, list):
        return _counts_to_mask([int(c) for c in counts], h, w)

    if isinstance(counts, bytes):
        counts = counts.decode("utf-8")

    if isinstance(counts, str):
        decoded_counts = _decode_coco_compressed_rle_counts(counts)
        if decoded_counts is None:
            return None
        return _counts_to_mask(decoded_counts, h, w)

    return None


def _box_to_mask(box_xyxy: List[float], h: int, w: int) -> np.ndarray:
    x1, y1, x2, y2 = box_xyxy
    x1 = max(0, int(round(x1)))
    y1 = max(0, int(round(y1)))
    x2 = min(w, int(round(x2)))
    y2 = min(h, int(round(y2)))
    mask = np.zeros((h, w), dtype=bool)
    if x2 > x1 and y2 > y1:
        mask[y1:y2, x1:x2] = True
    return mask


def run_sam3_for_verified_label(
    image_path: Path,
    label: str,
    h: int,
    w: int,
    max_masks: int = 20,
    min_score: Optional[float] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """只用 SAM3 text prompt 对一个已通过 YOLOE 存在性验证的标签做分割。

    关键约束：
      - 不传 YOLOE box 给 SAM3；
      - 不使用 YOLOE box 作为 fallback mask；
      - SAM3 没有返回有效 mask 时，该标签跳过，不伪造分割。
    """
    cmd = [
        str(SAM3_CLIENT),
        "image-infer",
        "--image-path",
        str(image_path),
        "--text-prompt",
        label,
    ]
    resp = run_client(cmd, timeout=600)
    result = _unwrap_client_result(resp)

    pred_masks = result.get("pred_masks") or []
    pred_scores = result.get("pred_scores") or []
    order = sorted(
        range(len(pred_masks)),
        key=lambda i: (
            -(
                float(pred_scores[i])
                if i < len(pred_scores) and pred_scores[i] is not None
                else 0.0
            )
        ),
    )

    masks: List[Dict[str, Any]] = []
    for i in order:
        score = (
            float(pred_scores[i])
            if i < len(pred_scores) and pred_scores[i] is not None
            else None
        )
        if min_score is not None and score is not None and score < min_score:
            continue
        m = _rle_to_mask(pred_masks[i], h=h, w=w)
        if m is None:
            print(
                f"[warn] SAM3 RLE decode failed for label '{label}', mask_index={i}",
                file=sys.stderr,
            )
            continue
        if m.shape != (h, w):
            print(
                f"[warn] SAM3 mask shape mismatch for label '{label}', mask_index={i}: "
                f"got {m.shape}, expected {(h, w)}",
                file=sys.stderr,
            )
            continue
        if int(m.sum()) == 0:
            continue
        masks.append(
            {
                "mask": m,
                "sam3_mask_index": int(i),
                "sam3_score": score,
            }
        )
        if len(masks) >= max_masks:
            break

    summary = {
        "sam3_session_id": result.get("session_id"),
        "sam3_prompt_type": "text_only",
        "sam3_text_prompt": label,
        "sam3_num_pred_masks": len(pred_masks),
        "sam3_num_valid_masks": len(masks),
        "sam3_top_score": float(pred_scores[0]) if pred_scores else None,
        "sam3_num_pred_boxes": len(
            result.get("pred_boxes") or result.get("boxes_xyxy") or []
        ),
        "sam3_orig_img_w": result.get("orig_img_w"),
        "sam3_orig_img_h": result.get("orig_img_h"),
        "sam3_masks_logits_shape": result.get("masks_logits_shape"),
        "yoloe_box_used_as_prompt": False,
        "bbox_fallback_used": False,
    }
    return masks, summary


# ----------------------------- DA3 -----------------------------------------


def _np_from_export_dir(export_dir: Path) -> Tuple[Optional[np.ndarray], List[Path]]:
    candidates: List[Path] = []
    for pattern in (
        "absolute_depth.npy",
        "absolute_depth.npz",
        "absolute_depth.tif*",
        "absolute_depth/frame_*.npy",
        "absolute_depth/frame_*.tif*",
        "**/*.npy",
        "**/*.npz",
        "**/*depth*.tif*",
    ):
        for path in sorted(export_dir.glob(pattern)):
            if "_vis" not in path.stem:
                candidates.append(path)

    for path in candidates:
        try:
            if path.suffix == ".npy":
                arr = np.load(path)
                if arr.ndim == 2:
                    return arr.astype(np.float32), candidates
                if arr.ndim == 3 and arr.shape[0] == 1:
                    return arr[0].astype(np.float32), candidates
                if arr.ndim == 3 and arr.shape[-1] == 1:
                    return arr[..., 0].astype(np.float32), candidates
            elif path.suffix == ".npz":
                data = np.load(path)
                for key in ("depth", "depth_map", "metric_depth", "absolute_depth"):
                    if key in data:
                        arr = data[key]
                        if arr.ndim == 2:
                            return arr.astype(np.float32), candidates
        except Exception:
            continue

    for path in candidates:
        if path.suffix.lower() in (".tif", ".tiff"):
            try:
                img = Image.open(path)
                arr = np.array(img)
                if arr.ndim == 3:
                    arr = arr[..., 0]
                return arr.astype(np.float32), candidates
            except Exception:
                continue

    return None, candidates


def run_da3(
    image_path: Path,
    work_dir: Path,
    h: int,
    w: int,
    process_res: Optional[int] = None,
) -> Tuple[Optional[np.ndarray], Path, Dict[str, Any]]:
    export_dir = work_dir / "da3_export"
    export_dir.mkdir(parents=True, exist_ok=True)

    da3_process_res = int(process_res) if process_res is not None else 1024

    method = "upper_bound_resize"
    submit_cmd = [
        str(DA3_CLIENT),
        "submit",
        "--image-path",
        str(image_path),
        "--export-dir",
        str(export_dir),
        "--export-format",
        "glb",
        "--process-res",
        str(da3_process_res),
        "--process-res-method",
        method,
    ]

    submit_resp = run_client(submit_cmd, timeout=600)
    task_id = submit_resp.get("task_id")
    if not task_id:
        raise RuntimeError(f"DA3 submit did not return task_id: {submit_resp}")

    wait_resp = run_client(
        [str(DA3_CLIENT), "wait-task", "--task-id", str(task_id)], timeout=1800
    )
    wait_text = json.dumps(wait_resp, ensure_ascii=False)
    err_text = str(wait_resp.get("error", "")) if isinstance(wait_resp, dict) else ""
    is_failed = (
        isinstance(wait_resp, dict) and wait_resp.get("status") == "failed"
    ) or bool(err_text)
    if is_failed:
        raise RuntimeError(
            f"DA3 failed at process_res={da3_process_res}. Response: {wait_text}"
        )

    depth_arr, candidate_files = _np_from_export_dir(export_dir)
    if depth_arr is not None and depth_arr.shape != (h, w):
        raise RuntimeError(
            f"DA3 depth shape {depth_arr.shape} != native image shape {(h, w)}. "
            "Expected DA3 to restore float32 depth to original resolution."
        )

    info = {
        "submit_response": submit_resp,
        "wait_response": wait_resp,
        "export_dir": str(export_dir),
        "process_res": da3_process_res,
        "process_res_method": method,
        "restored_to_original_resolution": bool(
            depth_arr is not None and depth_arr.shape == (h, w)
        ),
        "depth_candidate_files": [str(p) for p in candidate_files],
    }
    return depth_arr, export_dir, info


def assert_image_size(path: Path, expected_w: int, expected_h: int, name: str) -> None:
    with Image.open(path) as img:
        actual_w, actual_h = img.size
    if (actual_w, actual_h) != (expected_w, expected_h):
        raise RuntimeError(
            f"{name} output size {(actual_w, actual_h)} != original size "
            f"{(expected_w, expected_h)}"
        )


# ----------------------------- semantic + depth fusion ---------------------


def colorize_semantic(
    instances: List[Dict[str, Any]],
    h: int,
    w: int,
) -> Image.Image:
    rng = np.random.default_rng(42)
    canvas = np.zeros((h, w, 3), dtype=np.uint8)
    for inst in instances:
        mask = inst.get("_mask")
        if mask is None or mask.shape != (h, w):
            continue
        color = rng.integers(50, 230, size=3).tolist()
        canvas[mask] = color
    return Image.fromarray(canvas)


def colorize_depth(depth: Optional[np.ndarray], h: int, w: int) -> Image.Image:
    if depth is None:
        return Image.new("RGB", (w, h), (0, 0, 0))
    if depth.shape != (h, w):
        raise RuntimeError(
            f"depth shape {depth.shape} != original shape {(h, w)}; "
            "refusing to resize/interpolate depth_map.png."
        )
    d = depth.astype(np.float32)
    finite = np.isfinite(d)
    if finite.sum() == 0:
        return Image.new("RGB", (w, h), (0, 0, 0))
    lo = float(np.percentile(d[finite], 2))
    hi = float(np.percentile(d[finite], 98))
    if hi <= lo:
        hi = lo + 1.0
    norm = np.clip((d - lo) / (hi - lo), 0.0, 1.0)
    norm = np.where(finite, norm, 0.0)
    gray = (norm * 255.0).astype(np.uint8)
    return Image.fromarray(gray).convert("RGB")


def depth_stats_for_mask(
    depth: Optional[np.ndarray], mask: np.ndarray
) -> Dict[str, Any]:
    if depth is None:
        return {"available": False}
    if depth.shape != mask.shape:
        raise RuntimeError(
            f"depth shape {depth.shape} != mask/original shape {mask.shape}; "
            "refusing to resize/interpolate before computing depth statistics."
        )
    sel = depth[mask]
    sel = sel[np.isfinite(sel)]
    if sel.size == 0:
        return {"available": False, "pixel_count": 0}
    return {
        "available": True,
        "pixel_count": int(sel.size),
        "min": float(sel.min()),
        "max": float(sel.max()),
        "mean": float(sel.mean()),
        "median": float(np.median(sel)),
    }


# ----------------------------- entity annotation export --------------------


def _safe_name(value: str, max_len: int = 80) -> str:
    value = str(value).strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return (value or "object")[:max_len]


def compute_bbox_2d(mask: np.ndarray) -> Optional[List[int]]:
    ys, xs = np.where(mask)
    if xs.size == 0 or ys.size == 0:
        return None
    # Canonical xyxy uses half-open pixel bounds, including single-pixel masks.
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def compute_centroid_2d(mask: np.ndarray) -> Optional[List[float]]:
    ys, xs = np.where(mask)
    if xs.size == 0 or ys.size == 0:
        return None
    return [float(xs.mean()), float(ys.mean())]


def estimate_camera_intrinsics(
    width: int,
    height: int,
    fx: Optional[float] = None,
    fy: Optional[float] = None,
    cx: Optional[float] = None,
    cy: Optional[float] = None,
) -> Dict[str, Any]:
    """Return intrinsics for rough monocular-depth back-projection.

    If real intrinsics are unavailable, use a conservative pinhole approximation.
    This is enough for relative spatial relations and rough 3D boxes, but not for
    metrology-grade measurement.
    """
    source = "provided"
    if fx is None:
        fx = float(max(width, height))
        source = "estimated_from_image_size"
    if fy is None:
        fy = float(fx)
        if source == "provided":
            source = "partially_estimated"
    if cx is None:
        cx = float(width) / 2.0
        if source == "provided":
            source = "partially_estimated"
    if cy is None:
        cy = float(height) / 2.0
        if source == "provided":
            source = "partially_estimated"
    return {
        "fx": float(fx),
        "fy": float(fy),
        "cx": float(cx),
        "cy": float(cy),
        "source": source,
        "coordinate_frame": "camera_frame_x_right_y_down_z_forward",
    }


def mask_depth_values(mask: np.ndarray, depth: Optional[np.ndarray]) -> np.ndarray:
    if depth is None:
        return np.zeros((0,), dtype=np.float32)
    if depth.shape != mask.shape:
        raise RuntimeError(
            f"depth shape {depth.shape} != mask/original shape {mask.shape}; "
            "refusing to resize/interpolate for entity annotations."
        )
    vals = depth[mask].astype(np.float32)
    vals = vals[np.isfinite(vals) & (vals > 0)]
    return vals


def mask_to_rough_pointcloud(
    mask: np.ndarray,
    depth: Optional[np.ndarray],
    intrinsics: Dict[str, Any],
    max_points: int = 50000,
) -> np.ndarray:
    """Back-project visible mask pixels to a rough camera-frame point cloud."""
    if depth is None:
        return np.zeros((0, 3), dtype=np.float32)
    if depth.shape != mask.shape:
        raise RuntimeError(
            f"depth shape {depth.shape} != mask/original shape {mask.shape}; "
            "refusing to resize/interpolate for 3D annotation."
        )

    ys, xs = np.where(mask)
    if xs.size == 0:
        return np.zeros((0, 3), dtype=np.float32)

    zs = depth[ys, xs].astype(np.float32)
    valid = np.isfinite(zs) & (zs > 0)
    xs = xs[valid].astype(np.float32)
    ys = ys[valid].astype(np.float32)
    zs = zs[valid]
    if zs.size == 0:
        return np.zeros((0, 3), dtype=np.float32)

    # Remove gross monocular-depth outliers before estimating boxes.
    if zs.size >= 20:
        lo, hi = np.percentile(zs, [3, 97])
        keep = (zs >= lo) & (zs <= hi)
        xs, ys, zs = xs[keep], ys[keep], zs[keep]

    if zs.size > max_points:
        # Deterministic subsample for reproducibility.
        idx = np.linspace(0, zs.size - 1, max_points).astype(np.int64)
        xs, ys, zs = xs[idx], ys[idx], zs[idx]

    fx = float(intrinsics["fx"])
    fy = float(intrinsics["fy"])
    cx = float(intrinsics["cx"])
    cy = float(intrinsics["cy"])

    x3 = (xs - cx) * zs / fx
    y3 = (ys - cy) * zs / fy
    z3 = zs
    return np.stack([x3, y3, z3], axis=1).astype(np.float32)


def compute_rough_3d_bbox(points: np.ndarray) -> Optional[Dict[str, Any]]:
    """Compute a rough camera-frame AABB from visible object points."""
    if points is None or len(points) == 0:
        return None
    mn = points.min(axis=0)
    mx = points.max(axis=0)
    center = (mn + mx) / 2.0
    size = mx - mn
    return {
        "type": "axis_aligned_visible_surface_bbox",
        "coordinate_frame": "camera_frame_x_right_y_down_z_forward",
        "min_xyz": [float(x) for x in mn.tolist()],
        "max_xyz": [float(x) for x in mx.tolist()],
        "center_xyz": [float(x) for x in center.tolist()],
        "size_xyz": [float(x) for x in size.tolist()],
        "note": "rough AABB from visible SAM3 mask pixels and monocular absolute depth; not a full-object CAD box",
    }


def compute_centroid_3d(points: np.ndarray) -> Optional[List[float]]:
    if points is None or len(points) == 0:
        return None
    c = np.median(points, axis=0)
    return [float(x) for x in c.tolist()]


def combine_entity_confidence(inst: Dict[str, Any]) -> Dict[str, Any]:
    """Combine model signals into a single question-generation confidence.

    SAM3 score is the primary evidence because the final object exists as a mask.
    YOLOE confidence is used as existence evidence when available.  VLM-only
    labels are slightly penalized because they are not detector-verified.
    """
    sam3_score = inst.get("sam3_score")
    yoloe_conf = inst.get("yoloe_confidence")
    try:
        sam3_score_f = float(sam3_score) if sam3_score is not None else None
    except Exception:
        sam3_score_f = None
    try:
        yoloe_conf_f = float(yoloe_conf) if yoloe_conf is not None else None
    except Exception:
        yoloe_conf_f = None

    if sam3_score_f is not None and yoloe_conf_f is not None:
        value = 0.70 * sam3_score_f + 0.30 * yoloe_conf_f
        rule = "0.70*sam3_score+0.30*yoloe_confidence"
    elif sam3_score_f is not None:
        value = sam3_score_f * (0.90 if inst.get("vlm_proposed") else 0.80)
        rule = "sam3_score_with_vlm_only_penalty"
    elif yoloe_conf_f is not None:
        value = yoloe_conf_f * 0.60
        rule = "yoloe_confidence_only_penalized"
    else:
        value = 0.0
        rule = "missing_confidence"

    value = max(0.0, min(1.0, float(value)))
    return {
        "value": value,
        "rule": rule,
        "components": {
            "sam3_score": sam3_score_f,
            "yoloe_confidence": yoloe_conf_f,
            "vlm_proposed": bool(inst.get("vlm_proposed")),
            "yoloe_verified": bool(inst.get("yoloe_verified")),
        },
    }


def save_instance_masks_and_build_entity_annotations(
    instances: List[Dict[str, Any]],
    out_dir: Path,
    depth: Optional[np.ndarray],
    image_width: int,
    image_height: int,
    intrinsics: Dict[str, Any],
    min_question_confidence: float = 0.25,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Save per-instance masks and build GT-like entity annotations.

    Each returned object contains the required fields requested by the user:
      object_id, category, mask, bbox_2d, depth_median, centroid_3d,
      rough_3d_bbox, confidence.
    """
    mask_dir = out_dir / "instance_masks"
    mask_dir.mkdir(parents=True, exist_ok=True)

    annotations: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for inst in instances:
        mask = inst.get("_mask")
        object_id = str(inst.get("instance_id"))
        category = str(inst.get("semantic_label") or "object")

        if (
            mask is None
            or not isinstance(mask, np.ndarray)
            or mask.shape != (image_height, image_width)
        ):
            skipped.append(
                {
                    "object_id": object_id,
                    "category": category,
                    "reason": "missing_or_bad_mask",
                }
            )
            continue
        mask_area = int(mask.sum())
        if mask_area <= 0:
            skipped.append(
                {"object_id": object_id, "category": category, "reason": "empty_mask"}
            )
            continue

        bbox_2d = compute_bbox_2d(mask)
        centroid_2d = compute_centroid_2d(mask)
        if bbox_2d is None or centroid_2d is None:
            skipped.append(
                {
                    "object_id": object_id,
                    "category": category,
                    "reason": "failed_bbox_or_centroid_2d",
                }
            )
            continue

        mask_path = mask_dir / f"{object_id}__{_safe_name(category)}.png"
        Image.fromarray((mask.astype(np.uint8) * 255)).save(mask_path)
        inst["mask_path"] = str(mask_path)

        depth_vals = mask_depth_values(mask, depth)
        depth_available = bool(depth_vals.size > 0)
        depth_stats = {
            "available": depth_available,
            "pixel_count": int(depth_vals.size),
            "median": float(np.median(depth_vals)) if depth_available else None,
            "mean": float(np.mean(depth_vals)) if depth_available else None,
            "min": float(np.min(depth_vals)) if depth_available else None,
            "max": float(np.max(depth_vals)) if depth_available else None,
            "p05": float(np.percentile(depth_vals, 5)) if depth_available else None,
            "p95": float(np.percentile(depth_vals, 95)) if depth_available else None,
        }

        points = mask_to_rough_pointcloud(mask, depth, intrinsics)
        centroid_3d = compute_centroid_3d(points)
        rough_3d_bbox = compute_rough_3d_bbox(points)
        confidence = combine_entity_confidence(inst)
        valid_for_question_generation = bool(
            confidence["value"] >= min_question_confidence
            and bbox_2d is not None
            and mask_area > 0
            and depth_available
        )

        ann = {
            "object_id": object_id,
            "category": category,
            "mask": {
                "path": str(mask_path),
                "format": "png_uint8_binary_0_255",
                "height": int(image_height),
                "width": int(image_width),
                "area_px": mask_area,
            },
            "bbox_2d": {
                "xyxy": bbox_2d,
                "normalized_xyxy": [
                    float(bbox_2d[0] / image_width),
                    float(bbox_2d[1] / image_height),
                    float(bbox_2d[2] / image_width),
                    float(bbox_2d[3] / image_height),
                ],
                "centroid_xy": centroid_2d,
                "centroid_normalized_xy": [
                    float(centroid_2d[0] / image_width),
                    float(centroid_2d[1] / image_height),
                ],
            },
            "depth_median": depth_stats["median"],
            "depth_stats": depth_stats,
            "centroid_3d": {
                "xyz": centroid_3d,
                "coordinate_frame": intrinsics.get("coordinate_frame"),
                "available": centroid_3d is not None,
            },
            "rough_3d_bbox": rough_3d_bbox,
            "confidence": confidence,
            "valid_for_question_generation": valid_for_question_generation,
            "source": {
                "vlm_proposed": bool(inst.get("vlm_proposed")),
                "yoloe_verified": bool(inst.get("yoloe_verified")),
                "sam3_prompt_source": inst.get("sam3_prompt_source"),
                "segmentation_source": inst.get("segmentation_source"),
                "detection_source": inst.get("detection_source"),
                "yoloe_detection_count": inst.get("yoloe_detection_count"),
                "yoloe_boxes_for_existence_check_only": inst.get(
                    "yoloe_boxes_for_existence_check_only", []
                ),
                "sam3_mask_index": inst.get("sam3_mask_index"),
                "sam3_score": inst.get("sam3_score"),
            },
        }
        inst["entity_annotation"] = ann
        annotations.append(ann)

    summary = {
        "num_instances_input": len(instances),
        "num_entity_annotations": len(annotations),
        "num_skipped": len(skipped),
        "skipped": skipped,
        "mask_dir": str(mask_dir),
        "camera_intrinsics": intrinsics,
        "min_question_confidence": float(min_question_confidence),
        "field_contract": {
            "object_id": "required",
            "category": "required",
            "mask": "required",
            "bbox_2d": "required",
            "depth_median": "required_when_depth_available",
            "centroid_3d": "strongly_recommended_computed_when_depth_available",
            "rough_3d_bbox": "recommended_computed_when_depth_available",
            "confidence": "required",
        },
    }
    return annotations, summary


# ----------------------------- main pipeline -------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, help="原始输入图像路径")
    ap.add_argument(
        "--out-dir",
        default=None,
        help="输出目录, 默认为 ~/run_image_to_semantic_depth_out/<image_stem>_<ts>",
    )
    ap.add_argument(
        "--user-hint",
        default=None,
        help="给 VLM 的场景类型 hint, 只作为辅助上下文，不允许替代图像理解",
    )
    ap.add_argument("--yoloe-conf", type=float, default=0.25)
    ap.add_argument(
        "--sam3-max-masks-per-label",
        type=int,
        default=20,
        help="每个通过 YOLOE 存在性验证的语义标签最多保留多少个 SAM3 mask。默认 20。",
    )
    ap.add_argument(
        "--sam3-min-score",
        type=float,
        default=None,
        help="SAM3 mask 分数下限。默认不设下限。",
    )
    ap.add_argument(
        "--max-vlm-terms",
        type=int,
        default=100,
        help="VLM 根据图片生成的候选名词上限，硬上限 100，默认 100。",
    )
    ap.add_argument(
        "--vlm-max-retries",
        type=int,
        default=3,
        help="VLM 输出 JSON 失败时的最大重试次数。默认 3，实际总尝试次数=1+重试次数。",
    )
    ap.add_argument(
        "--vlm-timeout",
        type=int,
        default=180,
        help="单次 VLM 请求超时时间（秒）。默认 180。",
    )
    ap.add_argument(
        "--allow-generic-fallback",
        action="store_true",
        help="VLM 读图失败时允许使用通用词表。默认关闭，避免假装看图。",
    )
    ap.add_argument(
        "--da3-process-res",
        type=int,
        default=None,
        help=(
            "DA3 处理分辨率。默认 1024：最长边等比例缩放到该值推理，"
            "再将 float32 深度还原到原图分辨率。"
        ),
    )
    ap.add_argument(
        "--fx", type=float, default=None, help="相机内参 fx；不提供则用 max(W,H) 近似。"
    )
    ap.add_argument(
        "--fy", type=float, default=None, help="相机内参 fy；不提供则默认等于 fx。"
    )
    ap.add_argument(
        "--cx", type=float, default=None, help="相机内参 cx；不提供则用 W/2。"
    )
    ap.add_argument(
        "--cy", type=float, default=None, help="相机内参 cy；不提供则用 H/2。"
    )
    ap.add_argument(
        "--min-question-confidence",
        type=float,
        default=0.25,
        help="实体可用于自动出题的最低置信度阈值，默认 0.25。",
    )
    ap.add_argument(
        "--workspace-root",
        default=None,
        help=(
            "（可选）BenchClaw workspace 根目录。如果提供，则脚本会按 Stage3 contract 落"
            " stage3/{realdata|benchmarkdataset}/<group>/<split?>/<record_id>/{original,"
            "semantic_entity_segmentation,depth,gt}/ 四件套，并追加 semi_gt_manifest.sqlite_export.jsonl"
            "（同步写入 stage3.db.semi_gt_candidates）。"
        ),
    )
    ap.add_argument(
        "--branch",
        choices=["realdata", "benchmarkdataset"],
        default=None,
        help="Stage3 非仿真器分支：realdata 或 benchmarkdataset。仅当 --workspace-root 提供时生效。",
    )
    ap.add_argument(
        "--group-name",
        default=None,
        help="realdata 的 <real_scene_or_source>，或 benchmarkdataset 的 <dataset_name>。",
    )
    ap.add_argument(
        "--split-name",
        default=None,
        help="benchmarkdataset 的 <existing_dataset_split_or_category>，realdata 可省略。",
    )
    ap.add_argument(
        "--record-id",
        default=None,
        help=("Stage3 用于追溯样本的 record_id；不提供时默认使用图像 stem。"),
    )
    args = ap.parse_args()
    if args.workspace_root and (not args.branch or not args.group_name):
        print("[error] Stage3 requires --branch and --group-name", file=sys.stderr)
        return 2

    image_path = Path(args.image).resolve()
    if not image_path.is_file():
        print(f"image not found: {image_path}", file=sys.stderr)
        return 2

    if args.out_dir:
        out_dir = Path(args.out_dir).resolve()
    else:
        ts = time.strftime("%Y%m%d_%H%M%S")
        out_dir = (
            Path.home() / "run_image_to_semantic_depth_out" / f"{image_path.stem}_{ts}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[info] image    = {image_path}")
    print(f"[info] out_dir  = {out_dir}")

    with Image.open(image_path) as im:
        im = im.convert("RGB")
        w, h = im.size
    print(f"[info] size     = {w}x{h}")

    print("[step] VLM image-based candidate terms ...")
    candidate_terms, vlm_info = vlm_extract_candidate_terms(
        image_path=image_path,
        user_hint=args.user_hint,
        max_terms=args.max_vlm_terms,
        allow_generic_fallback=args.allow_generic_fallback,
        max_retries=args.vlm_max_retries,
        timeout=args.vlm_timeout,
    )
    print(
        f"[info] vision_llm_candidate_terms ({len(candidate_terms)}): "
        f"{candidate_terms[:10]}..."
    )
    if vlm_info.get("fallback_used"):
        print(
            "[warn] using generic fallback vocabulary; VLM did not actually provide "
            "image-grounded candidates",
            file=sys.stderr,
        )

    print("[step] YOLOE existence verification for VLM candidate terms ...")
    yoloe_resp = run_yoloe_text_infer(
        image_path, candidate_terms, args.yoloe_conf, out_dir
    )
    detections = (yoloe_resp.get("result") or {}).get("detections") or []
    verified_labels = collect_yoloe_verified_labels(detections)
    sam3_label_plan = build_sam3_label_plan(
        vlm_terms=candidate_terms,
        yoloe_verified_labels=verified_labels,
        max_labels=max(100, args.max_vlm_terms),
    )

    print(f"[info] YOLOE detections: {len(detections)}")
    print(f"[info] YOLOE-verified labels: {len(verified_labels)}")
    print(f"[info] SAM3 input labels from VLM union YOLOE: {len(sam3_label_plan)}")
    if verified_labels:
        print(
            f"[info] YOLOE verified labels preview: "
            f"{[item['semantic_label'] for item in verified_labels[:20]]}"
        )
    if sam3_label_plan:
        print(
            f"[info] SAM3 label plan preview: "
            f"{[item['semantic_label'] + ':' + item['sam3_prompt_source'] for item in sam3_label_plan[:30]]}"
        )
    else:
        print(
            "[warn] no VLM or YOLOE labels are available; SAM3 segmentation will be empty.",
            file=sys.stderr,
        )

    print("[step] SAM3 text-only segmentation for VLM union YOLOE labels ...")
    instances: List[Dict[str, Any]] = []
    inst_idx = 0
    for label_info in sam3_label_plan:
        label = label_info["semantic_label"]
        try:
            sam_masks, sam_info = run_sam3_for_verified_label(
                image_path=image_path,
                label=label,
                h=h,
                w=w,
                max_masks=args.sam3_max_masks_per_label,
                min_score=args.sam3_min_score,
            )
        except Exception as exc:
            print(f"[warn] SAM3 failed on label '{label}': {exc}", file=sys.stderr)
            sam_masks = []
            sam_info = {
                "sam3_error": str(exc),
                "sam3_prompt_type": "text_only",
                "sam3_text_prompt": label,
                "yoloe_box_used_as_prompt": False,
                "bbox_fallback_used": False,
            }

        if not sam_masks:
            print(
                f"[warn] SAM3 returned no valid mask for label '{label}' "
                f"source={label_info.get('sam3_prompt_source')}, skip it.",
                file=sys.stderr,
            )
            continue

        for local_mask_idx, mask_info in enumerate(sam_masks):
            inst = {
                "instance_id": f"inst_{inst_idx:04d}",
                "semantic_label": label,
                "vlm_proposed": bool(label_info.get("vlm_proposed")),
                "yoloe_verified": bool(label_info.get("yoloe_verified")),
                "yoloe_confidence": label_info.get("yoloe_confidence"),
                "yoloe_detection_count": label_info.get("yoloe_detection_count"),
                "yoloe_boxes_for_existence_check_only": label_info.get(
                    "yoloe_boxes", []
                ),
                "sam3_prompt_source": label_info.get("sam3_prompt_source"),
                "detection_source": "vlm_union_yoloe_labels_to_sam3_text_only",
                "segmentation_source": "sam3_text_prompt_only",
                "sam3_mask_index": mask_info.get("sam3_mask_index"),
                "sam3_score": mask_info.get("sam3_score"),
                "_mask": mask_info["mask"],
                "sam3": sam_info,
            }
            instances.append(inst)
            inst_idx += 1

    print("[step] Depth Anything 3 ...")
    depth_arr, da3_export_dir, da3_info = run_da3(
        image_path, out_dir, h, w, process_res=args.da3_process_res
    )
    if depth_arr is not None:
        print(f"[info] depth shape: {depth_arr.shape}")
    else:
        print("[warn] no usable depth numpy was found under DA3 export dir")

    for inst in instances:
        inst["depth"] = depth_stats_for_mask(depth_arr, inst["_mask"])

    print("[step] build structured entity annotations ...")
    camera_intrinsics = estimate_camera_intrinsics(
        width=w,
        height=h,
        fx=args.fx,
        fy=args.fy,
        cx=args.cx,
        cy=args.cy,
    )
    entity_annotations, entity_annotation_summary = (
        save_instance_masks_and_build_entity_annotations(
            instances=instances,
            out_dir=out_dir,
            depth=depth_arr,
            image_width=w,
            image_height=h,
            intrinsics=camera_intrinsics,
            min_question_confidence=args.min_question_confidence,
        )
    )
    entity_annotations_path = out_dir / "entity_annotations.json"
    entity_annotations_payload = {
        "image_path": str(image_path),
        "image_size": {"width": w, "height": h},
        "camera_intrinsics": camera_intrinsics,
        "summary": entity_annotation_summary,
        "objects": entity_annotations,
    }
    entity_annotations_path.write_text(
        json.dumps(entity_annotations_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"[info] entity annotations: {len(entity_annotations)} -> {entity_annotations_path}"
    )

    print("[step] render semantic / depth visualizations ...")
    sem_img = colorize_semantic(instances, h, w)
    sem_path = out_dir / "semantic_entity_segmentation.png"
    sem_img.save(sem_path)
    assert_image_size(sem_path, w, h, "semantic_entity_segmentation.png")

    depth_img = colorize_depth(depth_arr, h, w)
    depth_path = out_dir / "depth_map.png"
    depth_img.save(depth_path)
    assert_image_size(depth_path, w, h, "depth_map.png")
    if depth_arr is not None:
        np.save(out_dir / "depth.npy", depth_arr.astype(np.float32), allow_pickle=False)

    clean_instances = []
    for inst in instances:
        clean_instances.append(
            {
                "instance_id": inst["instance_id"],
                "semantic_label": inst["semantic_label"],
                "object_id": inst.get("instance_id"),
                "category": inst.get("semantic_label"),
                "mask_path": inst.get("mask_path"),
                "bbox_2d": (inst.get("entity_annotation") or {}).get("bbox_2d"),
                "depth_median": (inst.get("entity_annotation") or {}).get(
                    "depth_median"
                ),
                "centroid_3d": (inst.get("entity_annotation") or {}).get("centroid_3d"),
                "rough_3d_bbox": (inst.get("entity_annotation") or {}).get(
                    "rough_3d_bbox"
                ),
                "confidence": (inst.get("entity_annotation") or {}).get("confidence"),
                "valid_for_question_generation": (
                    inst.get("entity_annotation") or {}
                ).get("valid_for_question_generation"),
                "vlm_proposed": inst.get("vlm_proposed", False),
                "yoloe_verified": inst.get("yoloe_verified", False),
                "sam3_prompt_source": inst.get("sam3_prompt_source"),
                "yoloe_confidence": inst.get("yoloe_confidence"),
                "yoloe_detection_count": inst.get("yoloe_detection_count"),
                "yoloe_boxes_for_existence_check_only": inst.get(
                    "yoloe_boxes_for_existence_check_only", []
                ),
                "detection_source": inst["detection_source"],
                "segmentation": {
                    "source": "sam3_text_prompt_only",
                    "sam3_mask_index": inst.get("sam3_mask_index"),
                    "sam3_score": inst.get("sam3_score"),
                    "yoloe_box_used_as_prompt": False,
                    "bbox_fallback_used": False,
                    "mask_summary": {
                        "pixel_count": int(inst["_mask"].sum()),
                        "image_height": h,
                        "image_width": w,
                    },
                    "sam3": inst["sam3"],
                },
                "depth": inst["depth"],
            }
        )

    result = {
        "image_path": str(image_path),
        "image_size": {"width": w, "height": h},
        "vision_llm_candidate_terms": candidate_terms,
        "vision_llm": vlm_info,
        "yoloe": {
            "candidate_source": "vision_llm_candidate_terms",
            "mode": yoloe_resp.get("mode"),
            "service_device": yoloe_resp.get("service_device"),
            "checkpoint_path": yoloe_resp.get("checkpoint_path"),
            "num_candidate_terms": len(candidate_terms),
            "num_detections": (yoloe_resp.get("result") or {}).get("num_detections"),
            "role": "existence_verification_only",
            "boxes_used_for_sam3_prompt": False,
            "verified_labels": verified_labels,
            "num_verified_labels": len(verified_labels),
        },
        "sam3": {
            "role": "final_segmentation_generator",
            "prompt_type": "text_only",
            "input_label_policy": "union_of_vlm_candidate_terms_and_yoloe_verified_labels",
            "input_labels": sam3_label_plan,
            "num_input_labels": len(sam3_label_plan),
            "uses_yoloe_boxes": False,
            "bbox_fallback_enabled": False,
            "max_masks_per_label": args.sam3_max_masks_per_label,
            "min_score": args.sam3_min_score,
            "num_output_masks": len(instances),
        },
        "entity_annotations": {
            "path": str(entity_annotations_path),
            "num_objects": len(entity_annotations),
            "summary": entity_annotation_summary,
        },
        "depth_anything_3": {
            "export_dir": str(da3_export_dir),
            "depth_available": depth_arr is not None,
            "depth_shape": list(depth_arr.shape) if depth_arr is not None else None,
            "restored_to_original_resolution": da3_info.get(
                "restored_to_original_resolution"
            ),
            "process_res": da3_info.get("process_res"),
            "process_res_method": da3_info.get("process_res_method"),
            "depth_unit_hint": "absolute_depth (DA3 backend default)",
            "depth_files_found": da3_info.get("depth_candidate_files"),
            "submit_response": da3_info.get("submit_response"),
            "wait_response": da3_info.get("wait_response"),
        },
        "outputs": {
            "depth_array": str(out_dir / "depth.npy") if depth_arr is not None else None,
            "semantic_entity_segmentation_image": str(sem_path),
            "depth_map_image": str(depth_path),
            "entity_annotations_json": str(entity_annotations_path),
            "instance_mask_dir": str(out_dir / "instance_masks"),
            "da3_export_dir": str(da3_export_dir),
        },
        "instances": clean_instances,
    }

    result_path = out_dir / "result.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[done] result.json -> {result_path}")
    print(f"[done] semantic    -> {sem_path}")
    print(f"[done] depth       -> {depth_path}")
    print(f"[done] entities    -> {entity_annotations_path}")

    if args.workspace_root:
        if not args.branch:
            print(
                "[warn] --workspace-root provided but --branch missing; skipping Stage3 contract finalize",
                file=sys.stderr,
            )
        elif not args.group_name:
            print(
                "[warn] --workspace-root provided but --group-name missing; skipping Stage3 contract finalize",
                file=sys.stderr,
            )
        else:
            workspace_root = Path(args.workspace_root).resolve()
            record_id = args.record_id or image_path.stem
            try:
                finalize_info = finalize_stage3_contract(
                    workspace_root=workspace_root,
                    branch=args.branch,
                    group_name=args.group_name,
                    split_name=args.split_name,
                    record_id=record_id,
                    image_path=image_path,
                    sem_image_path=sem_path,
                    depth_image_path=depth_path,
                    result_json_path=result_path,
                    instances=clean_instances,
                    out_dir=out_dir,
                )
                print(
                    f"[done] stage3 contract -> record_root={finalize_info['record_root']} "
                    f"candidates={finalize_info['num_candidates']}"
                )
            except Exception as exc:
                print(
                    f"[error] Stage3 contract finalize failed: {exc}",
                    file=sys.stderr,
                )
                return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
