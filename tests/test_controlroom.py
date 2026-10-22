import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone

import pytest
from aiohttp import CookieJar
from aiohttp.test_utils import TestClient, TestServer

from core.engine import Engine
from core.planner import Plan, validate_plan
from core.scheduling import next_after, validate_schedule
from core.settings import Settings
from core.store import Store
from server import make_app


def spec(**changes):
    return {"agent": "finance", "objective": "Review runway", "title": "Runway", "kind": "interval", "interval_minutes": 1, "timezone": "Europe/London", **changes}


def test_schedule_claim_is_persistent_and_not_duplicated(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = Store(path)
    schedule = store.create_schedule(spec())
    due = schedule["next_run"]
    assert len(store.tick(due + .1)) == 1
    assert store.tick(due + .1) == []
    # A second occurrence is coalesced while the first is queued.
    assert store.tick(due + 61) == []
    store.db.close()
    reopened = Store(path)
    assert reopened.schedule(schedule["id"])["last_status"] == "queued"
    assert len(reopened.rows("SELECT * FROM runs")) == 1
    assert reopened.state()["messages"][0]["role"] == "system"
    run = reopened.claim()
    assert reopened.schedule(schedule["id"])["last_status"] == "running"
    tid = reopened.task(run["id"], "finance", "Review runway", "Scheduled", [])
    reopened.update_task(tid, status="running")
    other = reopened.conversation("Another conversation")
    reopened.event(run["id"], "finance", "FOUND", "Evidence checked", task_id=tid)
    state = reopened.state(other)
    assert state["tasks"] == []
    assert state["active_tasks"][0]["id"] == tid
    assert state["live_events"][0]["task_id"] == tid


def test_pause_resume_delete_and_oneoff(tmp_path):
    store = Store(tmp_path / "db")
    item = store.create_schedule(spec())
    store.change_schedule(item["id"], "pause")
    assert store.tick(time.time() + 1000) == []
    resumed = store.change_schedule(item["id"], "resume")
    assert resumed["status"] == "active"
    store.change_schedule(item["id"], "delete")
    assert store.state()["schedules"] == []
    once = store.create_schedule(spec(kind="once", timezone="UTC", when_local=datetime.fromtimestamp(time.time()+90, timezone.utc).replace(tzinfo=None).isoformat()))
    assert len(store.tick(once["next_run"] + 1)) == 1
    assert store.schedule(once["id"])["status"] == "completed"
    assert store.tick(once["next_run"] + 1000) == []


def test_timezone_and_daylight_saving_are_explicit():
    schedule = validate_schedule(spec(kind="daily", time_local="01:30"))
    after = datetime(2027, 3, 27, 23, 0, tzinfo=timezone.utc).timestamp()
    # London 01:30 doesn't exist on spring-forward day; advance to local 02:00.
    assert datetime.fromtimestamp(next_after(schedule, after), timezone.utc).isoformat() == "2027-03-28T01:00:00+00:00"
    with pytest.raises(ValueError):
        validate_schedule(spec(timezone="invented/zone"))
    with pytest.raises(ValueError):
        validate_schedule(spec(interval_minutes=0))


def test_restart_marks_interrupted_work_and_preserves_queue(tmp_path):
    store = Store(tmp_path / "db")
    first = store.enqueue("Assess churn")
    second = store.enqueue("Review runway")
    claimed = store.claim()
    task = store.task(claimed["id"], "retention", "Check cancellations", "Relevant", [])
    store.update_task(task, status="running")
    chief = store.task(claimed["id"], "chief", "Reconcile findings", "Await specialists", [])
    store.update_task(chief, status="waiting")
    store.recover()
    assert store.one("SELECT status FROM runs WHERE id=?", (first["id"],))["status"] == "interrupted"
    assert store.one("SELECT status FROM tasks WHERE id=?", (task,))["status"] == "error"
    assert store.one("SELECT status FROM tasks WHERE id=?", (chief,))["status"] == "error"
    assert store.claim()["id"] == second["id"]


def test_chief_plan_rejects_cycles_and_unrequested_scheduling():
    with pytest.raises(ValueError, match="cycle"):
        validate_plan(Plan(reply="Plan", tasks=[{"agent":"pmf","instruction":"Check","reason":"Demand","depends_on":["retention"]},{"agent":"retention","instruction":"Check","reason":"Churn","depends_on":["pmf"]}]), "Review demand")
    with pytest.raises(ValueError, match="explicit"):
        validate_plan(Plan(reply="Plan", schedules=[spec()]), "Review runway")


def test_engine_runs_selected_specialists_and_separate_sandboxes(tmp_path):
    store = Store(tmp_path / "db")
    queued = store.enqueue("Review cancellation reasons")
    run = store.claim()
    executed = []

    class FakeCloud:
        def __init__(self, settings, run_id, event=None):
            self.model = None
            self.sandboxes, self.cleanup_errors = {}, []
            self.event = event
        def start(self):
            pass
        def agent(self, role, data, question, upstream):
            executed.append(role)
            self.sandboxes[role] = "test-sandbox-" + role
            self.event(role,"SANDBOX","Created",{"sandbox_id": self.sandboxes[role]})
            return {"agent": role,"status":"ok","summary":"Evidence checked.","explanation":"A test result.","recommendation":"Validate the finding.","findings":[],"source_ids":[],"confidence":"low","sandbox_id":self.sandboxes[role],"proposed_actions":["Interview affected customers."]}
        def close(self):
            pass

    def planner(*args):
        return Plan(reply="I will check cancellation evidence.", tasks=[{"agent":"retention","instruction":"Count reasons and lost MRR","reason":"The question is about churn."}])
    engine = Engine(store, Settings("test"), FakeCloud, planner)
    asyncio.run(engine.execute(run))
    assert executed == ["retention", "chief"]
    state = store.state(queued["conversation_id"])
    assert state["run"]["status"] == "done"
    assert len({t["sandbox_id"] for t in state["tasks"]}) == 2
    assert any(e["action_state"] == "proposed" for e in state["events"])


def test_web_auth_csrf_origin_and_schedule_controls(tmp_path):
    async def scenario():
        store = Store(tmp_path / "db")
        app = await make_app(store, Settings("test"), start_background=False, slack=False, auth_hash=hashlib.sha256(b"test-access-key").hexdigest(), origin="http://localhost", secure=False)
        async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as client:
            assert (await client.get('/api/state')).status == 401
            assert (await client.post('/api/login', json={"key":"test-access-key"}, headers={"Origin":"https://attacker.example"})).status == 403
            response = await client.post('/api/login',json={"key":"test-access-key"},headers={"Origin":"http://localhost"})
            assert response.status == 200
            csrf = (await response.json())["csrf"]
            assert 'HttpOnly' in response.headers['Set-Cookie']
            assert (await client.post('/api/chat',json={"objective":"Test"},headers={"Origin":"http://localhost"})).status == 403
            headers={"Origin":"http://localhost","X-CSRF-Token":csrf}
            response=await client.post('/api/chat',json={"objective":"Review churn","timezone":"Europe/London"},headers=headers)
            assert response.status == 202
            queued=await response.json()
            assert queued['status']=='queued'
            response=await client.post('/api/schedules',json=spec(),headers=headers)
            assert response.status == 201
            schedule=await response.json()
            response=await client.post('/api/schedules/'+schedule['id']+'/pause',json={},headers=headers)
            assert (await response.json())['status']=='paused'
            task=store.task(queued['id'],'retention','Inspect churn','Relevant',[])
            store.update_task(task,status='error',error='Simulated test failure')
            response=await client.post('/api/tasks/'+task+'/retry',json={},headers=headers)
            assert response.status==202
            retry=await response.json()
            assert retry['id']!=queued['id'] and retry['parent_run']==queued['id']
            response=await client.post('/api/tasks/'+task+'/followup',json={'objective':'Explain the uncertainty'},headers=headers)
            assert response.status==202
            followup=await response.json()
            assert followup['agent']=='retention' and followup['conversation_id']==queued['conversation_id']
            assert (await client.get('/api/state')).status == 200
    asyncio.run(scenario())


def test_specialist_failure_remains_visible_to_chief(tmp_path):
    store = Store(tmp_path / "db")
    queued = store.enqueue("Review churn")
    run = store.claim()
    observed = {}

    class FailingCloud:
        def __init__(self, settings, run_id, event=None):
            self.model = None
            self.sandboxes, self.cleanup_errors = {}, []
        def start(self):
            pass
        def agent(self, role, data, question, upstream):
            if role == "retention":
                raise TimeoutError("Simulated cloud timeout")
            observed.update(upstream)
            return {"agent": role, "status": "ok", "summary": "Retention evidence is unavailable.", "confidence": "low", "findings": [], "proposed_actions": []}
        def close(self):
            observed["cleanup"] = True

    def planner(*args):
        return Plan(reply="Check churn", tasks=[{"agent": "retention", "instruction": "Check cancellations", "reason": "Churn question"}])

    asyncio.run(Engine(store, Settings("test"), FailingCloud, planner).execute(run))
    state = store.state(queued["conversation_id"])
    assert state["run"]["status"] == "partial"
    assert next(t for t in state["tasks"] if t["agent"] == "retention")["status"] == "error"
    assert observed["retention"]["status"] == "error"
    assert observed["cleanup"]
    assert any(e["kind"] == "ERROR" for e in state["events"])
