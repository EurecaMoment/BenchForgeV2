# Qwen streaming relay

The provider's 30 minute SDK/watchdog settings do not change the HTTP client's
roughly 300 second body idle timeout. On the inspected deployment, the internal
9000 proxy buffered SSE output: the same completed 256 token request returned its
first SSE bytes after 30.618 seconds on 9000, versus 0.338 seconds on 8008. This
relay defaults to the directly streaming 8008 endpoint. `--upstream-port 9000`
retains the old route for rollback; its buffering remains outside this relay.

For `stream: true` requests with a successful `text/event-stream` response, one
writer sends complete upstream SSE events unchanged and adds a comment after
15 seconds without a complete event. This keeps the HTTP connection active
without inventing model tokens or tool arguments. A dedicated reader assembles
events across arbitrary packet boundaries. Non-streaming and HTTP error bodies
pass through unchanged with `read1()` and receive no comments.

Heartbeats do not extend the 30 minute total request deadline. Upload reads and
downstream writes also use the remaining budget; reporting a final error gets
at most one additional second. A real client
disconnect immediately shuts down the upstream socket; the reader and watcher
threads are joined during cleanup. A timeout, read failure, missing completion,
or partial final event produces an SSE `error` payload after response headers.
The relay never retries a request or fabricates `[DONE]`.

Run from the repository root, passing the existing local credential file path:

```powershell
python integrations/qwen_relay/relay.py --key-file <existing-key-file> --port 19002
```

`--upstream-host`, `--upstream-port`, `--heartbeat-interval`, and `--total-timeout`
are configurable. Importing the module reads no key file. Tests and acceptance
harnesses can use `create_server(RelayConfig(key="test", ...), port=0)` with a
local fake upstream; call `serve_forever()` on a background thread and
`shutdown()` / `server_close()` when finished.

Focused local verification:

```powershell
python -m unittest discover -s integrations/qwen_relay/tests -v
```

The tests cover split JSON/UTF-8/CRLF, exact tool argument bytes, heartbeat
eligibility, genuine client cancellation, total deadline despite heartbeats,
and an incomplete upstream event without a synthetic completion. They use only
loopback fake servers and short deadlines.

On 2026-11-05, the production Node 22.22.2 runtime (built-in Undici 6.24.1)
failed an unpatched, controlled idle stream after 300.789 seconds with the
original cause `UND_ERR_BODY_TIMEOUT`. The relay completed the same stream
after a deliberate 310 second upstream gap: 20 comment heartbeats, unchanged
`beforeafter` content, the real `stop` reason and `[DONE]`. A real model request
through the deployed FIT route completed an automatic function call with the
expected arguments and `finish_reason=tool_calls` in 3.178 seconds. Cancellation
and the absolute deadline were checked using the focused real-socket tests;
the long idle test uses an isolated synthetic upstream, not a production scene.
