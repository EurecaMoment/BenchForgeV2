#!/usr/bin/env python3
"""Base template for generated grey-batch metric evaluators.

This file is intentionally a parent/base template. Stage4 metric-compilation
should generate a dataset-specific subclass at runtime from the actual produced
evaluation set, then use that subclass to run grey evaluation.

Policy:
  - The canonical model config is BENCHCLAW_ROOT/modelNeedMeasured/model_config.json.
  - If BENCHCLAW_ROOT is unset, locate it by walking ancestors for both
    modelNeedMeasured/ and skills/.
  - The only evaluable model list is model_config["grey_test"]["models"].
  - CLI arguments may limit item/model counts for debugging, but must not
    introduce models from any other file or ad-hoc hardcoded list.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import mimetypes
import os
import random
import re
import statistics
import textwrap
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import requests
except ImportError:  # pragma: no cover - inference mode reports this at runtime.
    requests = None


def find_benchclaw_root() -> Path:
    env_root = os.environ.get("BENCHCLAW_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "modelNeedMeasured").is_dir() and (parent / "skills").is_dir():
            return parent
    return Path.cwd().resolve()


MODEL_CONFIG_PATH = find_benchclaw_root() / "modelNeedMeasured" / "model_config.json"
MODEL_SOURCE_POLICY = "grey_test_only"
PREDICTION_KEYS = ("prediction", "pred", "answer", "model_answer", "response", "output")


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
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


def write_csv(path: Path, rows: Sequence[Dict[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def safe_id(value: Any) -> str:
    text = re.sub(r"\s+", "_", str(value or "").strip())
    text = re.sub(r"[^0-9A-Za-z_.:-]+", "_", text)
    return text.strip("_") or "UNKNOWN"


def metric_item_id(item: Dict[str, Any]) -> str:
    return str(item.get("eval_id") or item.get("id") or item.get("item_id") or item.get("sample_id") or "")


def first_present(item: Dict[str, Any], keys: Sequence[str], default: Any = "") -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return default


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ",".join(normalize_text(part) for part in value)
    text = str(value).strip()
    text = text.replace("，", ",").replace("；", ";").replace("：", ":")
    text = re.sub(r"\s+", " ", text)
    return text.casefold()


def normalize_choice_text(value: Any) -> str:
    return normalize_text(value).strip(" .。,:;；、()[]{}\"'")


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
    text = str(value or "").strip()
    if not text:
        return []
    text = text.replace("，", ",").replace("；", ",").replace("、", ",")
    return [part.strip() for part in re.split(r"[,;\s]+", text) if part.strip()]


def option_keys(options: Any) -> List[str]:
    if not isinstance(options, dict):
        return []
    return [str(key).upper() for key in options.keys()]


def option_value_to_keys(options: Any) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = defaultdict(list)
    if isinstance(options, dict):
        for key, value in options.items():
            result[normalize_choice_text(value)].append(str(key).upper())
    return result


def choice_list(value: Any, options: Any, allow_multi: bool) -> List[str]:
    keys = option_keys(options)
    valid = set(keys)
    if not valid:
        return [normalize_choice_text(part).upper() for part in as_sequence(value) if normalize_choice_text(part)]

    values_to_keys = option_value_to_keys(options)
    chunks = list(value) if isinstance(value, (list, tuple, set)) else as_sequence(value)
    if not chunks:
        chunks = [value]

    found: List[str] = []
    for chunk in chunks:
        raw = str(chunk or "").strip()
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
        for candidate in re.findall(r"(?<![A-Za-z0-9])([A-Za-z])(?=[\s,.;:：。)、)\]]|$)", raw):
            letter = candidate.upper()
            if letter in valid:
                found.append(letter)

    deduped: List[str] = []
    seen = set()
    for key in found:
        if key in valid and key not in seen:
            deduped.append(key)
            seen.add(key)
    return deduped if allow_multi else deduped[:1]


def set_f1(gold_set: set, pred_set: set) -> float:
    if not gold_set and not pred_set:
        return 1.0
    if not gold_set or not pred_set:
        return 0.0
    tp = len(gold_set & pred_set)
    precision = tp / len(pred_set)
    recall = tp / len(gold_set)
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def summarize(values: Sequence[float]) -> Dict[str, Any]:
    if not values:
        return {"n": 0, "mean_score": 0.0}
    return {
        "n": len(values),
        "mean_score": sum(values) / len(values),
        "median_score": statistics.median(values),
        "min_score": min(values),
        "max_score": max(values),
    }


@dataclass(frozen=True)
class GreyModelEndpoint:
    model_ref: str
    provider_id: str
    model_id: str
    api_model: str
    endpoint: str
    api_key: str
    display_name: str
    capabilities: Dict[str, Any]


class GreyTestModelConfig:
    """Read grey-test models from the single canonical model_config.json."""

    def __init__(self, path: Path = MODEL_CONFIG_PATH) -> None:
        self.path = Path(path)
        if self.path != MODEL_CONFIG_PATH:
            raise ValueError(f"Model config override is forbidden; use {MODEL_CONFIG_PATH}")
        self.payload = self._load_payload()

    def _load_payload(self) -> Dict[str, Any]:
        if not self.path.is_file():
            raise FileNotFoundError(f"Required model config does not exist: {self.path}")
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Model config must contain a JSON object: {self.path}")
        if not isinstance(payload.get("provider"), dict):
            raise ValueError("model_config.json must contain provider object")
        if not isinstance(payload.get("grey_test"), dict):
            raise ValueError("model_config.json must contain grey_test object")
        models = payload["grey_test"].get("models")
        if not isinstance(models, list) or not models:
            raise ValueError("model_config.json grey_test.models must be a non-empty list")
        return payload

    @staticmethod
    def _endpoint_from_base_url(base_url: Any) -> str:
        text = str(base_url or "").strip().rstrip("/")
        if not text:
            return ""
        if text.endswith("/chat/completions"):
            return text
        return f"{text}/chat/completions"

    @staticmethod
    def _api_key(raw: Any) -> str:
        text = str(raw or "").strip()
        if text.startswith("env:"):
            return os.environ.get(text[4:].strip(), "").strip()
        if text.startswith("${") and text.endswith("}"):
            return os.environ.get(text[2:-1].strip(), "").strip()
        return text

    @staticmethod
    def _parse_model_ref(model_ref: str) -> Tuple[str, str]:
        provider_id, sep, model_id = str(model_ref).partition("/")
        if not sep or not provider_id.strip() or not model_id.strip():
            raise ValueError(f"Invalid grey_test model reference {model_ref!r}; expected provider/model_id")
        return provider_id.strip(), model_id.strip()

    def resolve_model_ref(self, model_ref: str) -> GreyModelEndpoint:
        provider_id, model_id = self._parse_model_ref(model_ref)
        providers = self.payload["provider"]
        provider_cfg = providers.get(provider_id)
        if not isinstance(provider_cfg, dict):
            raise ValueError(f"grey_test model {model_ref!r} references unknown provider {provider_id!r}")
        options = provider_cfg.get("options") if isinstance(provider_cfg.get("options"), dict) else {}
        models = provider_cfg.get("models") if isinstance(provider_cfg.get("models"), dict) else {}
        model_cfg = models.get(model_id)
        if not isinstance(model_cfg, dict):
            raise ValueError(f"grey_test model {model_ref!r} references unknown provider model {model_id!r}")
        endpoint = self._endpoint_from_base_url(
            model_cfg.get("endpoint")
            or model_cfg.get("baseURL")
            or options.get("baseURL")
            or options.get("baseUrl")
        )
        if not endpoint:
            raise ValueError(f"grey_test model {model_ref!r} has no provider/model endpoint")
        api_model = str(model_cfg.get("api_model") or model_cfg.get("model") or model_id).strip()
        if not api_model:
            raise ValueError(f"grey_test model {model_ref!r} has no api_model/model")
        return GreyModelEndpoint(
            model_ref=str(model_ref),
            provider_id=provider_id,
            model_id=model_id,
            api_model=api_model,
            endpoint=endpoint,
            api_key=self._api_key(model_cfg.get("apiKey") or options.get("apiKey")),
            display_name=str(model_cfg.get("name") or model_id),
            capabilities=model_cfg.get("capabilities") if isinstance(model_cfg.get("capabilities"), dict) else {},
        )

    def grey_models(self, *, max_models: int = 0) -> List[GreyModelEndpoint]:
        refs = [str(item).strip() for item in self.payload["grey_test"]["models"] if str(item).strip()]
        endpoints = [self.resolve_model_ref(model_ref) for model_ref in refs]
        return endpoints[:max_models] if max_models else endpoints


class BaseGreyMetricEvaluator(ABC):
    """Parent class for generated dataset-specific grey metric evaluators.

    Subclasses should be generated from the actual evaluation JSONL produced by
    Stage4 answer-program generation. They normally only override:
      - metric_name
      - score_item
      - optional media_fields / build_prompt if the benchmark has custom media
    """

    dataset_profile: Dict[str, Any] = {}

    def __init__(
        self,
        items_path: Path,
        out_dir: Path,
        *,
        seed: int = 20260624,
        limit: int = 0,
        dry_run: bool = False,
        include_image: bool = True,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        timeout: int = 120,
        max_models: int = 0,
    ) -> None:
        self.items_path = Path(items_path).expanduser().resolve()
        self.out_dir = Path(out_dir).expanduser().resolve()
        self.seed = seed
        self.limit = limit
        self.dry_run = dry_run
        self.include_image = include_image
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_models = max_models
        self.model_config = GreyTestModelConfig()

    @property
    @abstractmethod
    def metric_name(self) -> str:
        """Stable metric/evaluator name for manifests and generated files."""

    @abstractmethod
    def score_item(self, item: Dict[str, Any], prediction: Any) -> Tuple[float, Dict[str, Any]]:
        """Return item-level score and parse/normalization detail."""

    def load_items(self) -> List[Dict[str, Any]]:
        items = read_jsonl(self.items_path)
        if not items:
            raise ValueError(f"Evaluation set is empty: {self.items_path}")
        if self.limit:
            rng = random.Random(self.seed)
            items = rng.sample(items, min(self.limit, len(items)))
        return items

    def media_fields(self, item: Dict[str, Any]) -> List[str]:
        """Return media paths/URLs visible to the model."""
        media: List[str] = []
        for key in ("image", "media", "asset", "input_image"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                media.append(value.strip())
        for key in ("images", "media_paths", "auxiliary_images"):
            value = item.get(key)
            if isinstance(value, list):
                media.extend(str(part).strip() for part in value if str(part).strip())
        deduped: List[str] = []
        seen = set()
        for path in media:
            if path not in seen:
                deduped.append(path)
                seen.add(path)
        return deduped

    def build_prompt(self, item: Dict[str, Any]) -> str:
        options = item.get("options")
        option_text = ""
        if isinstance(options, dict):
            option_text = "\n".join(f"{key}. {value}" for key, value in options.items())
        lines = [
            "请回答下面这道灰度评测题。",
            f"template_id: {item.get('template_id') or 'UNKNOWN'}",
            f"answer_type: {item.get('answer_type') or item.get('answer_format') or 'UNKNOWN'}",
            "",
            "题目：",
            str(first_present(item, ("question", "question_text", "prompt"), "")),
        ]
        if option_text:
            lines.extend(["", "选项：", option_text])
        lines.extend(
            [
                "",
                "输出要求：",
                "只输出合法 JSON，格式为 {\"answer\": \"选项字母或最终答案\", \"reason\": \"一句简短依据\"}。",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _guess_mime(path_text: str) -> str:
        mime, _ = mimetypes.guess_type(path_text)
        return mime or "image/jpeg"

    def _media_to_data_url(self, path_text: str) -> str:
        text = str(path_text or "").strip()
        if text.startswith(("http://", "https://", "data:image/")):
            return text
        path = Path(text).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Media file does not exist: {path_text}")
        b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
        return f"data:{self._guess_mime(str(path))};base64,{b64}"

    def build_messages(self, item: Dict[str, Any]) -> List[Dict[str, Any]]:
        content: List[Dict[str, Any]] = [{"type": "text", "text": self.build_prompt(item)}]
        if self.include_image:
            media = self.media_fields(item)
            if not media:
                raise ValueError(f"Item {metric_item_id(item)} has no visible media")
            for path_text in media:
                content.append({"type": "image_url", "image_url": {"url": self._media_to_data_url(path_text), "detail": "high"}})
        return [
            {"role": "system", "content": "你是一个严谨的图文题评测模型，只根据可见输入作答。"},
            {"role": "user", "content": content},
        ]

    @staticmethod
    def response_text(resp_json: Dict[str, Any]) -> str:
        choices = resp_json.get("choices") or []
        if not choices:
            return ""
        msg = choices[0].get("message") or {}
        content = msg.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    parts.append(str(part.get("text") or part.get("content") or ""))
                else:
                    parts.append(str(part))
            return "\n".join(text for text in parts if text)
        return str(content)

    @staticmethod
    def prediction_from_text(text: str) -> Any:
        ok, obj = parse_json_maybe(text)
        if ok and isinstance(obj, dict):
            for key in PREDICTION_KEYS:
                if key in obj:
                    return obj[key]
            return obj
        if ok:
            return obj
        return text

    def call_model(self, item: Dict[str, Any], model: GreyModelEndpoint) -> Dict[str, Any]:
        if requests is None:
            raise RuntimeError("Missing dependency: requests")
        payload = {
            "model": model.api_model,
            "messages": self.build_messages(item),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        headers = {"Content-Type": "application/json"}
        if model.api_key:
            headers["Authorization"] = f"Bearer {model.api_key}"
        started = time.time()
        session = requests.Session()
        if re.match(r"^https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(?::|/|$)", model.endpoint, re.I):
            session.trust_env = False
        resp = session.post(model.endpoint, headers=headers, json=payload, timeout=self.timeout)
        try:
            resp_json = resp.json()
        except Exception:
            resp_json = {"raw_text": resp.text[:4000]}
        text = self.response_text(resp_json) if isinstance(resp_json, dict) else ""
        ok = resp.status_code == 200 and bool(str(text).strip())
        return {
            "ok": ok,
            "status_code": resp.status_code,
            "duration_sec": round(time.time() - started, 4),
            "response_json": resp_json,
            "response_text": text,
            "prediction": self.prediction_from_text(text) if ok else None,
            "error": None if ok else str(resp.text[:1000]),
        }

    def generate_runtime_code(self, output_path: Path, items: Sequence[Dict[str, Any]]) -> None:
        """Emit a dataset-specific subclass skeleton/profile from real items."""
        profile = self.profile_items(items)
        class_name = "".join(part.capitalize() for part in safe_id(profile["metric_name"]).split("_")) + "Evaluator"
        code = f'''#!/usr/bin/env python3
"""Generated grey metric evaluator.

