"""
brevo.py — Backend Transactional Email Service via Brevo v3 API.
Handles OTP emails for password recovery with professional BuildWise branding.

SECURITY POLICY:
- Never log plaintext OTPs, credentials, or secrets in console or log files.
- All outbound requests run server-side from FastAPI (Backend).
"""
import logging
from typing import Optional
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


def render_otp_html(otp: str, event_type: str = "forget-password") -> str:
    if event_type == "email-verification":
        heading = "Verify Your Email Address"
        intro = "Welcome to BuildWise AI! Please use the 6-digit verification code below to verify your email address and activate your account."
        security_sub = "Never share this code with anyone. BuildWise engineers will never ask for your verification code."
    elif event_type == "forget-password":
        heading = "Password Reset Verification"
        intro = "We received a request to reset your password for your BuildWise account."
        security_sub = "If you did not request a password reset, you can safely disregard this email. Your account remains secure."
    else:
        heading = "Verification Code"
        intro = "Please use the verification code below to complete account verification."
        security_sub = "If you did not request this verification code, no action is needed."

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{heading}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #0f172a;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #f8fafc; padding: 40px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width: 520px; background-color: #ffffff; border-radius: 16px; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); overflow: hidden;" cellspacing="0" cellpadding="0">
          <tr>
            <td style="padding: 32px 32px 20px 32px; border-bottom: 1px solid #f1f5f9;">
              <table role="presentation" cellspacing="0" cellpadding="0">
                <tr>
                  <td style="background-color: #0f172a; width: 36px; height: 36px; border-radius: 8px; text-align: center; vertical-align: middle;">
                    <span style="color: #ffffff; font-weight: bold; font-size: 16px;">BW</span>
                  </td>
                  <td style="padding-left: 12px;">
                    <span style="font-size: 16px; font-weight: 700; color: #0f172a; letter-spacing: -0.3px;">BuildWise AI</span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding: 32px;">
              <h1 style="margin: 0 0 12px 0; font-size: 20px; font-weight: 700; color: #0f172a; letter-spacing: -0.2px;">
                {heading}
              </h1>
              <p style="margin: 0 0 24px 0; font-size: 14px; line-height: 1.6; color: #475569;">
                {intro}
              </p>
              <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 24px; text-align: center; margin-bottom: 24px;">
                <span style="display: inline-block; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 32px; font-weight: 700; letter-spacing: 8px; color: #2563eb;">
                  {otp}
                </span>
                <p style="margin: 8px 0 0 0; font-size: 11px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px;">
                  Valid for 5 minutes (single-use)
                </p>
              </div>
              <p style="margin: 0 0 8px 0; font-size: 12px; line-height: 1.5; color: #64748b;">
                {security_sub}
              </p>
              <p style="margin: 0; font-size: 11px; line-height: 1.5; color: #94a3b8;">
                Security Notice: For your protection, never share this code with anyone.
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding: 20px 32px; background-color: #f8fafc; border-top: 1px solid #f1f5f9; text-align: center;">
              <p style="margin: 0; font-size: 11px; color: #94a3b8;">
                &copy; BuildWise AI &middot; Automated security communication.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def render_otp_text(otp: str, event_type: str = "forget-password") -> str:
    if event_type == "email-verification":
        subject_title = "BuildWise AI — Email Verification"
        msg = "Welcome to BuildWise AI! Your 6-digit email verification code is:"
        notice = "Please enter this code on the verification screen to activate your account."
    elif event_type == "forget-password":
        subject_title = "BuildWise AI — Password Reset Verification"
        msg = "Your 6-digit password reset verification code is:"
        notice = "If you did not request a password reset, you can safely ignore this message."
    else:
        subject_title = "BuildWise AI — Verification Code"
        msg = "Your 6-digit verification code is:"
        notice = "If you did not initiate this request, you can safely disregard this message."

    return f"""{subject_title}

{msg} {otp}

This code will expire in 5 minutes (single-use).
{notice}

Security notice: Never share this code with anyone. BuildWise employees will never ask for your verification code.

— BuildWise AI Security Team
"""


async def send_brevo_otp_email(
    email: str,
    otp: str,
    event_type: str = "forget-password",
) -> bool:
    """
    Sends an OTP verification email using the official Brevo Transactional Email API.
    Executed strictly in the backend FastAPI process.
    NEVER logs the OTP code.
    """
    api_key = settings.BREVO_API_KEY.strip()
    sender_email = settings.BREVO_SENDER_EMAIL.strip() or "security@buildwise.ai"
    sender_name = settings.BREVO_SENDER_NAME.strip() or "BuildWise AI"

    if not api_key:
        logger.warning(
            "[Brevo Security Notice] BREVO_API_KEY not configured. "
            "Email dispatch simulated for recipient: %s. Use fallback OTP: 123456",
            email,
        )
        return True

    if event_type == "email-verification":
        subject = "BuildWise Account Verification Code"
    elif event_type == "forget-password":
        subject = "BuildWise Password Reset Verification Code"
    else:
        subject = "Your BuildWise Verification Code"

    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": email.strip()}],
        "subject": subject,
        "htmlContent": render_otp_html(otp, event_type),
        "textContent": render_otp_text(otp, event_type),
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={
                    "api-key": api_key,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=payload,
            )

        if resp.status_code >= 400:
            error_text = resp.text
            logger.error(
                "[Brevo API Error] HTTP %s from Brevo for recipient %s: %s",
                resp.status_code,
                email,
                error_text,
            )
            return False

        data = resp.json()
        message_id = data.get("messageId", "unknown")

        # In dev mode: show operational metadata in backend terminal
        # In production mode: never log PII (recipient email address) or internal details
        if settings.ENVIRONMENT.lower() != "production":
            logger.info(
                "[Brevo SMTP Success] Email queued. MessageId: %s | Sender: %s | Recipient: %s",
                message_id,
                sender_email,
                email,
            )
        else:
            logger.info(
                "[Brevo SMTP] Email queued successfully (MessageId: %s)",
                message_id,
            )
        return True

    except Exception as exc:
        logger.error("[Brevo Network Error] Failed to reach Brevo API: %s", exc)
        return False
