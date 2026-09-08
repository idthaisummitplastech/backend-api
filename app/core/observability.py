import time
import json
import logging
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

GRAFANA_OTLP_URL = "https://otlp-gateway-prod-ap-southeast-2.grafana.net/otlp/v1/logs"
GRAFANA_AUTH_HEADER = "Basic MTgyMTkyOTpnbGNfZXlKdklqb2lNVGt3TXpRM01DSXNJbTRpT2lKcGRITndMV1Z0WVdsc0xXeHZaM01pTENKcklqb2lRMVp0VWt0Vk1VazFaVE0wT0RjMk1tVjFVM3B3VURrMUlpd2liU0k2ZXlKeUlqb2ljSEp2WkMxaGNDMXpiM1YwYUdWaGMzUXRNaUo5ZlE9PQ=="


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

        req = urllib.request.Request(
            GRAFANA_OTLP_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": GRAFANA_AUTH_HEADER,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status in (200, 204):
                logger.info("Grafana Cloud log streamed successfully for: %s", recipient)
    except Exception as e:
        logger.warning("Failed to stream log to Grafana Cloud: %s", e)
