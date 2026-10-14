"""邮箱发送服务：通过 SMTP 发送验证码（QQ 邮箱 smtp.qq.com:465 SSL）。"""
from __future__ import annotations

import smtplib
from email.header import Header
from email.mime.text import MIMEText

from ..config import settings


def send_verification_code(to_email: str, code: str) -> None:
    if not settings.smtp_user or not settings.smtp_password:
        raise RuntimeError("邮箱 SMTP 未配置")

    subject = "校园外卖配送平台 · 邮箱验证码"
    body = f"您的验证码是：{code}，5 分钟内有效，请勿泄露。若非本人操作请忽略。"

    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = settings.smtp_user
    msg["To"] = to_email
    msg["Subject"] = Header(subject, "utf-8")

    server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10)
    try:
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_user, [to_email], msg.as_string())
    finally:
        server.quit()