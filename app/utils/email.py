import asyncio
import os
import boto3
from botocore.exceptions import BotoCoreError, ClientError


def _build_ses_client():
    return boto3.client(
        "ses",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )


async def send_otp_email(to_email: str, otp: str) -> None:
    def _send():
        mail_from = os.getenv("MAIL_FROM")
        if not mail_from:
            raise RuntimeError("MAIL_FROM must be set in environment variables.")

        plain = (
            f"Your OTP for password reset is: {otp}\n"
            "This OTP is valid for 10 minutes.\n"
            "If you did not request this, please ignore this email."
        )
        html = f"""
        <html>
          <body style="font-family: Arial, sans-serif; color: #333;">
            <h2>Password Reset OTP</h2>
            <p>Use the OTP below to reset your password:</p>
            <h1 style="letter-spacing: 6px; color: #4F46E5;">{otp}</h1>
            <p>This OTP is valid for <strong>10 minutes</strong>.</p>
            <p style="color: #888; font-size: 13px;">
              If you did not request a password reset, please ignore this email.
            </p>
          </body>
        </html>
        """

        client = _build_ses_client()
        try:
            client.send_email(
                Source=mail_from,
                Destination={"ToAddresses": [to_email]},
                Message={
                    "Subject": {"Data": "Your Password Reset OTP - Skill Snapshot", "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": plain, "Charset": "UTF-8"},
                        "Html": {"Data": html, "Charset": "UTF-8"},
                    },
                },
            )
        except ClientError as e:
            raise RuntimeError(f"SES failed to send email: {e.response['Error']['Message']}")
        except BotoCoreError as e:
            raise RuntimeError(f"AWS connection error: {str(e)}")

    await asyncio.to_thread(_send)
