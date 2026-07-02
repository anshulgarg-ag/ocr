import httpx

from config.logging import get_logger
from config.settings import settings

log = get_logger(__name__)


async def send_slack_alert(message: str, level: str = "error") -> None:
    if not settings.slack_webhook_url:
        return
    icon = ":rotating_light:" if level == "error" else ":warning:"
    payload = {"text": f"{icon} *OCR Pipeline Alert*\n{message}"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(settings.slack_webhook_url, json=payload)
            resp.raise_for_status()
    except Exception as exc:
        log.warning("slack_alert_failed", error=str(exc))


async def alert_flow_failed(batch_id: str, error: str) -> None:
    await send_slack_alert(
        f"Batch `{batch_id}` failed.\nError: `{error}`",
        level="error",
    )


async def alert_dead_letter_spike(count: int, threshold: int = 10) -> None:
    if count >= threshold:
        await send_slack_alert(
            f"{count} documents hit the dead-letter queue in this batch (threshold: {threshold}).",
            level="warning",
        )