Generated from: {self.items_path}
This file must keep using GreyTestModelConfig, which reads only:
{MODEL_CONFIG_PATH}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

from grey_metric_eval_base import (
    BaseGreyMetricEvaluator,
    choice_list,
    normalize_choice_text,
    parse_json_maybe,
    set_f1,
)


DATASET_PROFILE = {json.dumps(profile, ensure_ascii=False, indent=2)}


class {class_name}(BaseGreyMetricEvaluator):
    dataset_profile = DATASET_PROFILE

    @property
    def metric_name(self) -> str:
        return DATASET_PROFILE["metric_name"]

    def score_item(self, item: Dict[str, Any], prediction: Any) -> Tuple[float, Dict[str, Any]]:
        # Replace or extend this generated default when the actual metric JSON
        # declares a stricter template-specific metric.
        answer_type = str(item.get("answer_type") or item.get("answer_format") or "").lower()
        options = item.get("options")
        if answer_type in {{"multi_choice", "multiple_choice"}}:
            gold = set(choice_list(item.get("answer"), options, allow_multi=True))
            pred = set(choice_list(prediction, options, allow_multi=True))
            return set_f1(gold, pred), {{"gold_set": sorted(gold), "pred_set": sorted(pred)}}
        gold_choice = choice_list(item.get("answer"), options, allow_multi=False)
        pred_choice = choice_list(prediction, options, allow_multi=False)
        if gold_choice or pred_choice:
            return float(bool(gold_choice and pred_choice and gold_choice[0] == pred_choice[0])), {{
                "gold_choice": gold_choice[:1],
                "pred_choice": pred_choice[:1],
            }}
        ok, pred_obj = parse_json_maybe(prediction)
        if isinstance(item.get("answer"), (dict, list)):
            return float(ok and pred_obj == item.get("answer")), {{"json_parse_ok": ok, "prediction": pred_obj}}
        return float(normalize_choice_text(item.get("answer")) == normalize_choice_text(prediction)), {{
            "gold_norm": normalize_choice_text(item.get("answer")),
            "pred_norm": normalize_choice_text(prediction),
        }}


