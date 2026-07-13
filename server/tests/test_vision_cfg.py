"""视觉复核配置解析：独立槽优先、回退旧全局兜底槽、base URL 预设。"""
from app.services import ai_synthesis_service as A


def _patch_settings(monkeypatch, values: dict):
    from app.core import hub_settings
    monkeypatch.setattr(hub_settings, "get", lambda key, default=None: values.get(key, default or ""))


def test_independent_vision_slot_wins(monkeypatch):
    _patch_settings(monkeypatch, {
        "vision_provider": "siliconflow", "vision_api_key": "vk",
        "vision_model": "Qwen/Qwen3-VL-30B-A3B-Instruct",
        # 旧槽同时存在也不该被用到
        "assistant_provider": "deepseek", "assistant_api_key": "ak",
        "assistant_vision_model": "old-model",
    })
    provider, key, base, model = A._assistant_vision_cfg()
    assert provider == "siliconflow" and key == "vk"
    assert base == "https://api.siliconflow.cn/v1"       # 空 base 按预设解析
    assert model == "Qwen/Qwen3-VL-30B-A3B-Instruct"


def test_legacy_assistant_slot_fallback(monkeypatch):
    # 独立槽未配 → 回退全局兜底 + assistant_vision_model（老用户零迁移）
    _patch_settings(monkeypatch, {
        "assistant_provider": "openrouter", "assistant_api_key": "ak",
        "assistant_model": "deepseek/deepseek-chat",
        "assistant_vision_model": "qwen/qwen2.5-vl-72b-instruct",
    })
    provider, key, base, model = A._assistant_vision_cfg()
    assert provider == "openrouter" and key == "ak"
    assert base == "https://openrouter.ai/api/v1"
    assert model == "qwen/qwen2.5-vl-72b-instruct"


def test_legacy_slot_without_vision_model_uses_text_model(monkeypatch):
    _patch_settings(monkeypatch, {
        "assistant_provider": "openai", "assistant_api_key": "ak",
        "assistant_model": "gpt-4o",
    })
    assert A._assistant_vision_cfg()[3] == "gpt-4o"


def test_non_vision_provider_rejected(monkeypatch):
    _patch_settings(monkeypatch, {
        "vision_provider": "groq", "vision_api_key": "vk", "vision_model": "x",
    })
    assert A._assistant_vision_cfg() is None


def test_unconfigured_returns_none(monkeypatch):
    _patch_settings(monkeypatch, {})
    assert A._assistant_vision_cfg() is None
