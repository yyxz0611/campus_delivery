"""照片审核：黑图/花图/模糊检测（PIL+numpy 真实计算）+ 单号/寝室号识别（预留华为云 OCR）。

硬性规则：
- 黑图（平均亮度过低）-> 拒绝
- 花图（随机噪声/颜色熵异常）-> 拒绝
- 过度模糊（边缘过少）-> 拒绝
生产环境通过 HW_OCR_ENABLED 对接华为云 OCR 校验单号与寝室号；本地演示为质量审核模式。
"""
from __future__ import annotations

import io
import math
from typing import Any

import numpy as np
from PIL import Image, ImageStat


def _open(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def _entropy(img: Image.Image) -> float:
    """灰度直方图熵。"""
    gray = img.convert("L")
    hist = gray.histogram()
    total = sum(hist)
    e = 0.0
    for h in hist:
        if h == 0:
            continue
        p = h / total
        e -= p * math.log2(p)
    return e


def _laplacian_variance(img: Image.Image) -> float:
    """拉普拉斯方差（清晰度指标），模糊图显著偏低。"""
    gray = np.asarray(img.convert("L"), dtype=np.float64)
    lap = np.zeros_like(gray)
    lap[1:-1, 1:-1] = (
        gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:] - 4 * gray[1:-1, 1:-1]
    )
    return float(np.var(lap))


def _color_entropy(img: Image.Image) -> float:
    """量化 RGB 后的颜色熵，随机噪声花图该值接近 9（log2 512），真实照片通常 < 6。"""
    arr = np.asarray(img)
    q = (arr >> 3).astype(np.int32)  # 每通道 5 bit -> 0-31
    idx = (q[:, :, 0] << 10) | (q[:, :, 1] << 5) | q[:, :, 2]  # 15 bit -> 0-32767
    hist = np.bincount(idx.ravel(), minlength=32768)
    total = idx.size
    probs = hist[hist > 0] / total
    return float(-np.sum(probs * np.log2(probs)))


def analyze_image(data: bytes) -> dict[str, float]:
    img = _open(data)
    gray = img.convert("L")
    brightness = ImageStat.Stat(gray).mean[0]
    edge_variance = _laplacian_variance(img)
    entropy = _entropy(img)
    color_entropy = _color_entropy(img)
    return {
        "brightness": round(brightness, 2),
        "edge_variance": round(edge_variance, 2),
        "entropy": round(entropy, 3),
        "color_entropy": round(color_entropy, 3),
    }


def audit_image(
    data: bytes,
    expected_order_no: str = "",
    expected_room: str = "",
) -> tuple[bool, dict[str, Any], str]:
    """返回 (是否通过, 审核结果, 拒绝原因)。"""
    metrics = analyze_image(data)

    is_black = metrics["brightness"] < 30
    is_blurry = metrics["edge_variance"] < 60
    is_flower_noise = metrics["color_entropy"] > 7.0

    result: dict[str, Any] = {
        "is_black": bool(is_black),
        "is_blurry": bool(is_blurry),
        "is_flower_noise": bool(is_flower_noise),
        "has_order_no": "unverified",
        "has_room": "unverified",
        "has_context": not (is_black or is_flower_noise),
        "ocr_mode": "quality_only",
    }

    reasons: list[str] = []
    if is_black:
        reasons.append("黑图（亮度不足），视为无效上传")
    if is_flower_noise:
        reasons.append("花图（色彩噪声异常），视为无效上传")
    if is_blurry:
        reasons.append("图片过度模糊，无法辨认")

    # 生产：华为云 OCR 校验单号与寝室号（识别成功才纳入硬性拒绝，调用失败则降级为质量审核）
    if _ocr_enabled():
        ocr_text = huawei_ocr_extract(data)
        if ocr_text is not None:
            result["ocr_mode"] = "huawei_ocr"
            result["ocr_text"] = ocr_text[:200]
            result["has_order_no"] = bool(expected_order_no and expected_order_no in ocr_text)
            result["has_room"] = bool(expected_room and expected_room in ocr_text)
            if expected_order_no and expected_order_no not in ocr_text:
                reasons.append("照片中未识别到清晰的外卖单号")
            if expected_room and expected_room not in ocr_text:
                reasons.append("照片中未识别到寝室号/环境背景")

    passed = not reasons
    return passed, result, "；".join(reasons)


def _ocr_enabled() -> bool:
    from ..config import settings

    return settings.huawei_ocr_enabled and settings.huawei_credentials_ready


def huawei_ocr_extract(data: bytes) -> str | None:
    """调用华为云 OCR 提取文字；网络/凭证异常时返回 None（降级不判定）。"""
    import base64

    from .. import huawei

    try:
        return huawei.ocr_extract_text(base64.b64encode(data).decode())
    except Exception:
        return None