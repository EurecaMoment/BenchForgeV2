"""Focused relay contracts using loopback HTTP servers and a fake credential."""
import contextlib
import http.client
import json
import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from integrations.qwen_relay.relay import RelayConfig, create_server


HEARTBEAT = b": relay keepalive\n\n"


@contextlib.contextmanager
def running_relay(scenario, **settings):
    """Run one controlled upstream; background exceptions fail the test."""
    errors = []

    class UpstreamHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            try:
                scenario(self)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            except BaseException as error:
                errors.append(error)

        def log_message(self, *args):
            pass

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    upstream.daemon_threads = True
    config = RelayConfig(
        key="fake-test-key",
        upstream_host="127.0.0.1",
        upstream_port=upstream.server_address[1],
        heartbeat_interval=settings.pop("heartbeat_interval", 0.02),
        total_timeout=settings.pop("total_timeout", 2.0),
        connect_timeout=0.5,
        read_timeout=1.0,
        **settings,
    )
    relay = create_server(config, host="127.0.0.1", port=0)
    servers = (upstream, relay)
    threads = []
    for server in servers:
        thread = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        thread.start()
        threads.append(thread)
    try:
        yield relay.server_address[1]
    finally:
        for server in reversed(servers):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=1)
        if errors:
            raise errors[0]


def post(port, *, stream=True):
    client = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    client.request(
        "POST",
        "/v1/chat/completions",
        body=json.dumps({"model": "fake", "stream": stream, "messages": []}),
        headers={"Content-Type": "application/json"},
    )
    return client, client.getresponse()


def begin_sse(handler):
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.end_headers()
    handler.wfile.flush()


def error_codes(body):
    values = []
    for event in body.split(b"\n\n"):
        if not event.startswith(b"data:"):
            continue
        data = event[len(b"data:"):].strip()
        if data == b"[DONE]":
            continue
        value = json.loads(data)
        if "error" in value:
            values.append(value["error"].get("code"))
    return values


class RelayTests(unittest.TestCase):
    def test_split_events_and_tool_arguments_remain_byte_identical(self):
        # Boundaries deliberately divide JSON, a UTF-8 sequence and CRLF.
        event1 = (
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":'
            '{"arguments":"{\\\"name\\\":\\\"中"}}]}}]}\r\n\r\n'
        ).encode("utf-8")
        event2 = (
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":'
            '{"arguments":"文\\\"}"}}]}}]}\n\n'
        ).encode("utf-8")
        done = b"data: [DONE]\n\n"
        expected = event1 + event2 + done
        observed = {}

        def scenario(handler):
            observed["authorization"] = handler.headers.get("Authorization")
            observed["accept_encoding"] = handler.headers.get("Accept-Encoding")
            begin_sse(handler)
            split = event1.index("中".encode("utf-8")) + 1
            handler.wfile.write(event1[:split])
            handler.wfile.flush()
            time.sleep(0.075)
            handler.wfile.write(event1[split:-1])
            handler.wfile.flush()
            time.sleep(0.035)
            handler.wfile.write(event1[-1:] + event2)
            handler.wfile.flush()
            time.sleep(0.04)
            handler.wfile.write(done)
            handler.wfile.flush()

        with running_relay(scenario) as port:
            client, response = post(port)
            self.assertEqual(response.status, 200)
            self.assertIsNone(response.getheader("Content-Length"))
            body = response.read()
            client.close()

        self.assertIn(HEARTBEAT, body)
        self.assertEqual(body.replace(HEARTBEAT, b""), expected)
        arguments = []
        for event in body.replace(b"\r\n", b"\n").split(b"\n\n"):
            if not event:
                continue
            if event.startswith(b":"):
                self.assertEqual(event, HEARTBEAT.rstrip(b"\n"))
                continue
            self.assertTrue(event.startswith(b"data: "))
            data = event[len(b"data: "):]
            if data != b"[DONE]":
                # A heartbeat inserted inside a data line makes this invalid JSON.
                value = json.loads(data)
                arguments.append(value["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"])
        self.assertEqual(json.loads("".join(arguments)), {"name": "中文"})
        self.assertEqual(observed["authorization"], "Bearer fake-test-key")
        self.assertEqual(observed["accept_encoding"], "identity")

    def test_heartbeat_is_restricted_to_successful_requested_sse(self):
        cases = [
            (False, 200, "text/event-stream", b"data: untouched\n\n"),
            (True, 429, "application/json", b'{"error":{"message":"busy"}}'),
            (True, 502, "text/event-stream", b"upstream unavailable"),
        ]
        for stream, status, content_type, expected in cases:
            with self.subTest(stream=stream, status=status, content_type=content_type):
                def scenario(handler):
                    handler.send_response(status)
                    handler.send_header("Content-Type", content_type)
                    handler.send_header("Content-Length", str(len(expected)))
                    handler.end_headers()
                    time.sleep(0.06)
                    handler.wfile.write(expected)
                    handler.wfile.flush()

                with running_relay(scenario) as port:
                    client, response = post(port, stream=stream)
                    self.assertEqual(response.status, status)
                    self.assertEqual(response.read(), expected)
                    client.close()

    def test_client_disconnect_cancels_the_upstream(self):
        cancelled = threading.Event()

        def scenario(handler):
            begin_sse(handler)
            handler.wfile.write(b'data: {"choices":[]}\n\n')
            handler.wfile.flush()
            handler.connection.settimeout(0.8)
            try:
                if handler.connection.recv(1) == b"":
                    cancelled.set()
            except (ConnectionResetError, ConnectionAbortedError):
                cancelled.set()

        with running_relay(scenario) as port:
            client, response = post(port)
            self.assertTrue(response.read(1))
            response.close()
            client.close()
            self.assertTrue(cancelled.wait(0.6), "relay left upstream running after cancellation")

    def test_deadline_still_expires_while_heartbeats_are_flowing(self):
        cancelled = threading.Event()

        def scenario(handler):
            begin_sse(handler)
            handler.connection.settimeout(0.8)
            try:
                if handler.connection.recv(1) == b"":
                    cancelled.set()
            except (ConnectionResetError, ConnectionAbortedError):
                cancelled.set()

        with running_relay(scenario, total_timeout=0.16) as port:
            started = time.monotonic()
            client, response = post(port)
            body = response.read()
            elapsed = time.monotonic() - started
            client.close()
            self.assertTrue(cancelled.wait(0.5))

        self.assertIn(HEARTBEAT, body)
        self.assertIn("relay_deadline_exceeded", error_codes(body))
        self.assertNotIn(b"[DONE]", body)
        self.assertLess(elapsed, 0.7)

    def test_incomplete_upstream_event_is_an_error_without_a_fake_done(self):
        def scenario(handler):
            begin_sse(handler)
            handler.wfile.write(b'data: {"partial":"never completed')
            handler.wfile.flush()

        with running_relay(scenario) as port:
            client, response = post(port)
            body = response.read()
            client.close()

        self.assertIn("relay_upstream_incomplete", error_codes(body))
        self.assertNotIn(b"partial", body)
        self.assertNotIn(b"[DONE]", body)


if __name__ == "__main__":
    unittest.main()
