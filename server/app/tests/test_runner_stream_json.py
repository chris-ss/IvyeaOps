"""ivyea-agent stream-json runner 升级：argv 探测门控 + NDJSON 解析。"""
from __future__ import annotations

import json

from app.services import runners


def _ndjson(*events) -> str:
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n"


_INIT = {"type": "system", "subtype": "init", "session_id": "sid-1", "model": "deepseek-chat",
         "tools": ["run_patrol"], "permissionMode": "acceptEdits"}
_TOOL = {"type": "assistant", "session_id": "sid-1", "message": {"role": "assistant", "content": [
    {"type": "tool_use", "id": "c1", "name": "run_patrol", "input": {"asin": "B0X"}}]}}
_TOOL_RES = {"type": "user", "session_id": "sid-1", "message": {"role": "user", "content": [
    {"type": "tool_result", "tool_use_id": "c1", "content": "巡检完成", "is_error": False}]}}
_FINAL = {"type": "assistant", "session_id": "sid-1", "message": {"role": "assistant", "content": [
    {"type": "text", "text": "# 报告\n结论"}]}}
_RESULT = {"type": "result", "subtype": "success", "is_error": False, "result": "# 报告\n结论",
           "session_id": "sid-1", "total_cost_cny": 0.0149,
           "usage": {"input_tokens": 100, "output_tokens": 50}}


def test_extract_stream_json_output():
    raw = _ndjson(_INIT, _TOOL, _TOOL_RES, _FINAL, _RESULT)
    out = runners.extract_runner_output("ivyea-agent", raw)
    assert out["structured"] is True
    assert out["text"] == "# 报告\n结论"
    assert out["cost_cny"] == 0.0149
    assert out["session_id"] == "sid-1"
    kinds = [e["type"] for e in out["events"]]
    assert kinds == ["tool_use", "tool_result", "text"]
    assert out["events"][0]["name"] == "run_patrol"


def test_extract_plain_text_passthrough():
    """旧版 ivyea / 其它 runner 的纯文本输出原样透传。"""
    raw = "# 报告\n这是纯文本输出"
    out = runners.extract_runner_output("ivyea-agent", raw)
    assert out["structured"] is False and out["text"] == raw
    out2 = runners.extract_runner_output("hermes", _ndjson(_INIT, _RESULT))
    assert out2["structured"] is False              # 非 ivyea runner 不解析


def test_extract_tolerates_noise_lines():
    """stderr 混入的非 JSON 行（告警/traceback）不影响解析。"""
    raw = "WARNING: something\n" + _ndjson(_INIT) + "垃圾行\n" + _ndjson(_FINAL, _RESULT)
    out = runners.extract_runner_output("ivyea-agent", raw)
    assert out["structured"] is True and out["text"] == "# 报告\n结论"


def test_extract_no_result_event_falls_back():
    """有 init 但进程中途死掉没 result → 原文透传（调用方按原逻辑处理）。"""
    raw = _ndjson(_INIT, _TOOL)
    out = runners.extract_runner_output("ivyea-agent", raw)
    assert out["structured"] is False and out["text"] == raw


def test_parser_incremental_progress():
    """增量喂 chunk：tool_use 事件实时更新 progress（供 job.progress 展示）。"""
    p = runners.IvyeaStreamJsonParser()
    raw = _ndjson(_INIT, _TOOL, _TOOL_RES, _RESULT)
    mid = len(raw) // 2
    p.feed(raw[:mid])
    p.feed(raw[mid:])
    p.close()
    assert p.progress == "正在调用 run_patrol…"
    assert p.session_id == "sid-1"
    assert p.result_event is not None and p.cost_cny == 0.0149


def test_build_runner_cmd_stream_json_gated_on_help(monkeypatch):
    """新版 CLI（help 有 --output-format）加 stream-json；旧版回退纯文本。"""
    monkeypatch.setattr(runners, "_ivyea_chat_help",
                        lambda b: "--output-format {text,stream-json} --permission-mode")
    argv = runners._build_runner_cmd("ivyea-agent", "/usr/bin/ivyea", "查广告")
    assert "--output-format" in argv and "stream-json" in argv
    assert "--approve-all" in argv                  # 默认档保持历史行为
    monkeypatch.setattr(runners, "_ivyea_chat_help", lambda b: "old help without new flags")
    argv_old = runners._build_runner_cmd("ivyea-agent", "/usr/bin/ivyea", "查广告")
    assert "--output-format" not in argv_old and "--approve-all" in argv_old


def test_build_runner_cmd_policy_mode_env(monkeypatch):
    monkeypatch.setattr(runners, "_ivyea_chat_help",
                        lambda b: "--output-format --permission-mode {default,policy,approve-all}")
    monkeypatch.setenv("IVYEA_OPS_IVYEA_PERMISSION_MODE", "policy")
    argv = runners._build_runner_cmd("ivyea-agent", "/usr/bin/ivyea", "查广告")
    assert "--permission-mode" in argv and "policy" in argv and "--approve-all" not in argv
