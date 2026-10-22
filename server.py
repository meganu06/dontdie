"""One persistent control-room service for web, Slack and scheduled execution."""
import argparse
import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from aiohttp import web

from core.engine import Engine
from core.settings import AGENTS, NAMES, ROOT, Settings
from core.store import Store


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


async def make_app(store=None, settings=None, start_background=True, slack=True, auth_hash=None, origin=None, secure=None):
    settings = settings or Settings.from_env()
    store = store or Store(os.getenv("CONTROL_ROOM_DB", str(ROOT / "runs/controlroom.sqlite3")))
    auth_hash = auth_hash or os.getenv("WEB_PASSWORD_SHA256", "")
    if len(auth_hash) != 64:
        raise ValueError("Configure WEB_PASSWORD_SHA256 before starting protected web controls.")
    origin = (origin or os.getenv("CONTROL_ROOM_URL", "http://127.0.0.1:8080")).rstrip("/")
    secure = origin.startswith("https://") if secure is None else secure
    engine = Engine(store, settings)
    failures = {}

    @web.middleware
    async def protect(request, handler):
        try:
            if request.path.startswith("/api/") and request.path != "/api/login":
                token = request.cookies.get("dontdie_session", "")
                session = store.one("SELECT * FROM sessions WHERE token_hash=? AND expires>?", (digest(token), time.time())) if token else None
                if not session:
                    raise web.HTTPUnauthorized(text=json.dumps({"error": "Sign in to continue."}), content_type="application/json")
                request["session"] = session
                if request.method not in ("GET", "HEAD"):
                    if not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), session["csrf"]):
                        raise web.HTTPForbidden(text=json.dumps({"error": "Session verification failed; reload and retry."}), content_type="application/json")
            if request.method not in ("GET", "HEAD") and request.headers.get("Origin") != origin:
                raise web.HTTPForbidden(text=json.dumps({"error": "Request origin was rejected."}), content_type="application/json")
            response = await handler(request)
        except (ValueError, KeyError, TypeError) as exc:
            response = web.json_response({"error": str(exc)[:300]}, status=400)
        except web.HTTPException as exc:
            response = web.Response(status=exc.status, text=exc.text, content_type=exc.content_type, headers={k:v for k,v in exc.headers.items() if k.lower() != "content-type"})
        except Exception as exc:
            logging.error("Web request failed: %s", type(exc).__name__)
            response = web.json_response({"error": "The request failed. Retry or inspect the service log."}, status=500)
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY", "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'"})
        return response

    app = web.Application(middlewares=[protect], client_max_size=20000)
    app["store"], app["engine"] = store, engine
    routes = web.RouteTableDef()

    @routes.get("/")
    async def index(request):
        return web.Response(text=(ROOT / "web/index.html").read_text(), content_type="text/html")

    @routes.get("/static/{name}")
    async def static(request):
        name = request.match_info["name"]
        if name not in ("app.js", "app.css"):
            raise web.HTTPNotFound()
        return web.Response(text=(ROOT / "web" / name).read_text(), content_type="application/javascript" if name.endswith(".js") else "text/css")

    @routes.get("/healthz")
    async def health(request):
        return web.json_response({"status": "ok", "service": "dontdie-control-room"})

    @routes.post("/api/login")
    async def login(request):
        now = time.time()
        ip = request.headers.get("X-Forwarded-For", request.remote or "unknown").split(",")[0]
        attempts = [t for t in failures.get(ip, []) if t > now - 300]
        failures[ip] = attempts
        if len(attempts) >= 8:
            return web.json_response({"error": "Too many attempts. Try again in five minutes."}, status=429)
        data = await request.json()
        if not hmac.compare_digest(digest(str(data.get("key", ""))), auth_hash):
            attempts.append(now)
            return web.json_response({"error": "That access key is not valid."}, status=401)
        failures.pop(ip, None)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        store.write("DELETE FROM sessions WHERE expires<?", (now,))
        store.write("INSERT INTO sessions VALUES (?,?,?)", (digest(token), csrf, now + 86400))
        response = web.json_response({"csrf": csrf, "names": NAMES})
        response.set_cookie("dontdie_session", token, httponly=True, secure=secure, samesite="Strict", max_age=86400, path="/")
        return response

    @routes.get("/api/session")
    async def session(request):
        return web.json_response({"csrf": request["session"]["csrf"], "names": NAMES})

    @routes.post("/api/logout")
    async def logout(request):
        store.write("DELETE FROM sessions WHERE token_hash=?", (request["session"]["token_hash"],))
        response = web.json_response({"ok": True})
        response.del_cookie("dontdie_session", path="/")
        return response

    @routes.get("/api/state")
    async def state(request):
        return web.json_response(store.state(request.query.get("conversation"), request.query.get("run")))

    @routes.post("/api/chat")
    async def chat(request):
        data = await request.json()
        tz = str(data.get("timezone") or "Europe/London")
        ZoneInfo(tz)
        cid = data.get("conversation_id")
        previous = store.one("SELECT id FROM runs WHERE conversation_id=? AND status IN ('done','partial') ORDER BY created DESC LIMIT 1", (cid,)) if cid else None
        run = store.enqueue(data.get("objective", ""), cid, timezone=tz, parent_run=previous["id"] if previous else None)
        return web.json_response(run, status=202)

    @routes.post("/api/agents/{agent}/run")
    async def agent_run(request):
        data = await request.json()
        run = store.enqueue(data.get("objective", ""), data.get("conversation_id"), agent=request.match_info["agent"], timezone=data.get("timezone", "Europe/London"))
        return web.json_response(run, status=202)

    @routes.get("/api/tasks/{id}")
    async def task_detail(request):
        task = store.one("SELECT * FROM tasks WHERE id=?", (request.match_info["id"],))
        if not task:
            raise ValueError("Task not found.")
        task["result"] = json.loads(task.pop("result_json") or "{}")
        task["events"] = store.rows("SELECT * FROM events WHERE task_id=? ORDER BY id", (task["id"],))
        for event in task["events"]:
            event["details"] = json.loads(event.pop("details_json") or "{}")
            event["details"].pop("code", None)
        return web.json_response(task)

    @routes.post("/api/tasks/{id}/{action}")
    async def task_action(request):
        task = store.one("SELECT * FROM tasks WHERE id=?", (request.match_info["id"],))
        if not task:
            raise ValueError("Task not found.")
        parent = store.one("SELECT * FROM runs WHERE id=?", (task["run_id"],))
        data = await request.json()
        action = request.match_info["action"]
        if action == "retry":
            if task["status"] != "error":
                raise ValueError("Only failed tasks can be retried; use Follow up for completed work.")
            objective = (parent["objective"] + "\nRetry the check: " + task["instruction"])[:2000]
        elif action == "followup":
            objective = data.get("objective", "")
        else:
            raise ValueError("Unknown task action.")
        return web.json_response(store.enqueue(objective, parent["conversation_id"], task["agent"], parent_run=parent["id"], timezone=parent["timezone"]), status=202)

    @routes.post("/api/runs/{id}/retry")
    async def retry_run(request):
        run = store.one("SELECT * FROM runs WHERE id=?", (request.match_info["id"],))
        if not run or run["status"] not in ("error", "partial", "interrupted"):
            raise ValueError("Select a failed, partial or interrupted run.")
        return web.json_response(store.enqueue(run["objective"], run["conversation_id"], run["agent"], parent_run=run["id"], timezone=run["timezone"]), status=202)

    @routes.post("/api/schedules")
    async def add_schedule(request):
        data = await request.json()
        cid = data.pop("conversation_id", None)
        if cid and not store.one("SELECT id FROM conversations WHERE id=?", (cid,)):
            raise ValueError("Conversation not found.")
        return web.json_response(store.create_schedule(data, cid), status=201)

    @routes.post("/api/schedules/{id}/{action}")
    async def schedule_action(request):
        return web.json_response(store.change_schedule(request.match_info["id"], request.match_info["action"]))

    app.add_routes(routes)

    async def startup(app):
        if start_background:
            await engine.start()
        if slack and os.getenv("SLACK_BOT_TOKEN") and os.getenv("SLACK_APP_TOKEN"):
            from slack_bolt.async_app import AsyncApp
            from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
            from bot import SlackPublisher
            slack_app = AsyncApp(token=os.environ["SLACK_BOT_TOKEN"])
            publish_lock = asyncio.Lock()

            async def slack_send(conversation, agent, text, result):
                publisher = SlackPublisher(slack_app.client, conversation["slack_channel"], conversation["slack_thread"], lock=publish_lock)
                await publisher.send(agent, text, result)
            engine.slack_send = slack_send

            @slack_app.event("app_mention")
            async def mention(event, body, client):
                if event.get("bot_id") or event.get("channel") != os.getenv("SLACK_CHANNEL"):
                    return
                key = body.get("event_id") or event["channel"] + event["ts"]
                if not store.write("INSERT OR IGNORE INTO slack_events VALUES (?,?)", (key, time.time())):
                    return
                question = re.sub(r"<@[A-Z0-9]+>", "", event.get("text", "")).strip()
                cid = store.conversation(question or "Slack conversation", event["channel"], event.get("thread_ts") or event["ts"])
                conversation = store.one("SELECT * FROM conversations WHERE id=?", (cid,))
                if question.lower() in ("", "hello", "hi", "help"):
                    text = "Chief and six specialists are ready. Ask an objective here or use the protected control room: " + origin
                    store.message(cid, "user", "chief", question)
                    store.message(cid, "assistant", "chief", text)
                    await slack_send(conversation, "chief", text, {})
                    return
                try:
                    run = store.enqueue(question, cid, source="slack")
                    await slack_send(conversation, "chief", "Objective queued. I’ll choose relevant specialists; all business data is synthetic demo evidence.", {"run_id": run["id"]})
                except ValueError as exc:
                    await slack_send(conversation, "chief", str(exc), {})
            handler = AsyncSocketModeHandler(slack_app, os.environ["SLACK_APP_TOKEN"])
            await handler.connect_async()
            app["slack_handler"] = handler
            print("DONTDIE_SLACK_CONNECTED shared persistent backend", flush=True)
        print("DONTDIE_WEB_READY " + origin, flush=True)

    async def cleanup(app):
        await engine.shutdown()
        if app.get("slack_handler"):
            await app["slack_handler"].close_async()
        store.db.close()

    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", action="store_true", help="Local HTTP development; disables the local Slack listener")
    args = parser.parse_args()
    Settings.from_env()
    if args.local:
        os.environ["CONTROL_ROOM_URL"] = "http://127.0.0.1:8080"
    logging.basicConfig(level=logging.WARNING)
    import fcntl
    lock_path = ROOT / "runs/controlroom.lock"
    lock_path.parent.mkdir(exist_ok=True)
    instance_lock = lock_path.open("a")
    try:
        fcntl.flock(instance_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("The control-room service is already running in this checkout.") from None
    web.run_app(make_app(slack=not args.local), host="127.0.0.1", port=8080, access_log=None)


if __name__ == "__main__":
    main()
