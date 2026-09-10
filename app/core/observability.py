import time
import json
import logging
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)


def _get_otlp_config() -> tuple[str, str]:
    """Ambil URL + auth Grafana OTLP murni via env (tanpa hardcoded di code).

    Ganti/rotasi cukup via env: GRAFANA_OTLP_URL, GRAFANA_AUTH_HEADER.
    Return ("", "") bila belum dikonfigurasi -> caller no-op (skip kirim).
    """
    url = ""
    auth = ""
    try:
        from app.core.config import settings as _s  # lazy agar tidak circular

        url = (getattr(_s, "GRAFANA_OTLP_URL", "") or "").strip()
        auth = (getattr(_s, "GRAFANA_AUTH_HEADER", "") or "").strip()
    except Exception:
        pass
    return url, auth


def push_email_log_to_grafana(
    channel: str,
    sender_name: str,
    recipient: str,
    subject: str,
    status: str,  # "SUCCESS" or "FAILED"
    error_message: Optional[str] = None,
) -> None:
    """
    Stream asynchronous email delivery log to Grafana Cloud Loki via OTLP Gateway.
    Completely zero impact on local database performance.
    """
    try:
        timestamp_nano = str(int(time.time() * 1e9))
        is_success = status.upper() == "SUCCESS"
        body_str = (
            f"[EMAIL SUCCESS] Terkirim ke {recipient} | Subjek: \"{subject}\" | Kanal: {channel} ({sender_name})"
            if is_success
            else f"[EMAIL FAILED] Gagal ke {recipient} | Subjek: \"{subject}\" | Error: {error_message or 'Unknown'}"
        )

        attributes = [
            {"key": "channel", "value": {"stringValue": channel}},
            {"key": "sender_name", "value": {"stringValue": sender_name}},
            {"key": "recipient", "value": {"stringValue": recipient}},
            {"key": "subject", "value": {"stringValue": subject}},
            {"key": "status", "value": {"stringValue": status.upper()}},
        ]
        if error_message:
            attributes.append({"key": "error_message", "value": {"stringValue": error_message}})

        payload = {
            "resourceLogs": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "pt-itsp-backend-api"}},
                            {"key": "deployment.environment", "value": {"stringValue": "production"}},
                            {"key": "app.name", "value": {"stringValue": "PT Indonesia Thai Summit Plastech"}},
                        ]
                    },
                    "scopeLogs": [
                        {
                            "scope": {"name": "email-delivery-engine"},
                            "logRecords": [
                                {
                                    "timeUnixNano": timestamp_nano,
                                    "severityNumber": 9 if is_success else 17,
                                    "severityText": "INFO" if is_success else "ERROR",
                                    "body": {"stringValue": body_str},
                                    "attributes": attributes,
                                }
                            ],
                        }
                    ],
                }
            ]
        }

        req = None
        otlp_url, otlp_auth = _get_otlp_config()
        # Tanpa konfigurasi via env -> no-op agar tidak crash & tidak kirim ke URL hardcoded.
        if not otlp_url or not otlp_auth:
            logger.debug("Grafana OTLP belum dikonfigurasi via env (GRAFANA_OTLP_URL/GRAFANA_AUTH_HEADER) — skip.")
            return
        req = urllib.request.Request(
            otlp_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": otlp_auth,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status in (200, 204):
                logger.info("Grafana Cloud log streamed successfully for: %s", recipient)
    except Exception as e:
        logger.warning("Failed to stream log to Grafana Cloud: %s", e)
