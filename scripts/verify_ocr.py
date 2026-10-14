"""验证华为云「通用文字识别」OCR 调用：生成一张带文字测试图，base64 后调用 ocr_extract_text。"""
from __future__ import annotations

import base64
import io
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
os.chdir(BASE)
sys.path.insert(0, str(BASE))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from app import huawei  # noqa: E402


def make_test_image() -> bytes:
    img = Image.new("RGB", (640, 260), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 44)
        small = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 36)
    except Exception:
        font = ImageFont.load_default()
        small = font
    d.text((40, 50), "Order No: FD10201800", fill="black", font=font)
    d.text((40, 150), "Room: 5-302", fill="black", font=small)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def main() -> None:
    print("开始调用华为云通用文字识别 ...")
    try:
        text = huawei.ocr_extract_text(base64.b64encode(make_test_image()).decode())
        print("== OCR 识别结果 ==")
        print(repr(text))
        print("== 校验 ==")
        print("含订单号 FD10201800:", "FD10201800" in (text or ""))
        print("含寝室号 5-302:", "5-302" in (text or ""))
        print("✅ 调用成功，OCR 服务可用")
    except Exception as e:
        print(f"❌ 调用失败：{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()