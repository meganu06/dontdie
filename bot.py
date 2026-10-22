"""Don't Die: seven agents, one Slack thread. Start with: python bot.py."""
import argparse
import asyncio
import html
import logging
import os
import re
import time
import json
import uuid
from collections import OrderedDict

from core.crew import run_crew
from core.cloud import CloudRun
from core.settings import ICONS, NAMES, QUESTION, ROOT, Settings


class EventDeduper:
    def __init__(self):
        self.seen = OrderedDict()

    def duplicate(self, key):
        now = time.monotonic()
        while self.seen and next(iter(self.seen.values())) < now - 3600:
            self.seen.popitem(last=False)
        if key in self.seen:
            return True
        if len(self.seen) >= 2000:
            self.seen.popitem(last=False)
        self.seen[key] = now
        return False


class SlackPublisher:
    def __init__(self, client, channel, thread_ts, delay=2, lock=None):
        self.client, self.channel, self.thread_ts = client, channel, thread_ts
        self.delay = delay
        self.lock = lock or asyncio.Lock()

    async def send(self, agent, text, result=None):
        from slack_sdk.errors import SlackApiError
        result = result or {}
        label = NAMES[agent]
        blocks = [{"type": "section", "text": {"type": "plain_text", "text": label + " · " + text[:2700]}}]
        sources = result.get("source_ids", [])
        context = []
        if sources:
            context.append("Demo sources: " + ", ".join(sources[:5]) + (" …" if len(sources) > 5 else ""))
        if result.get("sandbox_id"):
            context.append("Google sandbox " + result["sandbox_id"].rsplit("/", 1)[-1])
        if result.get("run_id"):
            context.append("Run " + result["run_id"])
        if context:
            blocks.append({"type": "context", "elements": [{"type": "plain_text", "text": " · ".join(context)[:1900]}]})
        arguments = dict(channel=self.channel, thread_ts=self.thread_ts,
                         username="Don't Die · " + label, icon_emoji=ICONS[agent],
                         text=html.escape(label + ": " + text, quote=False), blocks=blocks,
                         parse="none", mrkdwn=False, unfurl_links=False, unfurl_media=False)
        async with self.lock:
            for attempt in range(3):
                try:
                    await self.client.chat_postMessage(**arguments)
                    break
                except SlackApiError as exc:
                    if exc.response.get("error") == "missing_scope" and "username" in arguments:
                        # The visible label still identifies the agent if customization was removed.
                        arguments.pop("username")
                        arguments.pop("icon_emoji")
                    elif exc.response.status_code == 429 and attempt < 2:
                        await asyncio.sleep(min(60, max(1, int(exc.response.headers.get("Retry-After", "2")))))
                    else:
                        raise
            else:
                raise RuntimeError("Slack retries exhausted")
            # Shared lock keeps all channel messages at least two seconds apart.
            await asyncio.sleep(self.delay)


async def slack_main(settings):
    from slack_bolt.async_app import AsyncApp
    from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
    for key in ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_CHANNEL"):
        if not os.getenv(key):
            raise ValueError(f"Set {key} in the environment or local .env.")
    app = AsyncApp(token=os.environ["SLACK_BOT_TOKEN"])
    allowed = os.environ["SLACK_CHANNEL"]
    seen = EventDeduper()
    busy = asyncio.Lock()
    publish_lock = asyncio.Lock()
    delay = max(2, float(os.getenv("SLACK_MESSAGE_DELAY", "2")))

    @app.event("app_mention")
    async def mention(event, body, client):
        if event.get("bot_id") or event.get("channel") != allowed:
            return
        if seen.duplicate(body.get("event_id") or event["channel"] + event["ts"]):
            return
        thread_ts = event.get("thread_ts") or event["ts"]
        publisher = SlackPublisher(client, allowed, thread_ts, delay, publish_lock)
        question = re.sub(r"<@[A-Z0-9]+>", "", event.get("text", "")).strip()
        if not question or question.lower() in ("hello", "hi", "help"):
            await publisher.send("chief", "Ready: Chief, PMF, Retention, Competitor, Finance, GTM and Product. Ask: “" + QUESTION + "”")
            return
        if len(question) > 2000:
            await publisher.send("chief", "Please keep the decision question under 2,000 characters.")
            return
        if busy.locked():
            await publisher.send("chief", "Another decision is running; please retry after its Chief recommendation appears.")
            return
        async with busy:
            try:
                await run_crew(settings, question, publisher.send)
            except Exception as exc:
                logging.error("Decision run failed (%s)", type(exc).__name__)
                await publisher.send("chief", "The cloud run failed; I cannot provide a reliable recommendation. Check the service logs and retry.")

    print("Don't Die listening: seven agents, synthetic business data, real Gemini and Google sandboxes.", flush=True)
    await AsyncSocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start_async()


async def console_send(agent, text, result=None):
    print(f"[{NAMES[agent]}] {text}", flush=True)
    if result and result.get("sandbox_id"):
        print("  Sandbox: " + result["sandbox_id"], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", metavar="QUESTION", help="Run all seven cloud agents without posting to Slack")
    parser.add_argument("--check-cloud", action="store_true", help="Verify Gemini and a temporary sandbox with the current cloud identity")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    settings = Settings.from_env()
    try:
        if args.check_cloud:
            cloud = CloudRun(settings, "preflight-" + uuid.uuid4().hex[:8])
            try:
                cloud.start()
                data = json.loads((ROOT / "data/loopdesk.json").read_text())
                result = cloud.agent("chief", {"kpis": data["kpis"]}, "Report the supplied demo business KPIs for a startup health check.")
                print("DONTDIE_CLOUD_READY " + result["sandbox_id"], flush=True)
            except Exception as exc:
                print("DONTDIE_CLOUD_FAILED " + type(exc).__name__, flush=True)
                raise SystemExit(1)
            finally:
                cloud.close()
        elif args.once:
            record = asyncio.run(run_crew(settings, args.once, console_send))
            print("Saved runs/" + record["run_id"] + ".json")
            if any(r["status"] != "ok" for r in record["agents"].values()):
                raise SystemExit(1)
        else:
            # The default entry point now shares persistence, scheduling and
            # adaptive routing with the protected web control room.
            from server import main as server_main
            server_main()
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
