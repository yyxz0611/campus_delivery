from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agents.agents.ops_agent import _extract_table, _last_user_text
from app.agents.graph import Router, VALID_ROUTES, _keyword_route


def test_router_accepts_ops_route() -> None:
    assert "ops_agent" in VALID_ROUTES
    router = Router(next="ops_agent", reply="好的")
    assert router.next == "ops_agent"


def test_statistics_question_routes_to_ops() -> None:
    assert _keyword_route("上周各楼栋超时订单数量") == "ops_agent"
    assert _keyword_route("异常类型分布") == "ops_agent"
    assert _keyword_route("订单状态分布") == "ops_agent"


def test_delivery_issue_routes_to_anomaly() -> None:
    assert _keyword_route("我的外卖丢了") == "anomaly_agent"
    assert _keyword_route("餐没收到怎么办") == "anomaly_agent"


def test_unrelated_question_finishes() -> None:
    assert _keyword_route("今天天气怎么样") == "FINISH"
    assert _keyword_route("") == "FINISH"


def test_extract_table_from_tool_message() -> None:
    payload = (
        '{"summary":"超时单量合计 9 单","intent":"各楼栋超时统计",'
        '"columns":["dorm_building","overdue_total"],'
        '"column_labels":["宿舍楼栋","超时单量"],'
        '"rows":[{"dorm_building":"竹园","overdue_total":3}],'
        '"overview":{"total":9}}'
    )
    message = ToolMessage(content=payload, tool_call_id="call_1")
    table = _extract_table([message])
    assert table is not None
    assert table["rows"] == [{"dorm_building": "竹园", "overdue_total": 3}]
    assert table["column_labels"] == ["宿舍楼栋", "超时单量"]
    assert table["summary"].startswith("超时单量")


def test_extract_table_ignores_error_payload() -> None:
    message = ToolMessage(content='{"error":"运营统计仅管理员可用"}', tool_call_id="call_2")
    assert _extract_table([message]) is None


def test_extract_table_ignores_non_json() -> None:
    message = ToolMessage(content="这不是 JSON", tool_call_id="call_3")
    assert _extract_table([message]) is None


def test_last_user_text_picks_latest_user_message() -> None:
    messages = [
        HumanMessage(content="第一句"),
        AIMessage(content="好的"),
        HumanMessage(content="各楼栋超时订单数量"),
    ]
    assert _last_user_text(messages) == "各楼栋超时订单数量"