import json

import httpx
import pytest

from alicia.core.ai.providers.ollama_runtime import OllamaRuntime, is_local
from alicia.core.errors import AliciaError


class FakeServer:
    def __init__(self, up=False, models=()):
        self.up, self.models, self.pulls = up, list(models), 0

    def handler(self, request):
        if not self.up:
            raise httpx.ConnectError("refusé")
        path = request.url.path
        if path == "/api/version":
            return httpx.Response(200, json={"version": "0.12"})
        if path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": m} for m in self.models]})
        if path == "/api/pull":
            self.pulls += 1
            lines = [
                {"status": "pulling", "total": 100, "completed": 40},
                {"status": "pulling", "total": 100, "completed": 100},
                {"status": "success"},
            ]
            self.models.append(json.loads(request.content)["model"])
            return httpx.Response(200, content="\n".join(json.dumps(x) for x in lines).encode())
        return httpx.Response(404)


def runtime(server, exe="C:/Ollama/ollama.exe", **kw):
    launched = []

    def launcher(path):
        launched.append(path)
        server.up = True

        class Process:
            terminated = False

            def poll(self):
                return None

            def terminate(self):
                Process.terminated = True

        return Process()

    rt = OllamaRuntime(
        "http://127.0.0.1:11434",
        "qwen2.5vl:7b",
        transport=httpx.MockTransport(server.handler),
        launcher=launcher,
        finder=lambda: exe,
        **kw,
    )
    return rt, launched


def test_ollama_is_started_when_not_running_and_stopped_on_exit():
    server = FakeServer(up=False)
    rt, launched = runtime(server)
    assert rt.ensure_running(wait_s=2) is True and launched
    process = rt.process
    rt.stop()
    assert type(process).terminated


def test_already_running_ollama_is_left_alone():
    server = FakeServer(up=True)
    rt, launched = runtime(server)
    assert rt.ensure_running() is False and not launched
    rt.stop()  # ne touche pas à un Ollama lancé par quelqu'un d'autre


def test_missing_ollama_explains_where_to_get_it():
    rt, _ = runtime(FakeServer(up=False), exe=None)
    with pytest.raises(AliciaError) as info:
        rt.ensure_running(wait_s=0.5)
    assert "ollama.com" in info.value.user_message


def test_missing_model_is_downloaded_with_progress():
    server = FakeServer(up=True, models=["llama3:latest"])
    rt, _ = runtime(server)
    assert not rt.has_model()
    seen = []
    rt.pull(seen.append)
    assert seen == [40, 100] and rt.has_model()


def test_remote_address_is_never_started():
    assert is_local("http://localhost:11434") and not is_local("http://192.168.1.20:11434")


def test_gpu_share_tells_if_ollama_runs_on_the_processor():
    import httpx

    from alicia.core.ai.providers.ollama_runtime import OllamaRuntime

    def handler(request):
        return httpx.Response(
            200,
            json={"models": [{"name": "qwen2.5vl:7b", "size": 8_000, "size_vram": 0}]},
        )

    runtime = OllamaRuntime(
        "http://127.0.0.1:11434", "qwen2.5vl:7b", transport=httpx.MockTransport(handler)
    )
    assert runtime.gpu_share() == 0.0


def test_ollama_never_takes_every_core():
    from alicia.core.ai.providers.ollama import default_threads

    assert 2 <= default_threads() <= 6


def test_unload_frees_only_our_loaded_models():
    posted = []

    def handler(request):
        if request.url.path == "/api/ps":
            return httpx.Response(
                200, json={"models": [{"name": "qwen2.5vl:7b"}, {"name": "x:1b"}]}
            )
        posted.append(json.loads(request.content))
        return httpx.Response(200, json={})

    runtime = OllamaRuntime(
        "http://127.0.0.1:11434", "qwen2.5vl:7b", transport=httpx.MockTransport(handler)
    )
    assert runtime.unload(["qwen2.5vl:7b", "qwen3.8:27b", "qwen2.5vl:7b"]) == ["qwen2.5vl:7b"]
    assert posted == [{"model": "qwen2.5vl:7b", "keep_alive": 0}]

    def down(request):
        raise httpx.ConnectError("Ollama fermé")

    closed = OllamaRuntime("http://127.0.0.1:11434", "m", transport=httpx.MockTransport(down))
    assert closed.unload(["m"]) == []
