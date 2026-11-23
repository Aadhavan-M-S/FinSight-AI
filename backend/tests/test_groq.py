import json

import httpx
from groq import Groq

from app import generation


def test_sdk_model_discovery_retry_and_validation(monkeypatch):
    calls = []
    model = "test-model"
    quote = "The filing disclosed supplier concentration."

    def handle(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200, json={"data": [{"id": model, "object": "model", "created": 0, "owned_by": "test"}]}
            )
        if calls.count(request.url.path) == 1:
            return httpx.Response(
                429, headers={"retry-after": "0"}, json={"error": {"message": "test throttle"}}
            )
        body = json.loads(request.content)
        assert body["model"] == model
        assert body["response_format"] == {"type": "json_object"}
        assert body["messages"][0]["role"] == "system"
        assert quote in body["messages"][1]["content"]
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 0,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "claims": [
                                        {
                                            "evidence_id": "test-id",
                                            "text": quote,
                                            "quote": quote,
                                        }
                                    ]
                                }
                            ),
                        },
                    }
                ],
            },
        )

    transport = httpx.MockTransport(handle)
    with httpx.Client(transport=transport) as client:
        sdk = Groq(api_key="offline-test-only", http_client=client, max_retries=0)
        monkeypatch.setattr(generation, "Groq", lambda **_: sdk)
        monkeypatch.setattr(generation.settings, "groq_api_key", "offline-test-only")
        monkeypatch.setattr(generation.settings, "groq_model", model)
        monkeypatch.setattr(generation.time, "sleep", lambda _: None)
        provider = generation.GroqProvider()
        excerpts = [{"id": "test-id", "text": quote}]
        result = provider.generate("What risk was disclosed?", excerpts)
    assert len(generation.verified_claims(result, excerpts)) == 1
    assert calls == ["/openai/v1/models", "/openai/v1/chat/completions", "/openai/v1/chat/completions"]
