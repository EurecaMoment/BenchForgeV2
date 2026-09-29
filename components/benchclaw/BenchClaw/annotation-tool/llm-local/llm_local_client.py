#!/usr/bin/env python3
import argparse
import json
import os
import urllib.request


BASE_URL = os.environ.get("LLM_LOCAL_BASE_URL", "http://127.0.0.1:9001")
DEFAULT_MODEL = os.environ.get("LLM_LOCAL_MODEL", "qwen3.5-0.8b")
DEFAULT_MAX_TOKENS = int(os.environ.get("LLM_LOCAL_MAX_TOKENS", "32000"))
DEFAULT_REPETITION_PENALTY = float(os.environ.get("LLM_LOCAL_REPETITION_PENALTY", "1.15"))


def load_json_file(path_value):
    with open(path_value, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _http_get(path):
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=30) as response:
        return response.status, response.read().decode("utf-8")


def _http_post(path, payload):
    data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=3600) as response:
        return json.loads(response.read().decode("utf-8"))


def print_json(payload):
    print(json.dumps(payload, ensure_ascii=True, indent=2))


def cmd_health(_args):
    status, body = _http_get("/health")
    print_json({"ok": status == 200, "status": status, "body": body})


def cmd_models(_args):
    _status, body = _http_get("/v1/models")
    print_json(json.loads(body))


def cmd_chat(args):
    messages = []
    if args.system:
        messages.append({"role": "system", "content": args.system})
    messages.append({"role": "user", "content": args.user})

    payload = {
        "model": args.model,
        "messages": messages,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "repetition_penalty": args.repetition_penalty,
        "stream": False,
    }
    print_json(_http_post("/v1/chat/completions", payload))


def cmd_chat_request(args):
    payload = load_json_file(args.request_file)

    payload.setdefault("model", args.model)
    payload.setdefault("max_tokens", args.max_tokens)
    payload.setdefault("repetition_penalty", args.repetition_penalty)
    payload.setdefault("stream", False)

    print_json(_http_post("/v1/chat/completions", payload))


def cmd_completion(args):
    payload = {
        "model": args.model,
        "prompt": args.prompt,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "repetition_penalty": args.repetition_penalty,
        "stream": False,
    }
    print_json(_http_post("/v1/completions", payload))


def build_parser():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    health_parser = subparsers.add_parser("health")
    health_parser.set_defaults(func=cmd_health)

    models_parser = subparsers.add_parser("models")
    models_parser.set_defaults(func=cmd_models)

    chat_parser = subparsers.add_parser("chat")
    chat_parser.add_argument("--system")
    chat_parser.add_argument("--user", required=True)
    chat_parser.add_argument("--model", default=DEFAULT_MODEL)
    chat_parser.add_argument("--temperature", type=float, default=0.0)
    chat_parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    chat_parser.add_argument(
        "--repetition-penalty",
        type=float,
        default=DEFAULT_REPETITION_PENALTY,
        help="重复惩罚系数，默认 1.15；如果后端不支持该参数，需要设为后端可接受的值或删掉 payload 字段。",
    )
    chat_parser.set_defaults(func=cmd_chat)

    chat_request_parser = subparsers.add_parser("chat-request")
    chat_request_parser.add_argument("--request-file", required=True)
    chat_request_parser.add_argument("--model", default=DEFAULT_MODEL)
    chat_request_parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    chat_request_parser.add_argument(
        "--repetition-penalty",
        type=float,
        default=DEFAULT_REPETITION_PENALTY,
    )
    chat_request_parser.set_defaults(func=cmd_chat_request)

    completion_parser = subparsers.add_parser("completion")
    completion_parser.add_argument("--prompt", required=True)
    completion_parser.add_argument("--model", default=DEFAULT_MODEL)
    completion_parser.add_argument("--temperature", type=float, default=0.0)
    completion_parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    completion_parser.add_argument(
        "--repetition-penalty",
        type=float,
        default=DEFAULT_REPETITION_PENALTY,
    )
    completion_parser.set_defaults(func=cmd_completion)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()