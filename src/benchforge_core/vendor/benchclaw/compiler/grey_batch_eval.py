#!/usr/bin/env python3
"""Grey small-batch evaluation helper.

This script provides:

1. sampling 100 evaluation instances per question_format;
2. question-only JSONL for external model inference;
3. a prediction template JSONL;
4. OpenAI-compatible multimodal inference across model difficulty tiers;
5. scoring and aggregation for grey-validation answer formats.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import csv
import json
import math
import mimetypes
import os
import random
import re
import statistics
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

try:
    import requests
except ImportError:  # pragma: no cover - handled at runtime for inference mode.
    requests = None


DEFAULT_DATASET = Path("artifacts/data_20_grey_batch/items.jsonl")
DEFAULT_OUT_ROOT = Path("artifacts/data_21_grey_eval_results")
DEFAULT_PER_FORMAT = 100
DEFAULT_SEED = 20260601


def find_benchclaw_root() -> Path:
    here = Path(__file__).resolve()
    env_root = os.environ.get("BENCHCLAW_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    for parent in here.parents:
        if (parent / "modelNeedMeasured").is_dir() and (parent / "skills").is_dir():
            return parent
    # Stage4 subskill scripts must also run inside isolated skill packages during smoke tests.
    # Fall back to the nearest ancestor containing a skills directory, then to cwd.
    for parent in here.parents:
        if (parent / "skills").is_dir():
            return parent
    return Path.cwd().resolve()


BENCHCLAW_ROOT = find_benchclaw_root()
DEFAULT_CONFIG = BENCHCLAW_ROOT / "modelNeedMeasured" / "model_config.json"

DEFAULT_ENDPOINT = "https://api.ephone.ai/v1/chat/completions"

# Legacy env fallback is still accepted for local compatibility, but the
# canonical source of truth is BENCHCLAW_ROOT/modelNeedMeasured/model_config.json.
DEFAULT_API_KEY_SLOTS: Dict[str, str] = {
    "key1": "",
    "key2": "",
    "key3": "",
}
DEFAULT_API_KEY_ENV_NAMES = ("EPHONE_KEY_1", "EPHONE_KEY_2", "EPHONE_KEY_3")
DEFAULT_MODEL_GROUPS: Dict[str, Dict[str, Any]] = {}

DEFAULT_SYSTEM_PROMPT = (
    "你是一个严谨的图文题评测模型。"
    "请只根据图片和题目作答，不要编造图片中不存在的信息。"
    "如果题目有选项，优先输出选项字母。"
)

NO_IMAGE_RESPONSE_RE = re.compile(
    r"未提供.*(?:图片|图像)|没有.*(?:图片|图像)|无法.*(?:图片|图像)|"
    r"请.*提供.*(?:图片|图像)|看不到.*(?:图片|图像)|无法获取图片"
)


PREDICTION_KEYS = ("prediction", "pred", "answer", "model_answer", "response", "output")


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_no}: expected JSON object")
            rows.append(row)
    return rows


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n")


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json_arg(value: Optional[str], default: Any = None) -> Any:
    """Read a JSON CLI value from either a JSON string or a JSON file path."""
    if value is None or value == "":
        return default
    value = value.strip()
    candidate = Path(value).expanduser()
    if candidate.is_file():
        return json.loads(candidate.read_text(encoding="utf-8"))
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Cannot parse JSON argument: {value[:200]}") from exc


def load_config(path_value: Optional[str]) -> Dict[str, Any]:
    if not path_value:
        return {}
    path = Path(path_value).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Config file does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Config file must contain a JSON object: {path}")
    return payload


def is_opencode_model_config(config: Dict[str, Any]) -> bool:
    return isinstance(config.get("provider"), dict) and (
        "grey_test" in config or "full_test" in config
    )


def normalize_chat_completions_endpoint(base_url: str) -> str:
    text = str(base_url or "").strip()
    if not text:
        return ""
    if text.endswith("/chat/completions"):
        return text
    return text.rstrip("/") + "/chat/completions"


def resolve_api_key_value(raw_value: Any) -> str:
    text = str(raw_value or "").strip()
    if not text or text in {"EMPTY", "xxxx"}:
        return ""
    if text.startswith("${") and text.endswith("}"):
        return os.environ.get(text[2:-1], "").strip()
    return text


def resolve_api_model_name(model_id: str, model_cfg: Dict[str, Any]) -> str:
    for key in ("api_model", "model", "name"):
        value = str(model_cfg.get(key) or "").strip()
        if value:
            return value
    return model_id


def parse_model_ref(model_ref: str) -> Tuple[str, str]:
    provider_id, sep, model_id = str(model_ref).partition("/")
    if not sep or not provider_id.strip() or not model_id.strip():
        raise ValueError(
            f"Invalid model reference {model_ref!r}; expected 'provider_id/model_id'."
        )
    return provider_id.strip(), model_id.strip()


def build_plan_from_opencode_config(
    config: Dict[str, Any],
    test_group: str,
    models_filter: Optional[Sequence[str]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    if test_group not in config:
        raise ValueError(
            f"Config missing test group {test_group!r}; expected one of grey_test/full_test."
        )
    group_cfg = config.get(test_group) or {}
    model_refs = group_cfg.get("models")
    if not isinstance(model_refs, list) or not model_refs:
        raise ValueError(f"Config {test_group}.models must be a non-empty list.")

    selected_models = set(models_filter or [])
    providers = config.get("provider") or {}
    plan: List[Dict[str, Any]] = []
    seen = set()
    for raw_ref in model_refs:
        model_ref = str(raw_ref).strip()
        if not model_ref:
            continue
        if selected_models and model_ref not in selected_models:
            continue
        if model_ref in seen:
            continue
        provider_id, model_id = parse_model_ref(model_ref)
        provider_cfg = providers.get(provider_id)
        if not isinstance(provider_cfg, dict):
            raise ValueError(f"Unknown provider {provider_id!r} for model {model_ref!r}.")
        provider_models = provider_cfg.get("models") or {}
        model_cfg = provider_models.get(model_id)
        if not isinstance(model_cfg, dict):
            raise ValueError(f"Unknown model id {model_id!r} under provider {provider_id!r}.")
        options = provider_cfg.get("options") or {}
        endpoint = normalize_chat_completions_endpoint(
            str(options.get("baseURL") or options.get("baseUrl") or "")
        )
        if not endpoint:
            raise ValueError(f"Provider {provider_id!r} missing options.baseURL/baseUrl.")
        provider_api_key = resolve_api_key_value(options.get("apiKey"))
        key_items = [(provider_id, provider_api_key)] if provider_api_key else []
        plan.append(
            {
                "tier": test_group,
                "model": model_ref,
                "api_model": resolve_api_model_name(model_id, model_cfg),
                "provider_id": provider_id,
                "display_name": str(model_cfg.get("name") or model_id),
                "endpoint": endpoint,
                "key_items": key_items,
                "capabilities": model_cfg.get("capabilities") or {},
            }
        )
        seen.add(model_ref)
    if not plan:
        raise ValueError(f"No models selected from {test_group}.models.")

    sampling = group_cfg.get("sampling") if isinstance(group_cfg, dict) else None
    sample_ratio = 1.0
    if isinstance(sampling, dict) and sampling.get("enabled") is False:
        sample_ratio = 1.0
    model_groups = {
        test_group: {
            "sample_ratio": sample_ratio,
            "models": [entry["model"] for entry in plan],
        }
    }
    return plan, model_groups


def pick_config_value(
    args: argparse.Namespace,
    config: Dict[str, Any],
    cli_name: str,
    config_name: Optional[str] = None,
    default: Any = None,
) -> Any:
    value = getattr(args, cli_name)
    if value not in (None, ""):
        return value
    return config.get(config_name or cli_name, default)


def csv_or_list(value: Any) -> List[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return parse_csv_arg(value)
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    raise TypeError(f"Expected comma-separated string or list, got {type(value).__name__}")


def infer_setting(args: argparse.Namespace, config: Dict[str, Any], name: str, default: Any) -> Any:
    value = getattr(args, name)
    return value if value is not None else config.get(name, default)


def guess_mime_type(image_path: str) -> str:
    mime, _ = mimetypes.guess_type(image_path)
    return mime or "image/jpeg"


def image_to_data_url(image_path: str) -> str:
    path = Path(image_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"图片文件不存在: {image_path}")
    mime = guess_mime_type(str(path))
    b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def normalize_image_input(image: str) -> str:
    image = image.strip()
    if image.startswith(("http://", "https://", "data:image/")):
        return image
    return image_to_data_url(image)


def image_file_metadata(image: Any) -> Dict[str, Any]:
    image_text = str(image or "").strip()
    meta: Dict[str, Any] = {"image": image_text}
    if not image_text or image_text.startswith(("http://", "https://", "data:image/")):
        return meta
    path = Path(image_text).expanduser()
    meta["exists"] = path.is_file()
    if path.is_file():
        stat = path.stat()
        meta.update(
            {
                "bytes": stat.st_size,
                "suffix": path.suffix,
                "mime_type": guess_mime_type(str(path)),
            }
        )
    return meta


def format_options(options: Any) -> str:
    if not options:
        return ""
    if isinstance(options, dict):
        return "\n".join(f"{k}. {v}" for k, v in options.items())
    if isinstance(options, list):
        labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        lines = []
        for idx, opt in enumerate(options):
            label = labels[idx] if idx < len(labels) else str(idx)
            lines.append(f"{label}. {opt}")
        return "\n".join(lines)
    return str(options)


def get_response_text(resp_json: Dict[str, Any]) -> str:
    """Extract assistant text from an OpenAI-compatible chat completion."""
    choices = resp_json.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif "text" in item:
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


def looks_like_no_image_response(response_text: Any) -> bool:
    return bool(NO_IMAGE_RESPONSE_RE.search(str(response_text or "")))


def usage_shows_vision_input(usage: Optional[Dict[str, Any]]) -> Optional[bool]:
    """Infer whether the upstream counted image input from provider usage fields."""
    if not isinstance(usage, dict):
        return None
    prompt_tokens = usage.get("prompt_tokens")
    details = usage.get("prompt_tokens_details") or {}
    if not isinstance(prompt_tokens, (int, float)):
        return None
    if isinstance(details, dict) and isinstance(details.get("text_tokens"), (int, float)):
        text_tokens = details["text_tokens"]
        if prompt_tokens <= text_tokens + 32:
            return False
    if prompt_tokens > 1000:
        return True
    return None


def raw_has_usable_vision(raw_record: Dict[str, Any]) -> bool:
    if raw_record.get("ok") is not True:
        return False
    if raw_record.get("vision_missing_response") is True:
        return False
    if raw_record.get("vision_used") is False:
        return False
    usage = (raw_record.get("response_json") or {}).get("usage")
    if usage_shows_vision_input(usage) is False:
        return False
    if looks_like_no_image_response(raw_record.get("response_text")):
        return False
    return True


def read_api_keys_from_env() -> Dict[str, str]:
    keys = dict(DEFAULT_API_KEY_SLOTS)
    for idx, env_name in enumerate(DEFAULT_API_KEY_ENV_NAMES, 1):
        value = os.environ.get(env_name, "").strip()
        if value:
            keys[f"key{idx}"] = value
    return {key: value for key, value in keys.items() if value}


def normalize_api_keys(api_keys: Union[List[str], Dict[str, str]]) -> List[Tuple[str, str]]:
    if isinstance(api_keys, dict):
        preferred = [f"key{i}" for i in range(1, 4)]
        ordered_names = [name for name in preferred if name in api_keys]
        ordered_names.extend(name for name in api_keys if name not in ordered_names)
        return [(str(name), str(api_keys[name]).strip()) for name in ordered_names if str(api_keys[name]).strip()]
    if isinstance(api_keys, list):
        return [(f"key{i + 1}", str(value).strip()) for i, value in enumerate(api_keys) if str(value).strip()]
    raise TypeError("api_keys must be a list or dict")


def parse_csv_arg(value: str) -> List[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def iter_model_plan(tiers: Sequence[str], models_filter: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    selected_models = set(models_filter or [])
    plan: List[Dict[str, Any]] = []
    seen = set()
    for tier in tiers:
        if tier not in DEFAULT_MODEL_GROUPS:
            raise ValueError(f"Unknown model tier {tier!r}; choose from {list(DEFAULT_MODEL_GROUPS)}")
        group = DEFAULT_MODEL_GROUPS[tier]
        for model in group["models"]:
            if selected_models and model not in selected_models:
                continue
            if model in seen:
                continue
            plan.append(
                {
                    "tier": tier,
                    "model": model,
                    "sample_ratio": group.get("sample_ratio"),
                }
            )
            seen.add(model)
    return plan


def choose_api_key(
    key_items: Sequence[Tuple[str, str]],
    model: str,
    tier: str,
    model_index: int,
    key_map: Optional[Dict[str, str]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    if not key_items:
        return None, None
    by_name = {name: value for name, value in key_items}
    if key_map:
        for lookup in (model, tier, "*"):
            requested = str(key_map.get(lookup, "")).strip()
            if not requested:
                continue
            if requested in by_name:
                return requested, by_name[requested]
            for name, value in key_items:
                if requested == value:
                    return name, value
    return key_items[model_index % len(key_items)]


def ordered_api_key_candidates(
    key_items: Sequence[Tuple[str, str]],
    model: str,
    tier: str,
    model_index: int,
    key_map: Optional[Dict[str, str]] = None,
) -> List[Tuple[str, str]]:
    """Return a failover key order: preferred key first, then every remaining key."""
    if not key_items:
        return []
    preferred_name, preferred_value = choose_api_key(key_items, model, tier, model_index, key_map=key_map)
    ordered: List[Tuple[str, str]] = []
    if preferred_name and preferred_value:
        ordered.append((preferred_name, preferred_value))
    for name, value in key_items:
        if name != preferred_name:
            ordered.append((name, value))
    return ordered


def build_ephone_prompt(item: Dict[str, Any]) -> str:
    option_text = format_options(item.get("options"))
    lines = [
        "请回答下面这道无人机图文评测题。",
        "",
        f"question_format: {question_format_of(item)}",
        f"answer_type: {item.get('answer_type') or 'UNKNOWN'}",
        "",
        "题目：",
        str(item.get("question") or ""),
    ]
    if option_text:
        lines.extend(["", "选项：", option_text])
    lines.extend(
        [
            "",
            "输出要求：",
            "1. 只输出合法 JSON，不要输出 Markdown，不要输出额外解释。",
            "2. JSON 格式固定为：{\"answer\": \"选项字母或最终答案\", \"reason\": \"一句简短依据\"}。",
            "3. 如果题目要求多个选项或排序，answer 可以是数组，例如 [\"A\", \"C\"]。",
            "4. 如果题目要求结构化 JSON，answer 可以是对象或数组。",
        ]
    )
    return "\n".join(lines)


def build_ephone_messages(item: Dict[str, Any], image_url: str, system_prompt: str) -> List[Dict[str, Any]]:
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": build_ephone_prompt(item)},
                {"type": "image_url", "image_url": {"url": image_url, "detail": "high"}},
            ],
        },
    ]


def prediction_from_response_text(response_text: str) -> Any:
    ok, obj = parse_json_maybe(response_text)
    if ok and isinstance(obj, dict):
        for key in ("answer", "prediction", "pred", "output", "response"):
            if key in obj:
                return obj[key]
        return obj
    if ok and isinstance(obj, list):
        return obj
    return response_text


def call_ephone_model(
    item: Dict[str, Any],
    model: str,
    tier: str,
    key_name: str,
    api_key: str,
    endpoint: str,
    system_prompt: str,
    temperature: float,
    max_tokens: int,
    timeout: int,
    retries: int,
    require_vision: bool,
) -> Dict[str, Any]:
    if requests is None:
        raise RuntimeError("Missing dependency: requests. Install it before running infer-ephone.")

    image = str(item.get("image") or "").strip()
    if not image:
        raise ValueError(f"Item {eval_key(item)} has no image field")
    image_url = normalize_image_input(image)
    messages = build_ephone_messages(item, image_url=image_url, system_prompt=system_prompt)
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    retryable_status = {408, 409, 425, 429, 500, 502, 503, 504}
    attempts: List[Dict[str, Any]] = []
    started = time.time()
    last_status: Optional[int] = None
    last_body = ""
    last_json: Optional[Dict[str, Any]] = None
    last_response_text = ""
    last_vision_used: Optional[bool] = None
    last_vision_missing = False

    for attempt in range(retries + 1):
        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
            last_status = resp.status_code
            try:
                parsed = resp.json()
                last_json = parsed if isinstance(parsed, dict) else {"raw_json": parsed}
            except Exception:
                last_json = None
            last_body = resp.text[:4000]
            attempts.append({"attempt": attempt, "status_code": last_status})

            if last_status == 200 and last_json is not None:
                response_text = get_response_text(last_json)
                usage = last_json.get("usage") if isinstance(last_json, dict) else None
                vision_used = usage_shows_vision_input(usage)
                vision_missing = looks_like_no_image_response(response_text)
                last_response_text = response_text
                last_vision_used = vision_used
                last_vision_missing = vision_missing
                if require_vision and (vision_used is False or vision_missing):
                    attempts[-1].update(
                        {
                            "error": "vision_input_not_used",
                            "vision_used": vision_used,
                            "vision_missing_response": vision_missing,
                        }
                    )
                    if attempt < retries:
                        time.sleep(1.5 * (attempt + 1))
                        continue
                    return {
                        "ok": False,
                        "error": "vision_input_not_used",
                        "status_code": last_status,
                        "duration_sec": round(time.time() - started, 4),
                        "response_json": last_json,
                        "response_text": response_text,
                        "prediction": None,
                        "vision_used": vision_used,
                        "vision_missing_response": vision_missing,
                        "attempts": attempts,
                    }
                return {
                    "ok": True,
                    "error": None,
                    "status_code": last_status,
                    "duration_sec": round(time.time() - started, 4),
                    "response_json": last_json,
                    "response_text": response_text,
                    "prediction": prediction_from_response_text(response_text),
                    "vision_used": vision_used,
                    "vision_missing_response": vision_missing,
                    "attempts": attempts,
                }
            if last_status not in retryable_status:
                break
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
        except Exception as exc:
            attempts.append({"attempt": attempt, "status_code": None, "error": repr(exc)})
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
            else:
                return {
                    "ok": False,
                    "error": repr(exc),
                    "status_code": None,
                    "duration_sec": round(time.time() - started, 4),
                    "response_json": None,
                    "response_text": "",
                    "prediction": None,
                    "attempts": attempts,
                }

    return {
        "ok": False,
        "error": last_body or f"HTTP status {last_status}",
        "status_code": last_status,
        "duration_sec": round(time.time() - started, 4),
        "response_json": last_json,
        "response_text": last_response_text or get_response_text(last_json or {}),
        "prediction": None,
        "vision_used": last_vision_used,
        "vision_missing_response": last_vision_missing,
        "attempts": attempts,
    }


def write_csv(path: Path, rows: Sequence[Dict[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def question_format_of(item: Dict[str, Any]) -> str:
    return str(
        item.get("question_format")
        or item.get("answer_format_id")
        or item.get("answer_format")
        or "UNKNOWN"
    )


def eval_key(item: Dict[str, Any]) -> str:
    return str(item.get("eval_id") or item.get("id") or item.get("item_id"))


def strip_gold_fields(item: Dict[str, Any]) -> Dict[str, Any]:
    keep = {
        "eval_id",
        "id",
        "sample_id",
        "image",
        "auxiliary_images",
        "template_id",
        "question_format",
        "capability",
        "question",
        "options",
        "answer_type",
        "scoring",
        "quality_flags",
    }
    out = {k: item.get(k) for k in keep if k in item}
    out["prediction_contract"] = {
        "required_key": "prediction",
        "prediction_id_key": "eval_id",
        "allowed_prediction_shapes": [
            "string",
            "number",
            "array",
            "object for JSON answer formats",
        ],
    }
    return out


def prepare(args: argparse.Namespace) -> None:
    dataset_path = Path(args.dataset).expanduser().resolve()
    items = load_jsonl(dataset_path)
    if not items:
        raise SystemExit(f"Dataset is empty: {dataset_path}")

    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in items:
        groups[question_format_of(item)].append(item)

    rng = random.Random(args.seed)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else (
        DEFAULT_OUT_ROOT / f"run_{timestamp}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    sampled: List[Dict[str, Any]] = []
    group_reports: Dict[str, Dict[str, Any]] = {}
    for qf in sorted(groups):
        pool = list(groups[qf])
        if len(pool) >= args.per_format:
            chosen = rng.sample(pool, args.per_format)
            replacement = False
        else:
            if args.fail_if_short:
                raise SystemExit(
                    f"question_format={qf!r} has only {len(pool)} items, "
                    f"less than requested {args.per_format}"
                )
            chosen = [rng.choice(pool) for _ in range(args.per_format)]
            replacement = True

        original_counts: Counter[str] = Counter()
        for rank, item in enumerate(chosen, 1):
            base_id = str(item.get("id") or item.get("item_id") or f"row_{rank}")
            original_counts[base_id] += 1
            repeat_index = original_counts[base_id]
            new_item = dict(item)
            new_item["eval_id"] = (
                f"{safe_id(qf)}__{rank:03d}__{base_id}"
                if repeat_index == 1
                else f"{safe_id(qf)}__{rank:03d}__{base_id}__repeat{repeat_index}"
            )
            new_item["grey_eval"] = {
                "question_format": qf,
                "rank_in_format": rank,
                "sampled_with_replacement": replacement,
                "source_dataset": str(dataset_path),
                "seed": args.seed,
            }
            sampled.append(new_item)

        group_reports[qf] = {
            "available": len(pool),
            "sampled": len(chosen),
            "sampled_with_replacement": replacement,
            "unique_original_ids": len(set(str(x.get("id") or x.get("item_id")) for x in chosen)),
        }

    gold_path = out_dir / "sampled_gold.jsonl"
    questions_path = out_dir / "questions_for_inference.jsonl"
    pred_template_path = out_dir / "prediction_template.jsonl"
    manifest_path = out_dir / "manifest.json"

    write_jsonl(gold_path, sampled)
    write_jsonl(questions_path, (strip_gold_fields(item) for item in sampled))
    write_jsonl(
        pred_template_path,
        (
            {
                "eval_id": eval_key(item),
                "id": item.get("id"),
                "question_format": question_format_of(item),
                "prediction": None,
            }
            for item in sampled
        ),
    )

    manifest = {
        "dataset": str(dataset_path),
        "out_dir": str(out_dir),
        "per_format": args.per_format,
        "seed": args.seed,
        "total_source_items": len(items),
        "total_eval_instances": len(sampled),
        "question_formats": group_reports,
        "files": {
            "sampled_gold": str(gold_path),
            "questions_for_inference": str(questions_path),
            "prediction_template": str(pred_template_path),
        },
        "prediction_jsonl_contract": {
            "required": ["eval_id", "prediction"],
            "accepted_id_keys": ["eval_id", "id", "item_id"],
            "accepted_prediction_keys": list(PREDICTION_KEYS),
        },
    }
    write_json(manifest_path, manifest)

    print(json.dumps({
        "out_dir": str(out_dir),
        "total_eval_instances": len(sampled),
        "question_formats": group_reports,
    }, ensure_ascii=False, indent=2))


def safe_id(text: str) -> str:
    text = re.sub(r"\s+", "_", text.strip())
    text = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", text)
    return text.strip("_") or "UNKNOWN"


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ",".join(normalize_text(x) for x in value)
    text = str(value)
    text = text.strip()
    text = text.replace("，", ",").replace("；", ";").replace("：", ":")
    text = re.sub(r"\s+", " ", text)
    return text.casefold()


def normalize_choice_text(value: Any) -> str:
    return normalize_text(value).strip(" .。,:;；、()[]{}\"'")


def option_keys(options: Any) -> List[str]:
    if not isinstance(options, dict):
        return []
    return [str(k).upper() for k in options.keys()]


def option_value_to_keys(options: Any) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = defaultdict(list)
    if not isinstance(options, dict):
        return result
    for key, value in options.items():
        result[normalize_choice_text(value)].append(str(key).upper())
    return result


def parse_json_maybe(value: Any) -> Tuple[bool, Any]:
    if isinstance(value, (dict, list)):
        return True, value
    if value is None:
        return False, None
    text = str(value).strip()
    if not text:
        return False, None

    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S | re.I)
    if fence:
        text = fence.group(1).strip()

    decoder = json.JSONDecoder()
    for idx, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            obj, _end = decoder.raw_decode(text[idx:])
            return True, obj
        except json.JSONDecodeError:
            pass
    try:
        return True, json.loads(text)
    except Exception:
        return False, None


def as_sequence(value: Any) -> List[Any]:
    ok, obj = parse_json_maybe(value)
    if ok and isinstance(obj, list):
        return obj
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    text = text.replace("，", ",").replace("；", ",").replace("、", ",")
    return [x.strip() for x in re.split(r"[,;\s]+", text) if x.strip()]


def choice_list(value: Any, options: Any, allow_multi: bool) -> List[str]:
    keys = option_keys(options)
    valid = set(keys)
    if not valid:
        return [normalize_choice_text(x).upper() for x in as_sequence(value) if normalize_choice_text(x)]

    values_to_keys = option_value_to_keys(options)
    found: List[str] = []

    if isinstance(value, (list, tuple, set)):
        chunks = list(value)
    else:
        ok, obj = parse_json_maybe(value)
        chunks = obj if ok and isinstance(obj, list) else [value]

    for chunk in chunks:
        if chunk is None:
            continue
        raw = str(chunk).strip()
        if not raw:
            continue
        raw_norm = normalize_choice_text(raw)
        raw_upper = raw_norm.upper()
        if raw_upper in valid:
            found.append(raw_upper)
            continue
        if raw_norm in values_to_keys:
            found.extend(values_to_keys[raw_norm])
            continue

        # Standalone option letters: A, "选A", "答案: A", "(A)", "A,B"
        candidates = re.findall(r"(?<![A-Za-z0-9])([A-Za-z])(?=[\s,.;:：。)、)\]]|$)", raw)
        if not candidates:
            candidates = re.findall(r"(?:选|答案|answer|option)\s*[:：]?\s*([A-Za-z])", raw, flags=re.I)
        for cand in candidates:
            letter = cand.upper()
            if letter in valid:
                found.append(letter)

        if not found:
            # Last resort for Chinese yes/no style answers.
            yn = yes_no_canonical(raw)
            if yn:
                for key, val in options.items():
                    if yes_no_canonical(val) == yn:
                        found.append(str(key).upper())

    deduped: List[str] = []
    seen = set()
    for key in found:
        if key in valid and key not in seen:
            deduped.append(key)
            seen.add(key)
    return deduped if allow_multi else deduped[:1]


def yes_no_canonical(value: Any) -> Optional[str]:
    text = normalize_choice_text(value)
    yes = {"是", "yes", "y", "true", "正确", "对", "可回答", "支持", "可以"}
    no = {"否", "no", "n", "false", "错误", "不对", "不可回答", "不支持", "不可以"}
    unknown = {"无法确定", "不确定", "unknown", "uncertain"}
    if text in yes:
        return "YES"
    if text in no:
        return "NO"
    if text in unknown:
        return "UNKNOWN"
    return None


def score_exact_choice(item: Dict[str, Any], prediction: Any) -> Tuple[float, Dict[str, Any]]:
    options = item.get("options")
    gold = item.get("answer")
    gold_choices = choice_list(gold, options, allow_multi=False)
    pred_choices = choice_list(prediction, options, allow_multi=False)
    if gold_choices or pred_choices:
        ok = bool(gold_choices and pred_choices and gold_choices[0] == pred_choices[0])
        return float(ok), {"gold_choice": gold_choices[:1], "pred_choice": pred_choices[:1]}

    gold_norm = normalize_choice_text(gold)
    pred_norm = normalize_choice_text(prediction)
    return float(gold_norm == pred_norm), {"gold_norm": gold_norm, "pred_norm": pred_norm}


def score_multi_choice(item: Dict[str, Any], prediction: Any) -> Tuple[float, Dict[str, Any]]:
    options = item.get("options")
    gold_set = set(choice_list(item.get("answer"), options, allow_multi=True))
    pred_set = set(choice_list(prediction, options, allow_multi=True))
    tp = len(gold_set & pred_set)
    precision = tp / len(pred_set) if pred_set else (1.0 if not gold_set else 0.0)
    recall = tp / len(gold_set) if gold_set else (1.0 if not pred_set else 0.0)
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    set_exact = float(gold_set == pred_set)
    return f1, {
        "gold_set": sorted(gold_set),
        "pred_set": sorted(pred_set),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "set_exact": set_exact,
    }


def score_ordered_list(item: Dict[str, Any], prediction: Any) -> Tuple[float, Dict[str, Any]]:
    options = item.get("options")
    gold_order = choice_list(item.get("answer"), options, allow_multi=True)
    pred_order = choice_list(prediction, options, allow_multi=True)
    pred_rank = {key: idx for idx, key in enumerate(pred_order)}
    total = 0
    correct = 0
    missing_pairs = 0
    for i in range(len(gold_order)):
        for j in range(i + 1, len(gold_order)):
            a, b = gold_order[i], gold_order[j]
            total += 1
            if a not in pred_rank or b not in pred_rank:
                missing_pairs += 1
                continue
            if pred_rank[a] < pred_rank[b]:
                correct += 1
    pairwise_accuracy = correct / total if total else float(gold_order == pred_order)
    exact = float(gold_order == pred_order)
    kendall_like = 2 * pairwise_accuracy - 1 if total else exact
    return pairwise_accuracy, {
        "gold_order": gold_order,
        "pred_order": pred_order,
        "pairwise_accuracy": pairwise_accuracy,
        "kendall_like": kendall_like,
        "exact": exact,
        "missing_pairs": missing_pairs,
        "total_pairs": total,
    }


def as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value)
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else None


def score_number(item: Dict[str, Any], prediction: Any) -> Tuple[float, Dict[str, Any]]:
    gold = as_float(item.get("answer"))
    pred = as_float(prediction)
    if gold is None or pred is None:
        return 0.0, {"error": "non_numeric", "gold": item.get("answer"), "prediction": prediction}
    absolute_error = abs(gold - pred)
    score = float(absolute_error == 0)
    return score, {"gold": gold, "prediction": pred, "absolute_error": absolute_error}


def score_text(item: Dict[str, Any], prediction: Any) -> Tuple[float, Dict[str, Any]]:
    gold_norm = normalize_choice_text(item.get("answer"))
    pred_norm = normalize_choice_text(prediction)
    return float(gold_norm == pred_norm), {"gold_norm": gold_norm, "pred_norm": pred_norm}


def leaf_equal_score(gold: Any, pred: Any) -> float:
    if isinstance(gold, (int, float)) and not isinstance(gold, bool):
        pred_num = as_float(pred)
        return float(pred_num is not None and abs(float(gold) - pred_num) == 0)
    if isinstance(gold, list):
        return set_f1({normalize_choice_text(x) for x in gold}, {normalize_choice_text(x) for x in as_sequence(pred)})
    if isinstance(gold, dict) and isinstance(pred, dict):
        if not gold:
            return float(not pred)
        return sum(leaf_equal_score(v, pred.get(k)) for k, v in gold.items()) / len(gold)
    return float(normalize_choice_text(gold) == normalize_choice_text(pred))


def set_f1(gold_set: set, pred_set: set) -> float:
    gold_set = {x for x in gold_set if x != ""}
    pred_set = {x for x in pred_set if x != ""}
    if not gold_set and not pred_set:
        return 1.0
    if not gold_set or not pred_set:
        return 0.0
    tp = len(gold_set & pred_set)
    precision = tp / len(pred_set) if pred_set else 0.0
    recall = tp / len(gold_set) if gold_set else 0.0
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def score_json_answer(item: Dict[str, Any], prediction: Any) -> Tuple[float, Dict[str, Any]]:
    gold = item.get("answer")
    ok, pred = parse_json_maybe(prediction)
    if isinstance(gold, dict):
        if not ok or not isinstance(pred, dict):
            return 0.0, {"schema_ok": False, "expected": "object"}
        if not gold:
            field_accuracy = float(not pred)
        else:
            field_scores = {str(k): leaf_equal_score(v, pred.get(k)) for k, v in gold.items()}
            field_accuracy = sum(field_scores.values()) / len(field_scores)
        return field_accuracy, {
            "schema_ok": True,
            "field_accuracy": field_accuracy,
            "gold_keys": sorted(str(k) for k in gold.keys()),
            "pred_keys": sorted(str(k) for k in pred.keys()),
        }
    if isinstance(gold, list):
        if not ok or not isinstance(pred, list):
            return 0.0, {"schema_ok": False, "expected": "array"}
        gold_norm = {normalize_choice_text(x) for x in gold}
        pred_norm = {normalize_choice_text(x) for x in pred}
        f1 = set_f1(gold_norm, pred_norm)
        exact = float([normalize_choice_text(x) for x in gold] == [normalize_choice_text(x) for x in pred])
        return f1, {"schema_ok": True, "f1": f1, "exact_ordered": exact}
    return score_text(item, prediction)


def score_item(item: Dict[str, Any], prediction: Any) -> Tuple[float, Dict[str, Any]]:
    answer_type = str(item.get("answer_type") or "").lower()
    qf = question_format_of(item)

    if answer_type == "multi_choice" or qf.startswith("F2"):
        return score_multi_choice(item, prediction)
    if answer_type == "ordered_list" or qf.startswith("F5") or qf.startswith("F19"):
        return score_ordered_list(item, prediction)
    if answer_type == "number" or qf.startswith("F8"):
        return score_number(item, prediction)
    if answer_type in {"json", "json_array"} or qf.startswith(("F6", "F24")):
        return score_json_answer(item, prediction)
    if answer_type == "text" or qf.startswith("F7"):
        return score_text(item, prediction)
    return score_exact_choice(item, prediction)


def load_predictions(path: Path) -> Dict[str, Any]:
    predictions: Dict[str, Any] = {}
    for row in load_jsonl(path):
        key = row.get("eval_id") or row.get("id") or row.get("item_id")
        if key is None:
            raise ValueError(f"Prediction row missing eval_id/id/item_id: {row}")
        pred_value = None
        found = False
        for pred_key in PREDICTION_KEYS:
            if pred_key in row:
                pred_value = row[pred_key]
                found = True
                break
        if not found:
            raise ValueError(f"Prediction row missing prediction field: {row}")
        predictions[str(key)] = pred_value
    return predictions


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize(values: Sequence[float]) -> Dict[str, Any]:
    if not values:
        return {"n": 0, "mean_score": 0.0}
    return {
        "n": len(values),
        "mean_score": mean(values),
        "median_score": statistics.median(values),
        "min_score": min(values),
        "max_score": max(values),
    }


def score(args: argparse.Namespace) -> None:
    gold_path = Path(args.gold).expanduser().resolve()
    pred_path = Path(args.pred).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else pred_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    gold_items = load_jsonl(gold_path)
    predictions = load_predictions(pred_path)

    item_reports: List[Dict[str, Any]] = []
    missing: List[str] = []
    by_qf: Dict[str, List[float]] = defaultdict(list)
    by_template: Dict[str, List[float]] = defaultdict(list)
    by_answer_type: Dict[str, List[float]] = defaultdict(list)

    for item in gold_items:
        key = eval_key(item)
        pred = predictions.get(key)
        if key not in predictions:
            fallback_key = str(item.get("id") or item.get("item_id") or "")
            pred = predictions.get(fallback_key)
        if pred is None and key not in predictions:
            missing.append(key)
        score_value, detail = score_item(item, pred)
        qf = question_format_of(item)
        template_id = str(item.get("template_id") or "UNKNOWN")
        answer_type = str(item.get("answer_type") or "UNKNOWN")
        by_qf[qf].append(score_value)
        by_template[template_id].append(score_value)
        by_answer_type[answer_type].append(score_value)
        item_reports.append(
            {
                "eval_id": key,
                "id": item.get("id"),
                "question_format": qf,
                "template_id": template_id,
                "answer_type": answer_type,
                "score": score_value,
                "gold_answer": item.get("answer"),
                "prediction": pred,
                "detail": detail,
            }
        )

    summary = {
        "gold": str(gold_path),
        "pred": str(pred_path),
        "overall": {
            **summarize([x["score"] for x in item_reports]),
            "missing_predictions": len(missing),
            "missing_eval_ids": missing[:200],
        },
        "by_question_format": {k: summarize(v) for k, v in sorted(by_qf.items())},
        "by_template_id": {k: summarize(v) for k, v in sorted(by_template.items())},
        "by_answer_type": {k: summarize(v) for k, v in sorted(by_answer_type.items())},
        "prediction_contract": {
            "accepted_id_keys": ["eval_id", "id", "item_id"],
            "accepted_prediction_keys": list(PREDICTION_KEYS),
        },
    }

    summary_path = out_dir / args.summary_name
    items_path = out_dir / args.items_name
    write_json(summary_path, summary)
    write_jsonl(items_path, item_reports)
    print(json.dumps(summary["overall"], ensure_ascii=False, indent=2))
    print(f"[written] summary: {summary_path}")
    print(f"[written] per-item: {items_path}")


def infer_ephone_task(
    args: argparse.Namespace,
    item: Dict[str, Any],
    out_dir: Path,
    raw_root: Path,
    model_entry: Dict[str, Any],
    task_index: int,
    key_items: Sequence[Tuple[str, str]],
    key_map: Optional[Dict[str, str]],
    semaphores: Dict[str, threading.Semaphore],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    tier = str(model_entry["tier"])
    model = str(model_entry["model"])
    api_model = str(model_entry.get("api_model") or model)
    endpoint = str(model_entry.get("endpoint") or args.endpoint)
    safe_model = safe_id(model)
    item_key = eval_key(item)
    qf = question_format_of(item)
    raw_model_dir = raw_root / safe_model
    raw_path = raw_model_dir / f"{safe_id(item_key)}.json"
    model_key_items = model_entry.get("key_items") or key_items
    key_candidates = ordered_api_key_candidates(model_key_items, model, tier, task_index, key_map=key_map)
    key_name = key_candidates[0][0] if key_candidates else None

    loaded_existing_raw = False
    if args.resume and raw_path.exists():
        try:
            raw_record = json.loads(raw_path.read_text(encoding="utf-8"))
            loaded_existing_raw = True
        except Exception as exc:
            raw_record = {
                "ok": False,
                "error": f"failed_to_read_existing_raw: {repr(exc)}",
                "prediction": None,
            }
        if (
            loaded_existing_raw
            and not args.reuse_failed_raw
            and args.require_vision
            and not raw_has_usable_vision(raw_record)
        ):
            raw_record = {
                "ok": False,
                "error": "stale_raw_without_usable_vision",
                "prediction": None,
            }
    else:
        raw_record = {
            "ok": False,
            "error": "missing_raw_result",
            "prediction": None,
        }

    if loaded_existing_raw and args.reuse_failed_raw:
        needs_call = False
    else:
        needs_call = (
            not raw_has_usable_vision(raw_record)
            if args.require_vision
            else raw_record.get("ok") is not True
        )
    if needs_call:
        if not key_candidates and not args.dry_run:
            raw_record = {
                "ok": False,
                "error": f"no_usable_api_key_for_model:{model}",
                "prediction": None,
                "status_code": None,
                "response_json": None,
                "response_text": "",
                "vision_used": None,
                "vision_missing_response": False,
                "attempts": [],
            }
        else:
            raw_model_dir.mkdir(parents=True, exist_ok=True)
            call_failures: List[Dict[str, Any]] = []
            raw_record = {}
            candidates_to_try = key_candidates[:1] if args.dry_run else key_candidates
            for candidate_key_name, candidate_api_key in candidates_to_try:
                base_record = {
                    "eval_id": item_key,
                    "id": item.get("id"),
                    "question_format": qf,
                    "answer_type": item.get("answer_type"),
                    "model": model,
                    "api_model": api_model,
                    "tier": tier,
                    "provider_id": model_entry.get("provider_id"),
                    "key_name": candidate_key_name,
                    "endpoint": endpoint,
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "key_failover_order": [name for name, _value in key_candidates],
                    "request": {
                        "image": item.get("image"),
                        "image_file": image_file_metadata(item.get("image")),
                        "question": item.get("question"),
                        "options": item.get("options"),
                        "temperature": args.temperature,
                        "max_tokens": args.max_tokens,
                        "require_vision": args.require_vision,
                        "system_prompt": args.system_prompt,
                        "user_prompt": build_ephone_prompt(item),
                    },
                }
                if args.dry_run:
                    call_result = {
                        "ok": False,
                        "error": "dry_run_no_api_call",
                        "status_code": None,
                        "duration_sec": 0.0,
                        "response_json": None,
                        "response_text": "",
                        "prediction": None,
                        "vision_used": None,
                        "vision_missing_response": False,
                        "attempts": [],
                    }
                else:
                    try:
                        semaphore = semaphores[str(candidate_key_name)]
                        with semaphore:
                            call_result = call_ephone_model(
                                item=item,
                                model=api_model,
                                tier=tier,
                                key_name=str(candidate_key_name),
                                api_key=str(candidate_api_key),
                                endpoint=endpoint,
                                system_prompt=args.system_prompt,
                                temperature=args.temperature,
                                max_tokens=args.max_tokens,
                                timeout=args.timeout,
                                retries=args.retries,
                                require_vision=args.require_vision,
                            )
                    except Exception as exc:
                        call_result = {
                            "ok": False,
                            "error": repr(exc),
                            "status_code": None,
                            "duration_sec": 0.0,
                            "response_json": None,
                            "response_text": "",
                            "prediction": None,
                            "vision_used": None,
                            "vision_missing_response": False,
                            "attempts": [],
                        }
                raw_record = {**base_record, **call_result}
                if raw_has_usable_vision(raw_record) if args.require_vision else raw_record.get("ok") is True:
                    break
                call_failures.append(
                    {
                        "key_name": candidate_key_name,
                        "ok": raw_record.get("ok"),
                        "status_code": raw_record.get("status_code"),
                        "error": raw_record.get("error"),
                        "vision_used": raw_record.get("vision_used"),
                        "vision_missing_response": raw_record.get("vision_missing_response"),
                    }
                )
            if not (raw_has_usable_vision(raw_record) if args.require_vision else raw_record.get("ok") is True):
                raw_record["error"] = "all_api_keys_failed"
            raw_record["key_failures"] = call_failures
            write_json(raw_path, raw_record)

    prediction = raw_record.get("prediction")
    score_value, detail = score_item(item, prediction)
    ok = bool(raw_record.get("ok"))
    error = raw_record.get("error")
    raw_rel = str(raw_path.relative_to(out_dir)) if raw_path.is_relative_to(out_dir) else str(raw_path)
    prediction_row = {
        "eval_id": item_key,
        "id": item.get("id"),
        "question_format": qf,
        "model": model,
        "api_model": api_model,
        "tier": tier,
        "prediction": prediction,
        "ok": ok,
        "error": error,
        "raw_result_path": raw_rel,
    }
    score_row = {
        "eval_id": item_key,
        "id": item.get("id"),
        "question_format": qf,
        "template_id": item.get("template_id"),
        "answer_type": item.get("answer_type"),
        "model": model,
        "api_model": api_model,
        "tier": tier,
        "score": score_value,
        "ok": ok,
        "error": error,
        "gold_answer": item.get("answer"),
        "prediction": prediction,
        "detail": detail,
        "raw_result_path": raw_rel,
    }
    return prediction_row, score_row


def record_ephone_result(
    prediction_row: Dict[str, Any],
    score_row: Dict[str, Any],
    prediction_rows_by_model: Dict[Tuple[str, str], List[Dict[str, Any]]],
    score_rows_by_model: Dict[Tuple[str, str], List[Dict[str, Any]]],
    aggregate_scores: Dict[Tuple[str, str, str], List[float]],
    aggregate_errors: Counter[Tuple[str, str, str]],
    model_overall: Dict[Tuple[str, str], List[float]],
    model_errors: Counter[Tuple[str, str]],
) -> None:
    tier = str(score_row["tier"])
    model = str(score_row["model"])
    qf = str(score_row["question_format"])
    model_key = (tier, model)
    prediction_rows_by_model[model_key].append(prediction_row)
    score_rows_by_model[model_key].append(score_row)

    score_value = float(score_row["score"])
    aggregate_scores[(tier, model, qf)].append(score_value)
    model_overall[model_key].append(score_value)
    if not score_row["ok"]:
        aggregate_errors[(tier, model, qf)] += 1
        model_errors[model_key] += 1


def write_ephone_outputs(
    out_dir: Path,
    pred_dir: Path,
    score_dir: Path,
    model_plan: Sequence[Dict[str, Any]],
    item_order: Dict[str, int],
    prediction_rows_by_model: Dict[Tuple[str, str], List[Dict[str, Any]]],
    score_rows_by_model: Dict[Tuple[str, str], List[Dict[str, Any]]],
    aggregate_scores: Dict[Tuple[str, str, str], List[float]],
    aggregate_errors: Counter[Tuple[str, str, str]],
    model_overall: Dict[Tuple[str, str], List[float]],
    model_errors: Counter[Tuple[str, str]],
) -> None:
    for model_entry in model_plan:
        tier = str(model_entry["tier"])
        model = str(model_entry["model"])
        safe_model = safe_id(model)
        model_key = (tier, model)
        prediction_rows = sorted(
            prediction_rows_by_model.get(model_key, []),
            key=lambda row: item_order.get(str(row.get("eval_id")), 10**12),
        )
        score_rows = sorted(
            score_rows_by_model.get(model_key, []),
            key=lambda row: item_order.get(str(row.get("eval_id")), 10**12),
        )

        pred_path = pred_dir / f"{safe_model}.jsonl"
        score_path = score_dir / f"{safe_model}_score_items.jsonl"
        summary_path = score_dir / f"{safe_model}_score_summary.json"
        write_jsonl(pred_path, prediction_rows)
        write_jsonl(score_path, score_rows)
        write_json(
            summary_path,
            {
                "model": model,
                "tier": tier,
                "prediction_file": str(pred_path),
                "score_items_file": str(score_path),
                "overall": {
                    **summarize([row["score"] for row in score_rows]),
                    "errors": sum(1 for row in score_rows if not row["ok"]),
                },
                "by_question_format": {
                    qf: {
                        **summarize([row["score"] for row in rows]),
                        "errors": sum(1 for row in rows if not row["ok"]),
                    }
                    for qf, rows in sorted(group_rows(score_rows, "question_format").items())
                },
            },
        )

    table_rows: List[Dict[str, Any]] = []
    for (tier, model, qf), values in sorted(aggregate_scores.items()):
        summary = summarize(values)
        table_rows.append(
            {
                "tier": tier,
                "model": model,
                "question_format": qf,
                **summary,
                "errors": aggregate_errors[(tier, model, qf)],
            }
        )

    overall_rows: List[Dict[str, Any]] = []
    for (tier, model), values in sorted(model_overall.items()):
        overall_rows.append(
            {
                "tier": tier,
                "model": model,
                **summarize(values),
                "errors": model_errors[(tier, model)],
            }
        )

    table_fields = [
        "tier",
        "model",
        "question_format",
        "n",
        "mean_score",
        "median_score",
        "min_score",
        "max_score",
        "errors",
    ]
    overall_fields = ["tier", "model", "n", "mean_score", "median_score", "min_score", "max_score", "errors"]
    write_csv(out_dir / "model_question_format_scores.csv", table_rows, table_fields)
    write_csv(out_dir / "model_overall_scores.csv", overall_rows, overall_fields)
    write_json(out_dir / "model_question_format_scores.json", {"rows": table_rows})
    write_json(out_dir / "model_overall_scores.json", {"rows": overall_rows})


def infer_ephone(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    if not is_opencode_model_config(config):
        raise SystemExit(
            "infer-ephone requires BENCHCLAW_ROOT/modelNeedMeasured/model_config.json "
            "or another config with the same opencode-style provider/grey_test/full_test schema."
        )

    model_plan: List[Dict[str, Any]]
    selected_tiers: List[str]
    models_filter = csv_or_list(args.models) if args.models else None
    model_plan, model_groups = build_plan_from_opencode_config(
        config,
        test_group=args.test_group,
        models_filter=models_filter,
    )
    global DEFAULT_MODEL_GROUPS
    DEFAULT_MODEL_GROUPS = model_groups
    selected_tiers = [args.test_group]

    args.endpoint = pick_config_value(args, config, "endpoint", default=DEFAULT_ENDPOINT)
    args.api_keys = pick_config_value(args, config, "api_keys", default="")
    args.model_key_map = pick_config_value(args, config, "model_key_map", default="")
    args.temperature = infer_setting(args, config, "temperature", 0.0)
    args.max_tokens = infer_setting(args, config, "max_tokens", 512)
    args.timeout = infer_setting(args, config, "timeout", 120)
    args.retries = infer_setting(args, config, "retries", 2)
    args.system_prompt = pick_config_value(args, config, "system_prompt", default=DEFAULT_SYSTEM_PROMPT)
    args.parallel_per_key = infer_setting(args, config, "parallel_per_key", 2)
    args.progress_every = infer_setting(args, config, "progress_every", 50)
    args.flush_every = infer_setting(args, config, "flush_every", 50)
    args.max_pending = infer_setting(args, config, "max_pending", 0)

    gold_path = Path(args.gold).expanduser().resolve()
    gold_items = load_jsonl(gold_path)
    if not gold_items:
        raise SystemExit(f"Gold file is empty: {gold_path}")

    if args.max_models:
        model_plan = model_plan[: args.max_models]
    if not model_plan:
        raise SystemExit("No models selected for infer-ephone.")

    items = gold_items[: args.max_items] if args.max_items else gold_items
    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else (
        gold_path.parent / f"ephone_eval_{time.strftime('%Y%m%d_%H%M%S')}"
    )
    raw_root = out_dir / "raw_inference"
    pred_dir = out_dir / "predictions"
    score_dir = out_dir / "scores"
    out_dir.mkdir(parents=True, exist_ok=True)

    api_keys_arg = args.api_keys if isinstance(args.api_keys, (dict, list)) else load_json_arg(args.api_keys, default=None)
    api_keys = api_keys_arg if api_keys_arg is not None else read_api_keys_from_env()
    key_items = normalize_api_keys(api_keys)
    any_model_keys = any(entry.get("key_items") for entry in model_plan)
    if not key_items and not any_model_keys and not args.dry_run:
        raise SystemExit(
            "No API key found. Provide provider.options.apiKey in model_config.json, set the referenced "
            "environment variable, or pass --api-keys as JSON."
        )

    key_map = (
        args.model_key_map
        if isinstance(args.model_key_map, dict)
        else load_json_arg(args.model_key_map, default=None)
    )
    if key_map is not None and not isinstance(key_map, dict):
        raise SystemExit("--model-key-map must be a JSON object.")

    aggregate_scores: Dict[Tuple[str, str, str], List[float]] = defaultdict(list)
    aggregate_errors: Counter[Tuple[str, str, str]] = Counter()
    model_overall: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    model_errors: Counter[Tuple[str, str]] = Counter()

    manifest = {
        "gold": str(gold_path),
        "out_dir": str(out_dir),
        "endpoint": args.endpoint,
        "api_key_slots": list(DEFAULT_API_KEY_SLOTS.keys()),
        "api_key_env_names": list(DEFAULT_API_KEY_ENV_NAMES),
        "selected_items": len(items),
        "selected_tiers": selected_tiers,
        "selected_test_group": args.test_group if is_opencode_model_config(config) else None,
        "selected_models": model_plan,
        "model_groups": DEFAULT_MODEL_GROUPS,
        "note": (
            "sample_ratio values are preserved from the supplier script for tier metadata; "
            "infer-ephone evaluates every selected item for every selected model."
        ),
        "require_vision": args.require_vision,
        "parallel_per_key": args.parallel_per_key,
        "max_workers": (len(key_items) or 1) * args.parallel_per_key,
        "max_pending": args.max_pending,
        "flush_every": args.flush_every,
        "resume_policy": (
            "With --resume, raw records are normally reused only when ok=true and, if --require-vision "
            "is enabled, the prior result does not look like a text-only/no-image response. "
            "With --reuse-failed-raw, any readable existing raw record is reused and scored as-is."
        ),
        "reuse_failed_raw": args.reuse_failed_raw,
        "files": {
            "raw_inference": str(raw_root),
            "predictions": str(pred_dir),
            "scores": str(score_dir),
        },
    }
    write_json(out_dir / "manifest.json", manifest)

    total_calls = len(model_plan) * len(items)
    completed = 0
    print(json.dumps({
        "out_dir": str(out_dir),
        "models": [entry["model"] for entry in model_plan],
        "items": len(items),
        "planned_model_item_results": total_calls,
        "dry_run": args.dry_run,
        "parallel_per_key": args.parallel_per_key,
        "max_workers": (len(key_items) or 1) * args.parallel_per_key,
        "max_pending": args.max_pending,
        "flush_every": args.flush_every,
        "reuse_failed_raw": args.reuse_failed_raw,
        "key_slots": sorted(
            {
                name
                for entry in model_plan
                for name, _value in (entry.get("key_items") or key_items)
            }
        ),
    }, ensure_ascii=False, indent=2))

    all_key_names = sorted(
        {
            name
            for entry in model_plan
            for name, _value in (entry.get("key_items") or key_items)
        }
    )
    max_workers = max(1, (max(len(all_key_names), 1)) * max(args.parallel_per_key, 1))
    max_pending = max(max_workers, args.max_pending or max_workers * 4)
    semaphores = {name: threading.Semaphore(max(args.parallel_per_key, 1)) for name in all_key_names}
    item_order = {eval_key(item): idx for idx, item in enumerate(items)}
    prediction_rows_by_model: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    score_rows_by_model: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    task_specs: List[Tuple[int, Dict[str, Any], Dict[str, Any]]] = []
    task_index = 0
    for model_entry in model_plan:
        for item in items:
            task_specs.append((task_index, model_entry, item))
            task_index += 1

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    pending: set[concurrent.futures.Future[Tuple[Dict[str, Any], Dict[str, Any]]]] = set()
    task_iter = iter(task_specs)

    def submit_until_pending_limit() -> None:
        while len(pending) < max_pending:
            try:
                next_task_index, next_model_entry, next_item = next(task_iter)
            except StopIteration:
                return
            pending.add(
                executor.submit(
                    infer_ephone_task,
                    args,
                    next_item,
                    out_dir,
                    raw_root,
                    next_model_entry,
                    next_task_index,
                    key_items,
                    key_map,
                    semaphores,
                )
            )

    try:
        submit_until_pending_limit()
        while pending:
            done, pending = concurrent.futures.wait(
                pending,
                timeout=1.0,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            if not done:
                continue
            for future in done:
                prediction_row, score_row = future.result()
                record_ephone_result(
                    prediction_row,
                    score_row,
                    prediction_rows_by_model,
                    score_rows_by_model,
                    aggregate_scores,
                    aggregate_errors,
                    model_overall,
                    model_errors,
                )

                completed += 1
                if args.progress_every and completed % args.progress_every == 0:
                    print(f"[progress] {completed}/{total_calls} model-item results")
                if args.flush_every and completed % args.flush_every == 0:
                    write_ephone_outputs(
                        out_dir,
                        pred_dir,
                        score_dir,
                        model_plan,
                        item_order,
                        prediction_rows_by_model,
                        score_rows_by_model,
                        aggregate_scores,
                        aggregate_errors,
                        model_overall,
                        model_errors,
                    )
            submit_until_pending_limit()
    except KeyboardInterrupt:
        print(
            f"\n[interrupted] writing {completed}/{total_calls} completed model-item results before exit...",
            file=sys.stderr,
        )
        executor.shutdown(wait=False, cancel_futures=True)
        write_ephone_outputs(
            out_dir,
            pred_dir,
            score_dir,
            model_plan,
            item_order,
            prediction_rows_by_model,
            score_rows_by_model,
            aggregate_scores,
            aggregate_errors,
            model_overall,
            model_errors,
        )
        print(
            f"[interrupted] partial tables written under {out_dir}. Resume with --resume.",
            file=sys.stderr,
        )
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(130)
    except Exception:
        executor.shutdown(wait=False, cancel_futures=True)
        write_ephone_outputs(
            out_dir,
            pred_dir,
            score_dir,
            model_plan,
            item_order,
            prediction_rows_by_model,
            score_rows_by_model,
            aggregate_scores,
            aggregate_errors,
            model_overall,
            model_errors,
        )
        raise
    else:
        executor.shutdown(wait=True)

    write_ephone_outputs(
        out_dir,
        pred_dir,
        score_dir,
        model_plan,
        item_order,
        prediction_rows_by_model,
        score_rows_by_model,
        aggregate_scores,
        aggregate_errors,
        model_overall,
        model_errors,
    )

    print(f"[written] raw inference: {raw_root}")
    print(f"[written] predictions: {pred_dir}")
    print(f"[written] scores: {score_dir}")
    print(f"[written] model-question_format table: {out_dir / 'model_question_format_scores.csv'}")

    return


def group_rows(rows: Sequence[Dict[str, Any]], key: str) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "UNKNOWN")].append(row)
    return grouped


def oracle_predictions(args: argparse.Namespace) -> None:
    gold_path = Path(args.gold).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    rows = []
    for item in load_jsonl(gold_path):
        rows.append(
            {
                "eval_id": eval_key(item),
                "id": item.get("id"),
                "prediction": item.get("answer"),
            }
        )
    write_jsonl(out_path, rows)
    print(f"[written] oracle predictions: {out_path}")


def infer_placeholder(_args: argparse.Namespace) -> None:
    raise SystemExit(
        "Use mode=infer-ephone for API-supplier multimodal inference, or write "
        "predictions as JSONL with {eval_id, prediction} and run mode=score."
    )



def mandatory_proxy_eval(args: argparse.Namespace) -> None:
    """Always-available grey evaluation mode.

    It creates a non-empty score matrix using deterministic/proxy responders when
    external model inference is not configured. This validates scorer, item
    schema, answer parsing, image paths, and gives CDM/IRT a matrix. It is not a
    real model leaderboard.
    """
    gold_path = Path(args.gold).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    rows = load_jsonl(gold_path)
    if not rows:
        raise SystemExit(f"No gold rows for mandatory proxy eval: {gold_path}")
    out_dir.mkdir(parents=True, exist_ok=True)
    proxy_models = ["proxy_oracle", "proxy_biased_first", "proxy_random_seeded", "proxy_wrong_choice"]
    pred_rows = []
    score_rows = []
    rng = random.Random(args.seed)
    for item in rows:
        options = item.get("options") if isinstance(item.get("options"), dict) else {}
        keys = list(options.keys()) or ["A", "B", "C", "D"]
        gold = item.get("answer")
        item_id = eval_key(item)
        for model in proxy_models:
            if model == "proxy_oracle":
                pred = gold
            elif model == "proxy_biased_first":
                pred = keys[0]
            elif model == "proxy_random_seeded":
                pred = rng.choice(keys)
            else:
                pred = next((k for k in keys if str(k).upper() != str(gold).upper()), "__wrong__")
            score_value, detail = score_item(item, pred)
            qf = question_format_of(item)
            diff = str(item.get("difficulty_level") or (item.get("metadata") or {}).get("difficulty_level") or "unknown")
            pred_rows.append({"model": model, "item_id": item_id, "prediction": pred, "evaluation_mode": "proxy"})
            score_rows.append({
                "model": model,
                "item_id": item_id,
                "eval_id": item_id,
                "template_id": item.get("template_id"),
                "question_format": qf,
                "difficulty_level": diff,
                "score": float(score_value),
                "max_score": 1.0,
                "ok": bool(score_value >= 1.0),
                "evaluation_mode": "proxy",
                "detail": detail,
            })
    write_jsonl(out_dir/"predictions.jsonl", pred_rows)
    write_jsonl(out_dir/"score_items.jsonl", score_rows)
    write_jsonl(out_dir/"score_matrix.jsonl", score_rows)
    by_model = group_rows(score_rows, "model")
    fields = ["model", "n", "mean_score", "evaluation_mode"]
    with (out_dir/"model_overall_scores.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for model, group in sorted(by_model.items()):
            w.writerow({"model": model, "n": len(group), "mean_score": sum(float(r["score"]) for r in group)/len(group), "evaluation_mode": "proxy"})
    qf_fields = ["model", "question_format", "difficulty_level", "n", "mean_score", "evaluation_mode"]
    with (out_dir/"model_question_format_scores.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=qf_fields); w.writeheader()
        grouped = defaultdict(list)
        for row in score_rows:
            grouped[(row["model"], row["question_format"], row["difficulty_level"])].append(row)
        for (model,qf,diff), group in sorted(grouped.items()):
            w.writerow({"model": model, "question_format": qf, "difficulty_level": diff, "n": len(group), "mean_score": sum(float(r["score"]) for r in group)/len(group), "evaluation_mode": "proxy"})
    status = {"status": "PASS", "evaluation_mode": "proxy", "reason": "external_models_not_required_for_stage4_gate", "n_items": len(rows), "n_score_records": len(score_rows), "note": "Proxy responders validate the grey gate and CDM/IRT matrix; they are not a real model leaderboard."}
    write_json(out_dir/"status.json", status)
    print(json.dumps(status, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare, infer, and score grey small-batch evaluation sets."
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    p_prepare = sub.add_parser("prepare", help="Sample 100 instances per question_format.")
    p_prepare.add_argument("--dataset", default=str(DEFAULT_DATASET))
    p_prepare.add_argument("--out-dir", default="")
    p_prepare.add_argument("--per-format", type=int, default=DEFAULT_PER_FORMAT)
    p_prepare.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p_prepare.add_argument(
        "--fail-if-short",
        action="store_true",
        help="Fail instead of sampling with replacement when a format has fewer than per-format items.",
    )
    p_prepare.set_defaults(func=prepare)

    p_score = sub.add_parser("score", help="Score a predictions JSONL file.")
    p_score.add_argument("--gold", required=True, help="Usually sampled_gold.jsonl from prepare mode.")
    p_score.add_argument("--pred", required=True, help="JSONL with eval_id and prediction.")
    p_score.add_argument("--out-dir", default="")
    p_score.add_argument("--summary-name", default="score_summary.json")
    p_score.add_argument("--items-name", default="score_items.jsonl")
    p_score.set_defaults(func=score)

    p_oracle = sub.add_parser("oracle-predictions", help="Create perfect predictions for scorer smoke test.")
    p_oracle.add_argument("--gold", required=True)
    p_oracle.add_argument("--out", required=True)
    p_oracle.set_defaults(func=oracle_predictions)

    p_ephone = sub.add_parser(
        "infer-ephone",
        help="Run OpenAI-compatible multimodal API inference, score every result, and aggregate model-format tables.",
    )
    p_ephone.add_argument("--gold", required=True, help="sampled_gold.jsonl from prepare mode.")
    p_ephone.add_argument("--out-dir", default="", help="Output directory for raw results, scores, and tables.")
    p_ephone.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="JSON config path. Must use the modelNeedMeasured opencode-style config schema.",
    )
    p_ephone.add_argument(
        "--test-group",
        default="grey_test",
        choices=["grey_test", "full_test"],
        help="When using modelNeedMeasured/model_config.json, select which configured model group to run.",
    )
    p_ephone.add_argument("--endpoint", default="")
    p_ephone.add_argument(
        "--api-keys",
        default="",
        help='Optional JSON string/file with empty-slot names, e.g. {"key1":"...","key2":"...","key3":"..."}. '
        "Defaults to config.api_keys, then EPHONE_KEY_1/2/3.",
    )
    p_ephone.add_argument(
        "--model-key-map",
        default="",
        help='Optional JSON object mapping model/tier/* to key name, e.g. {"cheap":"key1","strong":"key3"}.',
    )
    p_ephone.add_argument(
        "--tiers",
        default="",
        help="Deprecated no-op for old configs. Keep empty when using modelNeedMeasured config.",
    )
    p_ephone.add_argument(
        "--models",
        default="",
        help="Optional comma-separated model allowlist. In opencode config, values must match provider/model refs.",
    )
    p_ephone.add_argument("--max-items", type=int, default=0, help="Debug limit on gold rows; 0 means all.")
    p_ephone.add_argument("--max-models", type=int, default=0, help="Debug limit on selected models; 0 means all.")
    p_ephone.add_argument("--temperature", type=float, default=None)
    p_ephone.add_argument("--max-tokens", type=int, default=None)
    p_ephone.add_argument("--timeout", type=int, default=None)
    p_ephone.add_argument("--retries", type=int, default=None)
    p_ephone.add_argument("--system-prompt", default="")
    p_ephone.add_argument("--parallel-per-key", type=int, default=None, help="Concurrent requests allowed per API key.")
    p_ephone.add_argument(
        "--require-vision",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require evidence that the API actually used image input; enabled by default.",
    )
    p_ephone.add_argument("--resume", action="store_true", help="Reuse existing raw result JSON files.")
    p_ephone.add_argument(
        "--reuse-failed-raw",
        action="store_true",
        help=(
            "When used with --resume, reuse any readable raw result, including failed/no-vision records, "
            "and score it as-is instead of retrying the API call."
        ),
    )
    p_ephone.add_argument("--dry-run", action="store_true", help="Create scored placeholder outputs without API calls.")
    p_ephone.add_argument("--progress-every", type=int, default=None)
    p_ephone.add_argument(
        "--flush-every",
        type=int,
        default=None,
        help="Rewrite prediction/score tables after this many completed model-item results; 0 disables periodic flush.",
    )
    p_ephone.add_argument(
        "--max-pending",
        type=int,
        default=None,
        help="Maximum submitted-but-unfinished futures; 0 uses four batches of max_workers.",
    )
    p_ephone.set_defaults(func=infer_ephone)

    p_proxy = sub.add_parser("mandatory-proxy-eval", help="Mandatory grey eval with deterministic/proxy responders.")
    p_proxy.add_argument("--gold", required=True)
    p_proxy.add_argument("--out-dir", required=True)
    p_proxy.add_argument("--seed", type=int, default=20260624)
    p_proxy.set_defaults(func=mandatory_proxy_eval)

    p_infer = sub.add_parser("infer-placeholder", help="Compatibility placeholder; use infer-ephone.")
    p_infer.set_defaults(func=infer_placeholder)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
