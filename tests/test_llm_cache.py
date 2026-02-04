"""Tests for the LLM response cache."""

from aurelia.llm.cache import LLMCache


class TestStoreAndLookup:
    async def test_round_trip(self, tmp_path):
        cache = LLMCache(tmp_path)
        h = cache.request_hash("model-a", [{"role": "user"}], {}, [])
        response = {"text": "hello world"}
        await cache.store(h, response, {"model": "model-a"})

        result = await cache.lookup(h)
        assert result == response

    async def test_miss_returns_none(self, tmp_path):
        cache = LLMCache(tmp_path)
        assert await cache.lookup("nonexistent_hash") is None


class TestHashDeterminism:
    def test_same_inputs_same_hash(self):
        cache = LLMCache(None)  # type: ignore[arg-type]
        contents = [{"role": "user", "parts": [{"text": "hi"}]}]
        config = {"temperature": 0.0}
        tools = [{"name": "read_file"}]

        h1 = cache.request_hash("gemini-2.5-flash", contents, config, tools)
        h2 = cache.request_hash("gemini-2.5-flash", contents, config, tools)
        assert h1 == h2

    def test_different_model_different_hash(self):
        cache = LLMCache(None)  # type: ignore[arg-type]
        contents = [{"role": "user"}]
        h1 = cache.request_hash("model-a", contents, {}, [])
        h2 = cache.request_hash("model-b", contents, {}, [])
        assert h1 != h2

    def test_different_contents_different_hash(self):
        cache = LLMCache(None)  # type: ignore[arg-type]
        h1 = cache.request_hash("m", [{"role": "user"}], {}, [])
        h2 = cache.request_hash("m", [{"role": "assistant"}], {}, [])
        assert h1 != h2

    def test_different_config_different_hash(self):
        cache = LLMCache(None)  # type: ignore[arg-type]
        h1 = cache.request_hash("m", [], {"temperature": 0.0}, [])
        h2 = cache.request_hash("m", [], {"temperature": 1.0}, [])
        assert h1 != h2

    def test_different_tools_different_hash(self):
        cache = LLMCache(None)  # type: ignore[arg-type]
        h1 = cache.request_hash("m", [], {}, [{"name": "a"}])
        h2 = cache.request_hash("m", [], {}, [{"name": "b"}])
        assert h1 != h2
