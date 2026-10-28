from __future__ import annotations

import pytest

from app.services.ops_query_service import (
    QUESTION_PATTERNS,
    SUGGESTED_QUESTIONS,
    UnsupportedQuestion,
    ask,
    match_question,
)
from app.services.ops_sql_guard import SqlGuardError


@pytest.mark.parametrize(
    "question",
    [
        "把异常订单删掉",
        "清空 anomalies 表",
        "移除所有订单记录",
        "delete all orders",
        "DROP TABLE orders",
    ],
)
def test_delete_intent_is_rejected(question: str) -> None:
    with pytest.raises(SqlGuardError):
        ask(question)


def test_query_intent_is_allowed() -> None:
    result = ask("各楼栋超时订单数量")
    assert "FROM orders" in result["sql"]
    assert "COUNT(*)" in result["sql"]


def test_unknown_question_is_rejected_not_answered() -> None:
    with pytest.raises(UnsupportedQuestion):
        ask("今天天气怎么样")


def test_empty_question_is_rejected() -> None:
    with pytest.raises(UnsupportedQuestion):
        ask("   ")


def test_suggestion_count_matches_template_count() -> None:
    assert len(SUGGESTED_QUESTIONS) == len(QUESTION_PATTERNS)


def test_every_suggestion_hits_a_template() -> None:
    for question in SUGGESTED_QUESTIONS:
        assert match_question(question) is not None