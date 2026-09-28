"""AlertNotifier delivers to Telegram, Slack or e-mail (no network: mocked transport and mailer)."""

import json

import httpx
import pytest

from core.infrastructure.alert_notifier import AlertDeliveryError, AlertNotifier


def _recording_client(status_code=200):
    """An httpx client factory that records requests instead of sending them."""
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status_code, json={"ok": status_code < 300})

    return requests, lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


class FakeMailer:
    def __init__(self):
        self.sent = []

    async def send_async(self, recipients, subject, body):
        self.sent.append((list(recipients), subject, body))


@pytest.mark.asyncio
async def test_telegram_alert_posts_to_the_bot_api_with_the_deployment_prefix():
    requests, factory = _recording_client()
    notifier = AlertNotifier("telegram", "chat.client.vn", telegram_bot_token="123:abc",
                             telegram_chat_id="-100", http_client_factory=factory)
    await notifier.send("Disk almost full", "92% used")
    (request,) = requests
    assert request.url == "https://api.telegram.org/bot123:abc/sendMessage"
    payload = json.loads(request.content)
    assert payload["chat_id"] == "-100"
    assert payload["text"].startswith("[chat.client.vn] Disk almost full") and "92% used" in payload["text"]


@pytest.mark.asyncio
async def test_slack_alert_posts_to_the_webhook():
    requests, factory = _recording_client()
    notifier = AlertNotifier("slack", "box", slack_webhook_url="https://hooks.slack.test/T/B/X",
                             http_client_factory=factory)
    await notifier.send("Service down", "api unhealthy")
    assert str(requests[0].url) == "https://hooks.slack.test/T/B/X"
    assert "Service down" in json.loads(requests[0].content)["text"]


@pytest.mark.asyncio
async def test_email_alert_goes_through_the_mailer():
    mailer = FakeMailer()
    notifier = AlertNotifier("smtp", "box", email_recipients=["ops@client.vn"], mailer=mailer)
    await notifier.send("Spend threshold", "80% of the monthly cap")
    assert mailer.sent == [(["ops@client.vn"], "[box] Spend threshold", "80% of the monthly cap")]


@pytest.mark.asyncio
async def test_a_refused_or_misconfigured_channel_raises():
    _, factory = _recording_client(status_code=401)
    notifier = AlertNotifier("telegram", "box", telegram_bot_token="t", telegram_chat_id="c", http_client_factory=factory)
    with pytest.raises(AlertDeliveryError, match="401"):
        await notifier.send("x", "y")
    with pytest.raises(AlertDeliveryError, match="required"):
        await AlertNotifier("slack", "box").send("x", "y")


@pytest.mark.asyncio
async def test_disabled_notifier_sends_nothing_and_unknown_channel_is_rejected():
    requests, factory = _recording_client()
    notifier = AlertNotifier("", "box", http_client_factory=factory)
    assert not notifier.enabled
    await notifier.send("x", "y")
    assert requests == []
    with pytest.raises(ValueError):
        AlertNotifier("pager", "box")
