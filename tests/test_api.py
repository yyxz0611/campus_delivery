"""核心业务端到端测试。"""
import base64
import io
import random

from PIL import Image, ImageDraw


def _png_b64(im: Image.Image) -> str:
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _normal_photo() -> str:
    im = Image.new("RGB", (320, 240), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 320, 80], fill=(220, 240, 255))
    d.text((20, 120), "FW2026092901", fill=(0, 0, 0))
    d.rectangle([20, 150, 140, 190], fill=(70, 130, 70))
    d.text((30, 160), "512", fill=(255, 255, 255))
    return _png_b64(im)


def _black_photo() -> str:
    return _png_b64(Image.new("RGB", (320, 240), (0, 0, 0)))


def _noise_photo() -> str:
    im = Image.new("RGB", (320, 240))
    px = im.load()
    for i in range(320):
        for j in range(240):
            px[i, j] = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
    return _png_b64(im)


def _create_order(client, order_no="FW0001", building="梅园1栋"):
    return client.post("/api/orders", json={
        "order_no": order_no, "customer_name": "张三", "dorm_building": building,
        "dorm_room": "512", "vendor_name": "老王炒饭", "food_items": "炒饭",
    }).json()


def test_meta(client):
    r = client.get("/api/meta")
    assert r.status_code == 200
    assert "database" in r.json()
    assert r.json()["redis_mode"] == "in-memory"


def test_frontend_served(client):
    assert "校园外卖配送" in client.get("/").text
    assert client.get("/app.js").status_code == 200
    assert client.get("/style.css").status_code == 200
    assert client.get("/vue.global.prod.js").status_code == 200


def test_order_flow_and_trajectory(client):
    o = _create_order(client)
    oid = o["id"]
    for st in ["picked", "handover", "in_campus", "arrived_site", "dorm_delivery", "delivered"]:
        r = client.patch(f"/api/orders/{oid}/status", json={"status": st, "courier_name": "李四"})
        assert r.status_code == 200

    nodes = client.get(f"/api/tracking/{oid}").json()
    assert len(nodes) == 6
    assert [n["node_type"] for n in nodes] == [
        "pickup", "external_handover", "internal_transport", "site_arrival", "dorm_delivery", "completed",
    ]


def test_photo_audit_black_rejected(client):
    o = _create_order(client, "FW0002")
    r = client.post("/api/photos/upload", json={
        "order_id": o["id"], "file_base64": _black_photo(), "file_ext": "png",
    })
    assert r.status_code == 200
    assert r.json()["audit_status"] == "rejected"


def test_photo_audit_noise_rejected(client):
    o = _create_order(client, "FW0003")
    r = client.post("/api/photos/upload", json={
        "order_id": o["id"], "file_base64": _noise_photo(), "file_ext": "png",
    })
    assert r.json()["audit_status"] == "rejected"


def test_photo_audit_normal_passed(client):
    o = _create_order(client, "FW0004")
    r = client.post("/api/photos/upload", json={
        "order_id": o["id"], "file_base64": _normal_photo(), "file_ext": "png",
    })
    assert r.json()["audit_status"] == "passed"


def test_anomaly_flow(client):
    o = _create_order(client, "FW0005")
    r = client.post("/api/anomalies", json={
        "order_id": o["id"], "anomaly_type": "not_delivered", "reported_by": "张三",
    })
    aid = r.json()["id"]

    a = client.post(f"/api/anomalies/{aid}/locate").json()
    assert a["status"] == "located"

    a = client.post(f"/api/anomalies/{aid}/compensate").json()
    assert a["compensation_granted"] is True
    assert a["compensation_amount"] > 0


def test_dispatch_plan(client):
    for i in range(5):
        _create_order(client, f"FWDISP{i}", "梅园1栋" if i < 3 else "竹园1栋")
    # 将订单推进到校内运输状态，以纳入调度
    orders = client.get("/api/orders?keyword=FWDISP").json()
    for o in orders:
        client.patch(f"/api/orders/{o['id']}/status", json={"status": "handover"})
    plan = client.post("/api/dispatch/plan").json()
    assert plan["total_orders"] == 5
    assert plan["vehicle_count"] >= 1
    assert len(plan["staff"]) >= 1