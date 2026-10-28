"""运营分析语义层：orders / anomalies 两表的中文字段、枚举全集与指标口径。

事实来源：2026-10-27 用 campus-db MCP 对 campus_delivery.db 实测
（list_tables / describe_table / run_readonly_query），不采信 ORM 注释推断。
当前覆盖 orders（17 列）与 anomalies（14 列），其余 10 张表待后续追加。
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

from app.constants import NODE_LABELS


ROLE_LABELS: Final[dict[str, str]] = {
    "key": "主键",
    "identifier": "业务标识",
    "dimension": "维度",
    "time": "时间",
    "measure": "度量",
    "flag": "标记",
    "payload": "明细文本",
    "sensitive": "敏感字段",
    "link": "外键",
    "geo": "坐标",
}

SENSITIVE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "orders.customer_name",
        "orders.customer_phone",
        "orders.vendor_phone",
        "orders.dorm_room",
        "anomalies.reported_by",
    }
)

DIMENSION_NORMALIZATION: Final[dict[str, dict[str, str]]] = {
    "orders.dorm_building": {
        "梅园1栋": "梅园",
        "致远居1栋": "致远居",
    }
}

ENUM_ORDER_STATUS: Final[dict[str, Any]] = {
    "label": "订单状态",
    "column": "orders.status",
    "description": "前 7 个为线性流程态，abnormal 为旁路异常态，不得视为 dorm_delivery 之后的一步。",
    "values": {
        "pending": {"label": "待配送", "stage": 1, "is_completed": False, "off_flow": False},
        "picked": {"label": "已取餐", "stage": 2, "is_completed": False, "off_flow": False},
        "handover": {"label": "已交接", "stage": 3, "is_completed": False, "off_flow": False},
        "in_campus": {"label": "校内运输中", "stage": 4, "is_completed": False, "off_flow": False},
        "arrived_site": {"label": "已达楼下站点", "stage": 5, "is_completed": False, "off_flow": False},
        "dorm_delivery": {"label": "配送中", "stage": 6, "is_completed": False, "off_flow": False},
        "delivered": {"label": "已到寝完成", "stage": 7, "is_completed": True, "off_flow": False},
        "abnormal": {"label": "异常", "stage": None, "is_completed": False, "off_flow": True},
    },
    "reserved": {
        "cancelled": "constants.py 预留标签，库中 0 条且无写入路径，不得作为查询条件生成。",
    },
}

SEMANTIC_ENUMS: Final[dict[str, dict[str, Any]]] = {
    "order_status": ENUM_ORDER_STATUS,
    "order_source": {
        "label": "订单录入来源",
        "column": "orders.source",
        "values": {
            "ocr": {"label": "小票 OCR 自动录入"},
            "manual": {"label": "人工手动录入"},
        },
    },
    "anomaly_type": {
        "label": "异常类型",
        "column": "anomalies.anomaly_type",
        "values": {
            "lost": {"label": "外卖丢失"},
            "not_delivered": {"label": "未配送到寝"},
        },
    },
    "anomaly_status": {
        "label": "异常处理状态",
        "column": "anomalies.status",
        "values": {
            "pending": {"label": "待处理"},
            "investigating": {"label": "核查中"},
            "located": {"label": "已定位环节"},
            "compensated": {"label": "已补偿"},
            "resolved": {"label": "已解决"},
        },
        "observed_in_db": ["investigating", "resolved"],
        "description": "五态全集来自 models.py 与 constants.py；当前库仅出现 observed_in_db 两个，其余为合法状态但尚无数据。",
    },
    "reported_role": {
        "label": "异常上报人角色",
        "column": "anomalies.reported_role",
        "values": {
            "admin": {"label": "管理员"},
            "rider": {"label": "骑手"},
            "student": {"label": "学生"},
        },
        "missing_value": {
            "": "历史数据未记录上报角色，统计时单列为「未知」，不得归入任何角色。",
        },
    },
    "node_type": {
        "label": "配送节点类型",
        "column": "anomalies.located_node_type",
        "values": {value: {"label": label} for value, label in NODE_LABELS.items()},
        "description": "与 delivery_nodes.node_type 同一套枚举，可用于说明异常卡在哪一环。",
    },
}

SEMANTIC_TABLES: Final[dict[str, dict[str, Any]]] = {
    "orders": {
        "label": "外卖订单",
        "description": "履约主实体，一单一行；按楼栋、时间、状态聚合的主要数据源。",
        "primary_key": "id",
        "fields": [
            {"name": "id", "type": "INTEGER", "label": "订单 ID", "role": "key", "nullable": False},
            {"name": "order_no", "type": "VARCHAR(64)", "label": "订单号", "role": "identifier", "nullable": False},
            {"name": "customer_name", "type": "VARCHAR(64)", "label": "顾客姓名", "role": "sensitive", "nullable": False},
            {"name": "customer_phone", "type": "VARCHAR(32)", "label": "顾客手机号", "role": "sensitive", "nullable": False},
            {
                "name": "dorm_building",
                "type": "VARCHAR(64)",
                "label": "宿舍楼栋",
                "role": "dimension",
                "nullable": False,
                "normalization": DIMENSION_NORMALIZATION["orders.dorm_building"],
                "normalization_note": "园区名与「园区+楼栋」两种写法并存：梅园/梅园1栋、致远居1栋。按园区粒度汇总时先归一，按楼栋粒度时不归一。",
            },
            {"name": "dorm_room", "type": "VARCHAR(32)", "label": "寝室号", "role": "sensitive", "nullable": False},
            {"name": "vendor_name", "type": "VARCHAR(64)", "label": "商家名称", "role": "dimension", "nullable": False},
            {"name": "vendor_phone", "type": "VARCHAR(32)", "label": "商家电话", "role": "sensitive", "nullable": False},
            {"name": "food_items", "type": "TEXT", "label": "商品明细", "role": "payload", "nullable": False},
            {"name": "status", "type": "VARCHAR(32)", "label": "订单状态", "role": "dimension", "enum": "order_status", "nullable": False},
            {"name": "longitude", "type": "FLOAT", "label": "收货经度", "role": "geo", "nullable": True},
            {"name": "latitude", "type": "FLOAT", "label": "收货纬度", "role": "geo", "nullable": True},
            {"name": "created_at", "type": "DATETIME", "label": "下单时间", "role": "time", "nullable": False},
            {"name": "expected_delivery_at", "type": "DATETIME", "label": "承诺送达时间", "role": "time", "nullable": True},
            {"name": "delivered_at", "type": "DATETIME", "label": "实际送达时间", "role": "time", "nullable": True},
            {"name": "source", "type": "VARCHAR(16)", "label": "录入来源", "role": "dimension", "enum": "order_source", "nullable": False},
            {"name": "rider_user_id", "type": "INTEGER", "label": "骑手用户 ID", "role": "link", "nullable": True},
        ],
    },
    "anomalies": {
        "label": "配送异常",
        "description": "异常上报与处置闭环，一条异常一行；本身无楼栋字段，按楼栋统计须关联 orders。",
        "primary_key": "id",
        "fields": [
            {"name": "id", "type": "INTEGER", "label": "异常 ID", "role": "key", "nullable": False},
            {"name": "order_id", "type": "INTEGER", "label": "关联订单 ID", "role": "link", "nullable": False, "references": "orders.id"},
            {"name": "anomaly_type", "type": "VARCHAR(32)", "label": "异常类型", "role": "dimension", "enum": "anomaly_type", "nullable": False},
            {"name": "reported_at", "type": "DATETIME", "label": "上报时间", "role": "time", "nullable": False},
            {"name": "reported_by", "type": "VARCHAR(64)", "label": "上报人姓名", "role": "sensitive", "nullable": False},
            {"name": "reported_by_user_id", "type": "INTEGER", "label": "上报人用户 ID", "role": "link", "nullable": True},
            {"name": "reported_role", "type": "VARCHAR(16)", "label": "上报人角色", "role": "dimension", "enum": "reported_role", "nullable": False},
            {"name": "description", "type": "TEXT", "label": "异常描述", "role": "payload", "nullable": False},
            {"name": "status", "type": "VARCHAR(32)", "label": "处理状态", "role": "dimension", "enum": "anomaly_status", "nullable": False},
            {"name": "located_node_type", "type": "VARCHAR(32)", "label": "定位到的节点", "role": "dimension", "enum": "node_type", "nullable": True},
            {"name": "handle_log", "type": "JSON", "label": "处理日志", "role": "payload", "nullable": False},
            {"name": "compensation_granted", "type": "BOOLEAN", "label": "是否已补偿", "role": "flag", "nullable": False},
            {"name": "compensation_amount", "type": "FLOAT", "label": "补偿金额", "role": "measure", "nullable": False},
            {"name": "resolution", "type": "TEXT", "label": "处理结果", "role": "payload", "nullable": False},
        ],
    },
}

JOIN_HINTS: Final[list[dict[str, str]]] = [
    {
        "left": "anomalies.order_id",
        "right": "orders.id",
        "label": "异常记录关联到订单，用于按楼栋、状态、时间汇总异常",
    },
]

SEMANTIC_METRICS: Final[dict[str, dict[str, Any]]] = {
    "order_total": {
        "label": "订单总数",
        "table": "orders",
        "expression": "COUNT(*)",
    },
    "delivered_count": {
        "label": "已送达单数",
        "table": "orders",
        "expression": "COUNT(*)",
        "where": "orders.status = 'delivered'",
    },
    "timeout_delivered_count": {
        "label": "超时送达单数",
        "table": "orders",
        "expression": "COUNT(*)",
        "where": (
            "orders.status = 'delivered' "
            "AND orders.delivered_at IS NOT NULL "
            "AND orders.delivered_at > orders.expected_delivery_at"
        ),
        "note": "分母为已送达单数；结果必须附带口径声明「超时=实际送达晚于承诺送达」。",
    },
    "overdue_undelivered_count": {
        "label": "逾期未达单数",
        "table": "orders",
        "expression": "COUNT(*)",
        "where": (
            "orders.delivered_at IS NULL "
            "AND orders.expected_delivery_at IS NOT NULL "
            "AND orders.expected_delivery_at < :now"
        ),
        "note": "与「超时送达」是两个指标，不可混算；:now 由执行层绑定当前时间。",
    },
    "in_transit_count": {
        "label": "在途单数",
        "table": "orders",
        "expression": "COUNT(*)",
        "where": "orders.status NOT IN ('delivered', 'abnormal')",
        "note": "包含 pending 至 dorm_delivery 全部流程态，禁止写死为单一状态值。",
    },
    "abnormal_order_count": {
        "label": "状态为异常的订单数",
        "table": "orders",
        "expression": "COUNT(*)",
        "where": "orders.status = 'abnormal'",
        "note": "与 anomalies 表记录数是两个来源，合并统计时须去重。",
    },
    "anomaly_record_count": {
        "label": "异常记录数",
        "table": "anomalies",
        "expression": "COUNT(*)",
    },
    "compensation_total": {
        "label": "补偿金额合计",
        "table": "anomalies",
        "expression": "SUM(anomalies.compensation_amount)",
        "where": "anomalies.compensation_granted = 1",
    },
}

COVERED_TABLES: Final[tuple[str, ...]] = tuple(SEMANTIC_TABLES)


def get_table_semantic(table: str) -> dict[str, Any]:
    if table not in SEMANTIC_TABLES:
        raise KeyError(f"语义层未覆盖表: {table}")
    return SEMANTIC_TABLES[table]


def get_enum_semantic(name: str) -> dict[str, Any]:
    if name not in SEMANTIC_ENUMS:
        raise KeyError(f"语义层未定义枚举: {name}")
    return SEMANTIC_ENUMS[name]


def order_status_values(include_reserved: bool = False) -> list[str]:
    values = list(ENUM_ORDER_STATUS["values"])
    if include_reserved:
        values.extend(ENUM_ORDER_STATUS["reserved"])
    return values


def _render_field(table: str, field: dict[str, Any]) -> str:
    parts = [f"{field['name']} {field['type']}", field["label"]]
    if field.get("enum"):
        enum = get_enum_semantic(field["enum"])
        enum_values = " / ".join(
            f"{value}={item['label']}" for value, item in enum["values"].items()
        )
        parts.append(f"取值：{enum_values}")
    if field.get("references"):
        parts.append(f"关联 {field['references']}")
    if field.get("normalization"):
        parts.append(f"归一等价：{field['normalization']}")
    if field["nullable"]:
        parts.append("可空")
    if f"{table}.{field['name']}" in SENSITIVE_FIELDS:
        parts.append("禁止出现在结果中")
    return " | ".join(parts)


def render_schema_prompt(tables: Sequence[str] | None = None) -> str:
    selected = tuple(tables) if tables is not None else COVERED_TABLES
    unknown = [name for name in selected if name not in SEMANTIC_TABLES]
    if unknown:
        raise KeyError(f"语义层未覆盖表: {', '.join(unknown)}")

    lines = ["【可查询表】"]
    for table in selected:
        meta = SEMANTIC_TABLES[table]
        lines.append(f"表 {table}（{meta['label']}）：{meta['description']}")
        for field in meta["fields"]:
            lines.append(f"  - {_render_field(table, field)}")

    lines.append("【表间关联】")
    for hint in JOIN_HINTS:
        lines.append(f"  - {hint['left']} = {hint['right']}（{hint['label']}）")

    lines.append("【指标口径】")
    for name, metric in SEMANTIC_METRICS.items():
        if metric["table"] not in selected:
            continue
        clause = metric.get("where")
        text = f"{name}={metric['label']}：{metric['expression']}"
        if clause:
            text += f" WHERE {clause}"
        if metric.get("note"):
            text += f"（{metric['note']}）"
        lines.append(f"  - {text}")

    lines.append("【硬性限制】")
    lines.append("  - 只允许查询上表列出的表与列，敏感字段不得出现在 SELECT 结果中。")
    lines.append("  - 只生成 SELECT 或 WITH 查询，不得生成任何写操作。")
    lines.append(
        "  - 订单状态只使用 "
        + " / ".join(ENUM_ORDER_STATUS["values"])
        + " 八个值；cancelled 不可用。"
    )
    return "\n".join(lines)

RESULT_METRICS: Final[dict[str, dict[str, str]]] = {
    "overdue_total": {"label": "超时单量", "unit": "单"},
    "total": {"label": "数量", "unit": "单"},
    "cnt": {"label": "数量", "unit": "单"},
    "n": {"label": "数量", "unit": "单"},
    "row_count": {"label": "条数", "unit": "条"},
}


def _field_label_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for meta in SEMANTIC_TABLES.values():
        for field in meta["fields"]:
            mapping.setdefault(field["name"], field["label"])
    return mapping


def result_column_labels(columns: Sequence[str]) -> list[str]:
    field_map = _field_label_map()
    labels: list[str] = []
    for column in columns:
        if column in field_map:
            labels.append(field_map[column])
        elif column in RESULT_METRICS:
            labels.append(RESULT_METRICS[column]["label"])
        else:
            labels.append(column)
    return labels


def build_summary(columns: Sequence[str], rows: Sequence[dict]) -> str:
    if not rows or len(columns) < 2:
        return ""

    dimension, metric = columns[0], columns[1]
    points: list[tuple[str, int]] = []
    for row in rows:
        try:
            points.append((str(row.get(dimension, "")), int(row.get(metric) or 0)))
        except (TypeError, ValueError):
            continue

    if not points:
        return ""

    total = sum(value for _, value in points)
    if total <= 0:
        return ""

    metric_meta = RESULT_METRICS.get(metric, {"label": "数值", "unit": ""})
    dimension_label = _field_label_map().get(dimension, dimension)
    top_label, top_value = points[0]
    share = round(top_value * 100 / total)

    if len(points) == 1:
        return f"{metric_meta['label']}合计 {total} {metric_meta['unit']}，仅「{top_label}」一项。"

    return (
        f"{metric_meta['label']}合计 {total} {metric_meta['unit']}，覆盖 {len(points)} 个{dimension_label}；"
        f"「{top_label}」最高（{top_value} {metric_meta['unit']}，占 {share}%）。"
    )


def _column_enum_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for meta in SEMANTIC_TABLES.values():
        for field in meta["fields"]:
            if field.get("enum"):
                mapping.setdefault(field["name"], field["enum"])
    return mapping


def translate_rows(columns: Sequence[str], rows: Sequence[dict]) -> list[dict]:
    enum_map = _column_enum_map()
    translated: list[dict] = []
    for row in rows:
        new_row: dict[str, Any] = {}
        for column in columns:
            value = row.get(column)
            enum_key = enum_map.get(column)
            if enum_key and enum_key in SEMANTIC_ENUMS and isinstance(value, str):
                options = SEMANTIC_ENUMS[enum_key].get("values", {})
                option = options.get(value)
                if isinstance(option, dict):
                    value = option.get("label", value)
            new_row[column] = value
        translated.append(new_row)
    return translated


def result_overview(columns: Sequence[str], rows: Sequence[dict]) -> dict[str, Any]:
    if not rows or len(columns) < 2:
        return {}

    dimension, metric = columns[0], columns[1]
    values: list[tuple[str, int]] = []
    for row in rows:
        try:
            values.append((str(row.get(dimension, "")), int(row.get(metric) or 0)))
        except (TypeError, ValueError):
            continue
    if not values:
        return {}

    total = sum(value for _, value in values)
    top_label, top_value = max(values, key=lambda item: item[1])
    metric_meta = RESULT_METRICS.get(metric, {"label": "数值", "unit": ""})

    return {
        "metric_label": metric_meta["label"],
        "unit": metric_meta["unit"],
        "total": total,
        "dimension_count": len(values),
        "top_label": top_label,
        "top_value": top_value,
        "top_share": round(top_value * 100 / total) if total else 0,
        "average": round(total / len(values), 1) if values else 0,
    }