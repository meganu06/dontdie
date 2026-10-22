import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from core.scheduling import next_after, validate_schedule


def uid():
    return uuid.uuid4().hex[:16]


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA foreign_keys=ON;
        PRAGMA busy_timeout=5000;
        CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY,title TEXT,created REAL,updated REAL,slack_channel TEXT,slack_thread TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS slack_thread_unique ON conversations(slack_channel,slack_thread) WHERE slack_channel IS NOT NULL;
        CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,conversation_id TEXT,role TEXT,agent TEXT,content TEXT,run_id TEXT,created REAL);
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,conversation_id TEXT,objective TEXT,mode TEXT,agent TEXT,status TEXT,source TEXT,created REAL,started REAL,finished REAL,error TEXT,plan_json TEXT,result_json TEXT,parent_run TEXT,schedule_id TEXT,timezone TEXT);
        CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,run_id TEXT,agent TEXT,instruction TEXT,reason TEXT,depends_json TEXT,status TEXT,sandbox_id TEXT,started REAL,finished REAL,result_json TEXT,error TEXT,last_code TEXT);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,run_id TEXT,task_id TEXT,agent TEXT,kind TEXT,action_state TEXT,text TEXT,details_json TEXT,created REAL);
        CREATE TABLE IF NOT EXISTS schedules(id TEXT PRIMARY KEY,conversation_id TEXT,spec_json TEXT,status TEXT,next_run REAL,last_run TEXT,last_status TEXT,last_result TEXT,created REAL);
        CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,csrf TEXT,expires REAL);
        CREATE TABLE IF NOT EXISTS slack_events(id TEXT PRIMARY KEY,created REAL);
        CREATE INDEX IF NOT EXISTS run_queue ON runs(status,created);
        CREATE INDEX IF NOT EXISTS run_tasks ON tasks(run_id);
        CREATE INDEX IF NOT EXISTS run_events ON events(run_id,id);
        """)
        self.db.commit()

    def rows(self, sql, params=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, params).fetchall()]

    def one(self, sql, params=()):
        rows = self.rows(sql, params)
        return rows[0] if rows else None

    def write(self, sql, params=()):
        with self.lock, self.db:
            return self.db.execute(sql, params).rowcount

    def recover(self):
        with self.lock, self.db:
            now = time.time()
            self.db.execute("UPDATE tasks SET status='error',error='Interrupted by service restart; retry this task.',finished=? WHERE status IN ('running','queued','waiting') AND run_id IN (SELECT id FROM runs WHERE status='running')", (now,))
            self.db.execute("UPDATE runs SET status='interrupted',error='Service restarted during this run; retry to continue.',finished=? WHERE status='running'", (now,))
            self.db.execute("UPDATE schedules SET last_status='interrupted' WHERE last_run IN (SELECT id FROM runs WHERE status='interrupted')")

    def conversation(self, title="New objective", slack_channel=None, slack_thread=None):
        with self.lock, self.db:
            if slack_channel:
                found = self.one("SELECT * FROM conversations WHERE slack_channel=? AND slack_thread=?", (slack_channel, slack_thread))
                if found:
                    return found["id"]
            key, now = uid(), time.time()
            self.db.execute("INSERT INTO conversations VALUES (?,?,?,?,?,?)", (key, title[:90], now, now, slack_channel, slack_thread))
            return key

    def message(self, conversation_id, role, agent, content, run_id=None):
        now = time.time()
        with self.lock, self.db:
            self.db.execute("INSERT INTO messages(conversation_id,role,agent,content,run_id,created) VALUES (?,?,?,?,?,?)", (conversation_id, role, agent, content, run_id, now))
            self.db.execute("UPDATE conversations SET updated=? WHERE id=?", (now, conversation_id))

    def enqueue(self, objective, conversation_id=None, agent="chief", source="web", parent_run=None, schedule_id=None, timezone="Europe/London", add_message=True):
        from core.settings import AGENTS
        objective = str(objective).strip()
        if not 1 <= len(objective) <= 2000 or agent not in AGENTS:
            raise ValueError("Choose an agent and enter an objective of 1–2,000 characters.")
        with self.lock, self.db:
            if self.db.execute("SELECT COUNT(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0] >= 30:
                raise ValueError("The queue is full; wait for current work to finish.")
            if conversation_id and not self.one("SELECT id FROM conversations WHERE id=?", (conversation_id,)):
                raise ValueError("Conversation not found.")
            conversation_id = conversation_id or self.conversation(objective)
            key = uid()
            self.db.execute("INSERT INTO runs(id,conversation_id,objective,mode,agent,status,source,created,parent_run,schedule_id,timezone) VALUES (?,?,?,?,?,'queued',?,?,?,?,?)", (key, conversation_id, objective, "chief" if agent == "chief" else "agent", agent, source, time.time(), parent_run, schedule_id, timezone))
            if add_message:
                self.message(conversation_id, "user" if source != "schedule" else "system", agent, objective if source != "schedule" else "Scheduled run: " + objective, key)
            return self.one("SELECT * FROM runs WHERE id=?", (key,))

    def claim(self):
        with self.lock, self.db:
            row = self.one("SELECT * FROM runs WHERE status='queued' ORDER BY created LIMIT 1")
            if row:
                self.db.execute("UPDATE runs SET status='running',started=? WHERE id=?", (time.time(), row["id"]))
            return row

    def event(self, run_id, agent, kind, text, details=None, task_id=None, action_state="executed"):
        with self.lock, self.db:
            self.db.execute("INSERT INTO events(run_id,task_id,agent,kind,action_state,text,details_json,created) VALUES (?,?,?,?,?,?,?,?)", (run_id, task_id, agent, kind, action_state, text[:3000], json.dumps(details or {}), time.time()))

    def task(self, run_id, agent, instruction, reason, depends):
        key = uid()
        self.write("INSERT INTO tasks(id,run_id,agent,instruction,reason,depends_json,status) VALUES (?,?,?,?,?,?,'queued')", (key, run_id, agent, instruction, reason, json.dumps(depends)))
        return key

    def update_task(self, key, **values):
        allowed = {"status", "sandbox_id", "started", "finished", "result_json", "error", "last_code"}
        if not values or not set(values) <= allowed:
            raise ValueError("Invalid task update")
        self.write("UPDATE tasks SET " + ",".join(k + "=?" for k in values) + " WHERE id=?", (*values.values(), key))

    def complete(self, run, results, error=None):
        status = "error" if error else ("partial" if any(r.get("status") != "ok" for r in results.values()) else "done")
        summary = results.get("chief", results.get(run["agent"], {})).get("summary", error or "Completed")
        with self.lock, self.db:
            self.db.execute("UPDATE runs SET status=?,finished=?,result_json=?,error=? WHERE id=?", (status, time.time(), json.dumps(results), error, run["id"]))
            if run.get("schedule_id"):
                self.db.execute("UPDATE schedules SET last_status=?,last_result=? WHERE id=?", (status, summary[:1000], run["schedule_id"]))

    def create_schedule(self, raw, conversation_id=None):
        spec = validate_schedule(raw)
        deadline = next_after(spec, time.time())
        with self.lock, self.db:
            if self.db.execute("SELECT COUNT(*) FROM schedules WHERE status!='deleted'").fetchone()[0] >= 50:
                raise ValueError("The demo supports up to 50 schedules.")
            key = uid()
            self.db.execute("INSERT INTO schedules(id,conversation_id,spec_json,status,next_run,created) VALUES (?,?,?,'active',?,?)", (key, conversation_id, json.dumps(spec), deadline, time.time()))
        return self.schedule(key)

    def schedule(self, key):
        row = self.one("SELECT * FROM schedules WHERE id=?", (key,))
        if row:
            row["spec"] = json.loads(row.pop("spec_json"))
        return row

    def change_schedule(self, key, action):
        with self.lock, self.db:
            row = self.schedule(key)
            if not row or row["status"] == "deleted":
                raise ValueError("Schedule not found.")
            if action == "pause":
                self.db.execute("UPDATE schedules SET status='paused' WHERE id=?", (key,))
                self.db.execute("UPDATE runs SET status='cancelled',finished=? WHERE schedule_id=? AND status='queued'", (time.time(), key))
            elif action == "resume":
                self.db.execute("UPDATE schedules SET status='active',next_run=? WHERE id=?", (next_after(row["spec"], time.time()), key))
            elif action == "delete":
                self.db.execute("UPDATE schedules SET status='deleted',next_run=NULL WHERE id=?", (key,))
                self.db.execute("UPDATE runs SET status='cancelled',finished=? WHERE schedule_id=? AND status='queued'", (time.time(), key))
            else:
                raise ValueError("Choose pause, resume or delete.")
            self.db.execute("UPDATE schedules SET last_status='cancelled',last_result='Queued occurrence cancelled by operator.' WHERE id=? AND last_run IN (SELECT id FROM runs WHERE status='cancelled')", (key,))
        return self.schedule(key)

    def tick(self, now=None):
        now = time.time() if now is None else now
        created = []
        # One transaction makes a due occurrence and its queue entry atomic.
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                rows = self.rows("SELECT * FROM schedules WHERE status='active' AND next_run<=? ORDER BY next_run", (now,))
                for row in rows:
                    spec = json.loads(row["spec_json"])
                    pending = self.one("SELECT id FROM runs WHERE schedule_id=? AND status IN ('queued','running')", (row["id"],))
                    next_run = None if spec["kind"] == "once" else next_after(spec, now)
                    state = "completed" if spec["kind"] == "once" else "active"
                    self.db.execute("UPDATE schedules SET status=?,next_run=? WHERE id=?", (state, next_run, row["id"]))
                    if pending:
                        continue
                    cid = row["conversation_id"]
                    if not cid:
                        cid = uid()
                        self.db.execute("INSERT INTO conversations VALUES (?,?,?,?,NULL,NULL)", (cid, spec["title"], now, now))
                        self.db.execute("UPDATE schedules SET conversation_id=? WHERE id=?", (cid, row["id"]))
                    rid = uid()
                    self.db.execute("INSERT INTO runs(id,conversation_id,objective,mode,agent,status,source,created,schedule_id,timezone) VALUES (?,?,?,?,?,'queued','schedule',?,?,?)", (rid, cid, spec["objective"], "chief" if spec["agent"] == "chief" else "agent", spec["agent"], now, row["id"], spec["timezone"]))
                    self.db.execute("INSERT INTO messages(conversation_id,role,agent,content,run_id,created) VALUES (?,'system',?,?,?,?)", (cid, spec["agent"], "Scheduled run: " + spec["objective"], rid, now))
                    self.db.execute("UPDATE conversations SET updated=? WHERE id=?", (now, cid))
                    self.db.execute("UPDATE schedules SET last_run=?,last_status='queued' WHERE id=?", (rid, row["id"]))
                    created.append(rid)
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
        return created

    def state(self, conversation_id=None, run_id=None):
        conversations = self.rows("SELECT * FROM conversations ORDER BY updated DESC LIMIT 50")
        cid = conversation_id or (conversations[0]["id"] if conversations else None)
        runs = self.rows("SELECT id,conversation_id,objective,agent,status,source,created,started,finished,error,schedule_id FROM runs WHERE conversation_id=? ORDER BY created DESC LIMIT 40", (cid,))
        selected = run_id or (runs[0]["id"] if runs else None)
        run = self.one("SELECT * FROM runs WHERE id=? AND conversation_id=?", (selected, cid))
        tasks = self.rows("SELECT id,run_id,agent,instruction,reason,depends_json,status,sandbox_id,started,finished,error,result_json FROM tasks WHERE run_id=? ORDER BY rowid", (run["id"] if run else None,))
        for task in tasks:
            result = json.loads(task.pop("result_json") or "{}")
            task["summary"] = result.get("summary", "")
            task["depends_on"] = json.loads(task.pop("depends_json") or "[]")
        events = self.rows("SELECT id,run_id,task_id,agent,kind,action_state,text,created FROM events WHERE run_id=? ORDER BY id DESC LIMIT 150", (run["id"] if run else None,))
        schedules = [self.schedule(r["id"]) for r in self.rows("SELECT id FROM schedules WHERE status!='deleted' ORDER BY created DESC")]
        if run:
            run["plan"] = json.loads(run.pop("plan_json") or "{}")
            run.pop("result_json", None)
        return {"conversations": conversations, "conversation_id": cid, "messages": list(reversed(self.rows("SELECT * FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT 200", (cid,)))), "runs": runs, "run": run, "tasks": tasks, "events": list(reversed(events)), "schedules": schedules, "queue_count": self.one("SELECT COUNT(*) AS n FROM runs WHERE status='queued'")["n"], "data_mode": "Synthetic Loopdesk demo data", "server_time": time.time()}
