# -*- coding: utf-8 -*-
"""AI 助手编排逻辑单测：用假 LLM 覆盖 supervisor 路由解析、三级降级与整图流程。"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from app.agents.graph import (
    DEFAULT_FINISH_REPLY,
    AgentState,
    _keyword_route,
    _make_finalize,
    _make_supervisor,
    _parse_supervisor_output,
)
from app.agents.text_utils import loads_first_json, strip_think


class FakeStructured:
    """模拟 llm.with_structured_output(...) 的可调用对象。"""

    def __init__(self, parent: "FakeLLM"):
        self.parent = parent

    def invoke(self, messages):
        self.parent.structured_calls += 1
        if self.parent.exc is not None:
            raise self.parent.exc
        return {
            "raw": AIMessage(content=self.parent.content or ""),
            "parsed": self.parent.structured,
            "parsing_error": None,
        }


class FakeLLM:
    """假模型，可分别模拟：function calling 成功/失败、纯文本输出、直接抛异常。"""

    def __init__(self, content: str | None = None, exc: Exception | None = None, structured: dict | None = None):
        self.content = content
        self.exc = exc
        self.structured = structured
        self.structured_calls = 0
        self.text_calls = 0

    def with_structured_output(self, schema, method=None, include_raw=False):
        return FakeStructured(self)

    def invoke(self, messages):
        self.text_calls += 1
        if self.exc is not None:
            raise self.exc
        return AIMessage(content=self.content or "")


def _build_fake_graph(llm, anomaly_reply: str = "已为您查询该订单的配送轨迹。"):
    """与 build_graph 结构一致，但把 anomaly_agent 换成固定回复的假节点。"""

    def fake_anomaly(state):
        return {"messages": [AIMessage(content=anomaly_reply)]}

    builder = StateGraph(AgentState)
    builder.add_node("supervisor", _make_supervisor(llm))
    builder.add_node("anomaly_agent", fake_anomaly)
    builder.add_node("finalize", _make_finalize())
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        lambda state: state.get("next") or "FINISH",
        {"anomaly_agent": "anomaly_agent", "FINISH": "finalize"},
    )
    builder.add_edge("anomaly_agent", "supervisor")
    builder.add_edge("finalize", END)
    return builder.compile()


# ---------------- 文本工具 ----------------

def test_strip_think_removes_block():
    assert strip_think("<think>先想想</think>你好") == "你好"


def test_strip_think_removes_unclosed_block():
    assert strip_think("<think>想到一半被截断") == ""


def test_strip_think_keeps_plain_text():
    assert strip_think("普通回复") == "普通回复"


def test_loads_first_json_skips_think_noise():
    text = '<think>这里出现 {假 JSON}</think> 真正输出：{"next": "FINISH"}'
    assert loads_first_json(strip_think(text)) == {"next": "FINISH"}


def test_loads_first_json_returns_none_for_garbage():
    assert loads_first_json("完全不是 JSON") is None


# ---------------- 解析层 ----------------

def test_parse_plain_json():
    assert _parse_supervisor_output('{"next": "anomaly_agent", "reply": "好的"}') == (
        "anomaly_agent",
        "好的",
    )


def test_parse_fenced_json():
    text = '```json\n{"next": "FINISH", "reply": "我只处理配送问题"}\n```'
    assert _parse_supervisor_output(text) == ("FINISH", "我只处理配送问题")


def test_parse_json_with_extra_text():
    text = '好的，我来处理。{"next": "anomaly_agent", "reply": "稍等"}'
    assert _parse_supervisor_output(text) == ("anomaly_agent", "稍等")


def test_parse_json_with_think_prefix():
    text = '<think>模型思考过程</think>{"next": "anomaly_agent", "reply": "稍等"}'
    assert _parse_supervisor_output(text) == ("anomaly_agent", "稍等")


def test_parse_garbage_returns_none():
    assert _parse_supervisor_output("今天天气不错") == (None, "")


def test_parse_empty_returns_none():
    assert _parse_supervisor_output("") == (None, "")


def test_parse_invalid_route_falls_back_to_finish():
    assert _parse_supervisor_output('{"next": "weather_agent", "reply": "x"}')[0] == "FINISH"


def test_parse_missing_reply():
    assert _parse_supervisor_output('{"next": "FINISH"}') == ("FINISH", "")


# ---------------- 关键词兜底层 ----------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("我的外卖丢失了，订单号 A1", "anomaly_agent"),
        ("一直没收到我的餐", "anomaly_agent"),
        ("骑手说送到了但没送达寝室", "anomaly_agent"),
        ("我要投诉这个餐品", "anomaly_agent"),
        ("今天天气怎么样", "FINISH"),
        ("", "FINISH"),
    ],
)
def test_keyword_route(text, expected):
    assert _keyword_route(text) == expected


# ---------------- supervisor 节点 ----------------

def test_supervisor_uses_function_calling_first():
    llm = FakeLLM(structured={"next": "anomaly_agent", "reply": "稍等"})
    supervisor = _make_supervisor(llm)
    out = supervisor({"messages": [HumanMessage("我的外卖丢了")], "routed": False})
    assert out["next"] == "anomaly_agent"
    assert out["reply"] == "稍等"
    assert llm.structured_calls == 1
    assert llm.text_calls == 0  # function calling 成功就不再走文本协议


def test_supervisor_falls_back_to_text_json():
    llm = FakeLLM(content='{"next": "FINISH", "reply": "我只帮您处理配送问题。"}')
    supervisor = _make_supervisor(llm)
    out = supervisor({"messages": [HumanMessage("今天天气如何")], "routed": False})
    assert out["next"] == "FINISH"
    assert out["reply"] == "我只帮您处理配送问题。"


def test_supervisor_finish_gets_default_reply():
    llm = FakeLLM(structured={"next": "FINISH", "reply": ""})
    supervisor = _make_supervisor(llm)
    out = supervisor({"messages": [HumanMessage("你好")], "routed": False})
    assert out["next"] == "FINISH"
    assert out["reply"] == DEFAULT_FINISH_REPLY


def test_supervisor_llm_error_falls_back_to_keyword():
    llm = FakeLLM(exc=RuntimeError("boom"))
    supervisor = _make_supervisor(llm)
    out = supervisor({"messages": [HumanMessage("我的外卖没收到")], "routed": False})
    assert out["next"] == "anomaly_agent"


def test_supervisor_unparsable_falls_back_to_keyword():
    llm = FakeLLM("随便说点什么")
    supervisor = _make_supervisor(llm)
    out = supervisor({"messages": [HumanMessage("外卖送错了")], "routed": False})
    assert out["next"] == "anomaly_agent"


def test_supervisor_no_tool_call_no_json_falls_back_to_keyword():
    """模型既没返回 tool_calls、也没输出 JSON —— 正是旧版 500 的场景。"""
    llm = FakeLLM(content="<think>让我想想……</think>")
    supervisor = _make_supervisor(llm)
    out = supervisor({"messages": [HumanMessage("我的外卖没收到")], "routed": False})
    assert out["next"] == "anomaly_agent"
    assert out["reply"] == ""


def test_supervisor_accepts_pydantic_parsed():
    """真实实现里 with_structured_output 返回的是 Pydantic 实例，要能正确取字段。"""
    from app.agents.graph import Router

    llm = FakeLLM(structured=Router(next="anomaly_agent", reply="稍等"))
    supervisor = _make_supervisor(llm)
    out = supervisor({"messages": [HumanMessage("我的外卖丢了")], "routed": False})
    assert out["next"] == "anomaly_agent"
    assert out["reply"] == "稍等"


def test_supervisor_does_not_loop_when_already_routed():
    llm = FakeLLM(structured={"next": "anomaly_agent", "reply": "x"})
    supervisor = _make_supervisor(llm)
    out = supervisor(
        {
            "messages": [HumanMessage("我的外卖丢了"), AIMessage("已处理")],
            "routed": True,
        }
    )
    assert out["next"] == "FINISH"
    assert llm.structured_calls == 0
    assert llm.text_calls == 0


def test_supervisor_reroutes_on_new_turn_after_reset():
    llm = FakeLLM(structured={"next": "anomaly_agent", "reply": "x"})
    supervisor = _make_supervisor(llm)
    out = supervisor({"messages": [HumanMessage("我的外卖丢了")], "routed": False})
    assert out["next"] == "anomaly_agent"
    out2 = supervisor({"messages": [HumanMessage("我的外卖丢了")], "routed": False})
    assert out2["next"] == "anomaly_agent"


# ---------------- 整图流程 ----------------

def test_graph_finish_path_returns_reply():
    graph = _build_fake_graph(FakeLLM(structured={"next": "FINISH", "reply": "我只帮您处理配送问题。"}))
    result = graph.invoke({"messages": [HumanMessage("今天天气如何")]})
    assert result["messages"][-1].content == "我只帮您处理配送问题。"


def test_graph_finish_path_default_reply():
    graph = _build_fake_graph(FakeLLM(exc=RuntimeError("网络异常")))
    result = graph.invoke({"messages": [HumanMessage("今天天气如何")]})
    assert result["messages"][-1].content == DEFAULT_FINISH_REPLY


def test_graph_anomaly_path_keeps_sub_agent_reply():
    graph = _build_fake_graph(FakeLLM(structured={"next": "anomaly_agent", "reply": "稍等"}))
    result = graph.invoke({"messages": [HumanMessage("我的外卖丢了")]})
    ai_messages = [m for m in result["messages"] if getattr(m, "type", None) == "ai"]
    assert len(ai_messages) == 1
    assert ai_messages[0].content == "已为您查询该订单的配送轨迹。"


def test_graph_never_raises_on_bad_model_output():
    graph = _build_fake_graph(FakeLLM(content="完全不相关的输出"))
    result = graph.invoke({"messages": [HumanMessage("我的外卖没收到")]})
    assert result["messages"][-1].content


def test_graph_strips_think_from_final_reply():
    graph = _build_fake_graph(
        FakeLLM(structured={"next": "FINISH", "reply": "<think>内部思考</think>正式回复"})
    )
    result = graph.invoke({"messages": [HumanMessage("今天天气如何")]})
    assert result["messages"][-1].content == "正式回复"


# ---------------- 异常应急 Agent 的兜底 ----------------

def test_anomaly_agent_wrapper_swallows_model_errors(monkeypatch):
    """模型/工具异常时，异常应急 Agent 应降级为说明性回复，而不是把异常抛到上层。"""
    import app.agents.agents.anomaly_agent as mod

    class Boom:
        def invoke(self, state):
            raise RuntimeError("模型不可用")

    monkeypatch.setattr(mod, "create_react_agent", lambda *a, **k: Boom())
    node = mod.build_anomaly_agent()
    out = node({"messages": [HumanMessage("我的外卖丢了")]})
    content = out["messages"][-1].content
    assert mod.AGENT_ERROR_REPLY in content


def test_anomaly_agent_wrapper_passes_through_normal_result(monkeypatch):
    import app.agents.agents.anomaly_agent as mod

    class Ok:
        def invoke(self, state):
            return {"messages": [AIMessage(content="已为您查询轨迹。")]}

    monkeypatch.setattr(mod, "create_react_agent", lambda *a, **k: Ok())
    node = mod.build_anomaly_agent()
    out = node({"messages": [HumanMessage("我的外卖丢了")]})
    assert out["messages"][-1].content == "已为您查询轨迹。"