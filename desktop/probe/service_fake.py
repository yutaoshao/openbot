"""Loopback-only fake OpenAI endpoint for service-path validation."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPLY = "Inverse kinematics finds joint angles for a desired end-effector pose."


def completion_text(payload: dict) -> str:
    system = "\n".join(
        str(message.get("content", ""))
        for message in payload["messages"]
        if message.get("role") == "system"
    )
    if "required_actions" in system:
        return json.dumps({"confidence": 1.0, "required_actions": ["answer"]})
    context = "\n".join(str(message.get("content", "")) for message in payload["messages"])
    if "JSON 数组" in context or "json array" in context.lower():
        return "[]"
    return REPLY


class FakeOpenAI(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        self.requests = 0
        super().__init__(("127.0.0.1", 0), FakeHandler)
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.shutdown()
        self.server_close()
        self.thread.join(timeout=2)


class FakeHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        pass

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract.
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests += 1
        if payload.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for delta, finish in [({"role": "assistant", "content": REPLY}, None), ({}, "stop")]:
                chunk = {
                    "id": "synthetic",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "openbot-service-probe",
                    "choices": [
                        {"index": 0, "delta": delta, "finish_reason": finish},
                    ],
                }
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        response = {
            "id": "synthetic",
            "object": "chat.completion",
            "created": 1,
            "model": "openbot-service-probe",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": completion_text(payload)},
                    "finish_reason": "stop",
                },
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 16, "total_tokens": 26},
        }
        body = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
