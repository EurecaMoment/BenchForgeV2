"""Authenticated loopback relay with SSE heartbeats and bounded cancellation.

The module is safe to import: only main() reads the supplied credential file.
"""
from __future__ import annotations

import argparse
import http.client
import json
import queue
import select
import socket
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys


HEARTBEAT = b": relay keepalive\n\n"
_HOP_HEADERS = {
    "connection", "transfer-encoding", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailer", "upgrade", "proxy-connection",
}


@dataclass(frozen=True)
class RelayConfig:
    key: str
    upstream_host: str = "172.31.1.7"
    upstream_port: int = 8008
    heartbeat_interval: float = 15.0
    total_timeout: float = 1800.0
    connect_timeout: float = 10.0
    read_timeout: float = 1800.0
    max_event_bytes: int = 16 * 1024 * 1024

    def __post_init__(self):
        if not self.key:
            raise ValueError("Key is empty")
        if min(self.heartbeat_interval, self.total_timeout,
               self.connect_timeout, self.read_timeout) <= 0:
            raise ValueError("Timeouts and heartbeat interval must be positive")
        if self.max_event_bytes < 1:
            raise ValueError("max_event_bytes must be positive")


class _SSEFramer:
    """Keep exact bytes, releasing only records ending with an empty line."""

    def __init__(self, limit):
        self.limit = limit
        self.event = bytearray()
        self.line_has_data = False
        self.pending_cr = False
        self.cr_ended_event = False

    def _take(self):
        event = bytes(self.event)
        self.event.clear()
        return event

    def feed(self, block):
        for byte in block:
            if self.pending_cr:
                self.pending_cr = False
                if byte == 10:
                    self.event.append(byte)
                    if self.cr_ended_event:
                        yield self._take()
                    continue
                if self.cr_ended_event:
                    yield self._take()
            self.event.append(byte)
            if len(self.event) > self.limit:
                raise ValueError("Upstream SSE event exceeds relay limit")
            if byte == 13:
                self.pending_cr = True
                self.cr_ended_event = not self.line_has_data
                self.line_has_data = False
            elif byte == 10:
                ended_event = not self.line_has_data
                self.line_has_data = False
                if ended_event:
                    yield self._take()
            else:
                self.line_has_data = True

    def finish(self):
        if self.pending_cr and self.cr_ended_event:
            self.pending_cr = False
            yield self._take()


def _event_status(event):
    data = []
    is_error = False
    for line in event.replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n"):
        field, _, value = line.partition(b":")
        if value.startswith(b" "):
            value = value[1:]
        if field == b"data":
            data.append(value)
        elif field == b"event" and value == b"error":
            is_error = True
    payload = b"\n".join(data)
    if payload == b"[DONE]":
        return "done"
    if payload:
        try:
            decoded = json.loads(payload)
            is_error = is_error or (isinstance(decoded, dict) and "error" in decoded)
        except (ValueError, UnicodeError):
            pass
    return "error" if is_error else "event"


class _RequestState:
    def __init__(self, timeout):
        self.deadline = time.monotonic() + timeout
        self.stopped = threading.Event()
        self.reason = None
        self.upstream_socket = None
        self.lock = threading.Lock()

    def attach(self, upstream_socket):
        with self.lock:
            self.upstream_socket = upstream_socket
            stopped = self.stopped.is_set()
        if stopped:
            self._shutdown(upstream_socket)

    @staticmethod
    def _shutdown(upstream_socket):
        if upstream_socket is not None:
            try:
                upstream_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def stop(self, reason):
        with self.lock:
            if self.reason is not None:
                return
            self.reason = reason
            self.stopped.set()
            upstream_socket = self.upstream_socket
        self._shutdown(upstream_socket)

    def watch_deadline(self):
        if not self.stopped.wait(max(0.0, self.deadline - time.monotonic())):
            self.stop("deadline")

    def watch_client(self, client):
        while not self.stopped.is_set():
            try:
                readable, _, _ = select.select([client], [], [], 0.1)
                if not readable:
                    continue
                if not client.recv(1, socket.MSG_PEEK):
                    self.stop("client_cancelled")
                    return
                # A pipelined request is not EOF; this relay closes after one response.
                self.stopped.wait(0.1)
            except (OSError, ValueError):
                self.stop("client_cancelled")
                return


