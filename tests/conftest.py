"""A fake /mcp/cad transport answering from ``fixtures/*.json`` (the core's fixtures: JSON-RPC answers in the
server's shapes, written by hand), and a private config folder per test."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Optional

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from makepartsnow import cli  # noqa: E402
from makepartsnow.core.client import HttpResponse  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def structured(content: dict[str, Any]) -> dict[str, Any]:
    """A tools/call answer carrying ``content`` as structuredContent."""
    return {"jsonrpc": "2.0", "id": 0, "result": {"isError": False, "content": [{"type": "text", "text": json.dumps(content)}],
                                                  "structuredContent": content}}


class FakeTransport:
    """Answers /mcp/cad calls from queued fixtures and records every request. ``queue(tool, *answers)``: a fixture name,
    a dict (a JSON-RPC message) or an exception; the last answer for a tool repeats."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.answers: dict[str, list[Any]] = {}
        self.put_bodies: list[bytes] = []

    def queue(self, tool: str, *answers: Any) -> "FakeTransport":
        self.answers.setdefault(tool, []).extend(answers)
        return self

    def tool_calls(self, name: Optional[str] = None) -> list[dict[str, Any]]:
        return [c for c in self.calls if c.get("tool") and (name is None or c["tool"] == name)]

    def __call__(self, method: str, url: str, headers: Mapping[str, str], body: Optional[bytes], timeout: float) -> HttpResponse:
        call: dict[str, Any] = {"method": method, "url": url, "headers": dict(headers)}
        self.calls.append(call)
        if method == "PUT":
            self.put_bodies.append(body or b"")
            return HttpResponse(201, {"content-type": "application/json"}, b'{"ok": true}')
        message = json.loads(body or b"{}")
        if message.get("method") == "notifications/initialized":
            return HttpResponse(202, {}, b"")
        if message.get("method") == "initialize":
            data = load_fixture("initialize")
        else:
            name = message["params"]["name"]
            call["tool"], call["arguments"] = name, message["params"].get("arguments", {})
            queued = self.answers.get(name)
            if name == "create_upload_links" and not queued:  # one signed link per requested file
                count = int(call["arguments"].get("count", 1))
                queued = [structured({"uploads": [{"upload_id": f"upl_{i}", "put_url": f"https://makepartsnow.com/api/agent/v1/uploads/signed/tok-{i}",
                                                   "expires_at": "2026-10-18T22:00:00Z"} for i in range(count)]})]
            if not queued:
                raise AssertionError(f"no answer queued for {name}")
            answer = queued.pop(0) if len(queued) > 1 else queued[0]
            if isinstance(answer, Exception):
                raise answer
            data = load_fixture(answer) if isinstance(answer, str) else dict(answer)
        data["id"] = message.get("id")
        return HttpResponse(200, {"content-type": "application/json"}, json.dumps(data).encode())


@pytest.fixture(autouse=True)
def config(tmp_path, monkeypatch):
    folder = tmp_path / "config"
    monkeypatch.setenv("MPN_CONFIG_DIR", str(folder))
    monkeypatch.delenv("MPN_BASE_URL", raising=False)
    monkeypatch.delenv("MPN_ACCEPT", raising=False)
    return folder


@pytest.fixture
def transport():
    return FakeTransport().queue("get_options", "get_options_materials")


class Run:
    def __init__(self, code: int, out: str, err: str) -> None:
        self.code, self.out, self.err = code, out, err

    @property
    def json(self) -> Any:
        return json.loads(self.out)


def run(transport: Any, *argv: str, answers: tuple[str, ...] = (), interactive: bool = False) -> Run:
    stdout, stderr = io.StringIO(), io.StringIO()
    replies = list(answers)
    code = cli.main(list(argv), transport=transport, stdout=stdout, stderr=stderr,
                    ask=lambda _prompt: replies.pop(0), interactive=interactive)
    return Run(code, stdout.getvalue(), stderr.getvalue())