Evaluator = {class_name}
'''
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(code, encoding="utf-8")

    def profile_items(self, items: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        answer_types = sorted(
            {str(first_present(item, ("answer_type", "answer_format"), "UNKNOWN")) for item in items}
        )
        templates = sorted({str(item.get("template_id") or "UNKNOWN") for item in items})
        capabilities = sorted(
            {
                str(first_present(item, ("capability", "capability_id", "capability_name"), "UNKNOWN"))
                for item in items
            }
        )
        media_keys = sorted({key for item in items for key in ("image", "images", "media", "media_paths", "auxiliary_images") if key in item})
        return {
            "metric_name": self.metric_name,
            "num_profiled_items": len(items),
            "answer_types": answer_types,
            "template_ids": templates,
            "capabilities": capabilities,
            "media_keys": media_keys,
            "model_config_source": str(MODEL_CONFIG_PATH),
            "model_source_policy": MODEL_SOURCE_POLICY,
            "grey_test_model_refs": [model.model_ref for model in self.model_config.grey_models(max_models=self.max_models)],
        }

    def run(self) -> Dict[str, Any]:
        items = self.load_items()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        runtime_code_path = self.out_dir / "generated_grey_metric_evaluator.py"
        self.generate_runtime_code(runtime_code_path, items)
        write_jsonl(self.out_dir / "sampled_gold.jsonl", items)

        models = self.model_config.grey_models(max_models=self.max_models)
        raw_dir = self.out_dir / "raw_inference"
        pred_dir = self.out_dir / "predictions"
        score_dir = self.out_dir / "scores"
        aggregate_scores: Dict[Tuple[str, str], List[float]] = defaultdict(list)
        item_score_rows: List[Dict[str, Any]] = []

        for model in models:
            model_key = safe_id(model.api_model)
            pred_rows: List[Dict[str, Any]] = []
            score_rows: List[Dict[str, Any]] = []
            for item in items:
                item_id = metric_item_id(item)
                raw_path = raw_dir / model_key / f"{safe_id(item_id)}.json"
                if self.dry_run:
                    raw_record = {
                        "ok": False,
                        "error": "dry_run_no_api_call",
                        "response_text": "",
                        "prediction": None,
                    }
                else:
                    raw_record = self.call_model(item, model)
                raw_record.update(
                    {
                        "eval_id": item_id,
                        "id": item.get("id"),
                        "template_id": item.get("template_id"),
                        "model_ref": model.model_ref,
                        "model": model.api_model,
                        "provider_id": model.provider_id,
                        "model_config_source": str(MODEL_CONFIG_PATH),
                        "model_source_policy": MODEL_SOURCE_POLICY,
                    }
                )
                write_json(raw_path, raw_record)
                prediction = raw_record.get("prediction")
                score_value, detail = self.score_item(item, prediction)
                score_row = {
                    "eval_id": item_id,
                    "id": item.get("id"),
                    "template_id": item.get("template_id"),
                    "capability": first_present(item, ("capability", "capability_id", "capability_name"), "UNKNOWN"),
                    "answer_type": first_present(item, ("answer_type", "answer_format"), "UNKNOWN"),
                    "model_ref": model.model_ref,
                    "model": model.api_model,
                    "score": score_value,
                    "prediction": prediction,
                    "gold_answer": item.get("answer"),
                    "detail": detail,
                    "raw_result_path": str(raw_path),
                    "chain_id": item.get("chain_id"),
                    "reasoning_hop_count": item.get("reasoning_hop_count"),
                    "gt_distance_level": item.get("gt_distance_level"),
                    "depth_role": item.get("depth_role"),
                }
                pred_rows.append(
                    {
                        "eval_id": item_id,
                        "id": item.get("id"),
                        "template_id": item.get("template_id"),
                        "model_ref": model.model_ref,
                        "model": model.api_model,
                        "prediction": prediction,
                        "ok": raw_record.get("ok"),
                        "error": raw_record.get("error"),
                    }
                )
                score_rows.append(score_row)
                item_score_rows.append(score_row)
                aggregate_scores[(model.model_ref, model.api_model)].append(float(score_value))
            write_jsonl(pred_dir / f"{model_key}.jsonl", pred_rows)
            write_jsonl(score_dir / f"{model_key}_score_items.jsonl", score_rows)

        model_rows = [
            {
                "model_ref": model_ref,
                "model": api_model,
                **summarize(values),
            }
            for (model_ref, api_model), values in sorted(aggregate_scores.items())
        ]
        write_csv(
            self.out_dir / "model_overall_scores.csv",
            model_rows,
            ["model_ref", "model", "n", "mean_score", "median_score", "min_score", "max_score"],
        )
        manifest = {
            "items_path": str(self.items_path),
            "out_dir": str(self.out_dir),
            "runtime_code": str(runtime_code_path),
            "metric_name": self.metric_name,
            "num_items": len(items),
            "model_config_source": str(MODEL_CONFIG_PATH),
            "model_source_policy": MODEL_SOURCE_POLICY,
            "grey_test_models": [model.model_ref for model in models],
            "dry_run": self.dry_run,
            "outputs": {
                "raw_inference": str(raw_dir),
                "predictions": str(pred_dir),
                "scores": str(score_dir),
                "model_overall_scores": str(self.out_dir / "model_overall_scores.csv"),
            },
        }
        write_json(self.out_dir / "grey_eval_manifest.json", manifest)
        write_jsonl(self.out_dir / "all_score_items.jsonl", item_score_rows)
        return manifest


class GenericGeneratedGreyMetricEvaluator(BaseGreyMetricEvaluator):
    """Concrete fallback used for smoke tests and simple generated metrics.

    Real metric-compilation output should subclass BaseGreyMetricEvaluator with
    template-specific parsing and scoring from the compiled metric JSON.
    """

    @property
    def metric_name(self) -> str:
        return "generic_generated_metric"

    def score_item(self, item: Dict[str, Any], prediction: Any) -> Tuple[float, Dict[str, Any]]:
        answer_type = str(first_present(item, ("answer_type", "answer_format"), "")).lower()
        options = item.get("options")
        if answer_type in {"multi_choice", "multiple_choice"}:
            gold = set(choice_list(item.get("answer"), options, allow_multi=True))
            pred = set(choice_list(prediction, options, allow_multi=True))
            return set_f1(gold, pred), {"gold_set": sorted(gold), "pred_set": sorted(pred)}
        if answer_type in {"ordered_list", "order"}:
            gold_order = choice_list(item.get("answer"), options, allow_multi=True)
            pred_order = choice_list(prediction, options, allow_multi=True)
            pred_rank = {key: idx for idx, key in enumerate(pred_order)}
            total = 0
            correct = 0
            for idx, left in enumerate(gold_order):
                for right in gold_order[idx + 1:]:
                    total += 1
                    if left in pred_rank and right in pred_rank and pred_rank[left] < pred_rank[right]:
                        correct += 1
            return (correct / total if total else float(gold_order == pred_order)), {
                "gold_order": gold_order,
                "pred_order": pred_order,
                "total_pairs": total,
            }
        if answer_type in {"number", "numeric"}:
            gold = as_float(item.get("answer"))
            pred = as_float(prediction)
            ok = gold is not None and pred is not None and gold == pred
            return float(ok), {"gold": gold, "prediction": pred}
        gold_choice = choice_list(item.get("answer"), options, allow_multi=False)
        pred_choice = choice_list(prediction, options, allow_multi=False)
        if gold_choice or pred_choice:
            return float(bool(gold_choice and pred_choice and gold_choice[0] == pred_choice[0])), {
                "gold_choice": gold_choice[:1],
                "pred_choice": pred_choice[:1],
            }
        ok, pred_obj = parse_json_maybe(prediction)
        if isinstance(item.get("answer"), (dict, list)):
            return float(ok and pred_obj == item.get("answer")), {
                "json_parse_ok": ok,
                "prediction": pred_obj,
            }
        return float(normalize_choice_text(item.get("answer")) == normalize_choice_text(prediction)), {
            "gold_norm": normalize_choice_text(item.get("answer")),
            "pred_norm": normalize_choice_text(prediction),
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Base grey metric evaluator template. Models are read only from "
            f"{MODEL_CONFIG_PATH} grey_test.models."
        )
    )
    parser.add_argument("--items", required=True, help="Actual generated evaluation JSONL.")
    parser.add_argument("--out-dir", required=True, help="Output directory for runtime code and grey results.")
    parser.add_argument("--limit", type=int, default=0, help="Optional sampled item limit for smoke runs.")
    parser.add_argument("--seed", type=int, default=20260624)
    parser.add_argument("--max-models", type=int, default=0, help="Limit grey_test models after reading model_config.json.")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--dry-run", action="store_true", help="Generate runtime code and outputs without model calls.")
    parser.add_argument("--no-image", action="store_true", help="Run text-only prompt path for debugging.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    evaluator = GenericGeneratedGreyMetricEvaluator(
        Path(args.items),
        Path(args.out_dir),
        seed=args.seed,
        limit=args.limit,
        dry_run=args.dry_run,
        include_image=not args.no_image,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        timeout=args.timeout,
        max_models=args.max_models,
    )
    manifest = evaluator.run()
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