def create_server(config: RelayConfig, host="127.0.0.1", port=0):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            self.forward()

        def do_POST(self):
            self.forward()

        def _json_error(self, status, code, message):
            body = json.dumps({"error": {"message": message, "type": "relay_error",
                                         "code": code}}, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()

        def _write(self, payload, state, *, final_error=False):
            remaining = state.deadline - time.monotonic()
            if remaining <= 0 and not final_error:
                state.stop("deadline")
                raise TimeoutError("Relay deadline exceeded")
            # A client that stops reading must not leave sendall blocked beyond
            # the request deadline. Allow at most 1s to report a final error.
            budget = max(0.001, remaining) if not final_error else 1.0
            self.connection.settimeout(min(config.read_timeout, budget))
            self.wfile.write(payload)
            self.wfile.flush()

        def _sse_error(self, code, message, state):
            payload = json.dumps({"error": {"message": message, "type": "relay_error",
                                           "code": code}}, separators=(",", ":")).encode()
            self._write(b"data: " + payload + b"\n\n", state, final_error=True)

        def _stream(self, response, state, readers):
            incoming = queue.Queue(maxsize=32)

            def deliver(kind, value=None):
                while not state.stopped.is_set():
                    try:
                        incoming.put((kind, value), timeout=0.1)
                        return
                    except queue.Full:
                        pass

            def read_events():
                framer = _SSEFramer(config.max_event_bytes)
                try:
                    while not state.stopped.is_set():
                        block = response.read1(65536)
                        if not block:
                            for event in framer.finish():
                                deliver("event", event)
                            deliver("incomplete" if framer.event else "eof")
                            return
                        for event in framer.feed(block):
                            deliver("event", event)
                except (OSError, http.client.HTTPException, ValueError):
                    deliver("error")

            reader = threading.Thread(target=read_events, name="qwen-relay-sse", daemon=True)
            readers.append(reader)
            reader.start()
            next_heartbeat = time.monotonic() + config.heartbeat_interval
            while True:
                if state.reason == "deadline" or time.monotonic() >= state.deadline:
                    state.stop("deadline")
                    self._sse_error("relay_deadline_exceeded", "Relay request exceeded its total time limit", state)
                    return
                if state.stopped.is_set():
                    return
                now = time.monotonic()
                try:
                    kind, value = incoming.get(timeout=max(0.001, min(
                        0.1, next_heartbeat - now, state.deadline - now)))
                except queue.Empty:
                    if time.monotonic() >= next_heartbeat:
                        self._write(HEARTBEAT, state)
                        next_heartbeat = time.monotonic() + config.heartbeat_interval
                    continue
                if kind == "event":
                    self._write(value, state)
                    next_heartbeat = time.monotonic() + config.heartbeat_interval
                    if _event_status(value) in {"done", "error"}:
                        return
                else:
                    code = "relay_upstream_error" if kind == "error" else "relay_upstream_incomplete"
                    self._sse_error(code, "Upstream stream ended before completion", state)
                    return

        def forward(self):
            self.close_connection = True
            if self.path not in ("/v1/models", "/v1/chat/completions"):
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > 64 * 1024 * 1024:
                    raise ValueError("Request size")
            except ValueError:
                self.send_error(413)
                return
            state = _RequestState(config.total_timeout)
            # read1 returns available bytes; reapply the remaining absolute
            # budget after every chunk so a dribbling upload cannot reset it.
            chunks = []
            remaining_length = length
            try:
                while remaining_length:
                    budget = state.deadline - time.monotonic()
                    if budget <= 0:
                        raise TimeoutError("Relay upload deadline exceeded")
                    self.connection.settimeout(min(config.read_timeout, budget))
                    block = self.rfile.read1(min(65536, remaining_length))
                    if not block:
                        return
                    chunks.append(block)
                    remaining_length -= len(block)
            except OSError:
                try:
                    self.connection.settimeout(1.0)
                    self._json_error(504, "relay_deadline_exceeded", "Request upload timed out")
                except OSError:
                    pass
                return
            body = b"".join(chunks) if length else None
            stream_requested = False
            if body:
                try:
                    request = json.loads(body)
                    stream_requested = isinstance(request, dict) and request.get("stream") is True
                except (ValueError, UnicodeError):
                    pass
            upstream = http.client.HTTPConnection(config.upstream_host, config.upstream_port,
                timeout=min(config.connect_timeout, max(0.001, state.deadline - time.monotonic())))
            threads = []
            response = None
            started = False
            is_sse = False
            try:
                timer = threading.Thread(target=state.watch_deadline, name="qwen-relay-deadline", daemon=True)
                threads.append(timer)
                timer.start()
                upstream.connect()
                upstream.sock.settimeout(config.read_timeout)
                state.attach(upstream.sock)
                watcher = threading.Thread(target=state.watch_client, args=(self.connection,),
                                           name="qwen-relay-cancel", daemon=True)
                threads.append(watcher)
                watcher.start()
                upstream.request(self.command, self.path, body=body, headers={
                    "Authorization": "Bearer " + config.key,
                    "Content-Type": "application/json", "Accept-Encoding": "identity",
                    "Connection": "close",
                })
                response = upstream.getresponse()
                is_sse = (stream_requested and 200 <= response.status < 300 and
                          response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
                          == "text/event-stream")
                self.connection.settimeout(min(config.read_timeout,
                    max(0.001, state.deadline - time.monotonic())))
                self.send_response(response.status)
                excluded = set(_HOP_HEADERS)
                excluded.update(name.strip().lower() for name in
                                response.getheader("Connection", "").split(","))
                if is_sse:
                    excluded.add("content-length")
                for name, value in response.getheaders():
                    if name.lower() not in excluded:
                        self.send_header(name, value)
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.flush()
                started = True
                if is_sse:
                    self._stream(response, state, threads)
                else:
                    while not state.stopped.is_set():
                        block = response.read1(65536)
                        if not block:
                            break
                        self._write(block, state)
            except (OSError, http.client.HTTPException) as error:
                self.log_message("transport_error=%s reason=%s", type(error).__name__, state.reason)
                if state.reason != "client_cancelled":
                    try:
                        deadline = state.reason == "deadline"
                        code = "relay_deadline_exceeded" if deadline else "relay_upstream_error"
                        if not started:
                            self.connection.settimeout(1.0)
                            self._json_error(504 if deadline else 502, code, "Qwen upstream unavailable")
                        elif is_sse:
                            self._sse_error(code, "Upstream stream failed", state)
                    except OSError:
                        pass
            finally:
                state.stop("complete")
                # shutdown() wakes blocked response reads before closing their file object.
                for thread in threads:
                    thread.join(timeout=1.0)
                if response is not None:
                    response.close()
                upstream.close()

        def log_message(self, fmt, *args):
            print(datetime.now(timezone.utc).isoformat(), fmt % args, file=sys.stderr, flush=True)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--port", type=int, default=19002)
    parser.add_argument("--upstream-host", default="172.31.1.7")
    parser.add_argument("--upstream-port", type=int, default=8008)
    parser.add_argument("--heartbeat-interval", type=float, default=15.0)
    parser.add_argument("--total-timeout", type=float, default=1800.0)
    args = parser.parse_args()
    config = RelayConfig(key=Path(args.key_file).read_text(encoding="utf-8").strip(),
                         upstream_host=args.upstream_host, upstream_port=args.upstream_port,
                         heartbeat_interval=args.heartbeat_interval, total_timeout=args.total_timeout)
    with create_server(config, port=args.port) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
