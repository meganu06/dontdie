import asyncio
import json
import logging
import time

from core.cloud import CloudRun
from core.crew import role_data
from core.planner import make_plan
from core.settings import ROOT


class Engine:
    def __init__(self, store, settings, cloud_factory=CloudRun, planner=make_plan):
        self.store, self.settings = store, settings
        self.cloud_factory, self.planner = cloud_factory, planner
        self.stopping = False
        self.background = []
        self.slack_send = None

    async def start(self):
        self.store.recover()
        self.background = [asyncio.create_task(self.worker()), asyncio.create_task(self.scheduler())]

    async def shutdown(self):
        self.stopping = True
        try:
            await asyncio.wait_for(asyncio.gather(*self.background), timeout=180)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            for task in self.background:
                task.cancel()

    async def scheduler(self):
        while not self.stopping:
            try:
                for rid in self.store.tick():
                    self.store.event(rid, "chief", "SCHEDULE", "Scheduled occurrence queued by the cloud service.")
            except Exception as exc:
                logging.error("Scheduler tick failed: %s", type(exc).__name__)
            await asyncio.sleep(2)

    async def worker(self):
        while not self.stopping:
            run = self.store.claim()
            if run:
                await self.execute(run)
            else:
                await asyncio.sleep(1)

    async def publish(self, run, agent, text, result=None):
        self.store.message(run["conversation_id"], "assistant", agent, text, run["id"])
        if self.slack_send:
            conversation = self.store.one("SELECT * FROM conversations WHERE id=?", (run["conversation_id"],))
            if conversation and conversation["slack_channel"]:
                try:
                    await self.slack_send(conversation, agent, text, result or {"run_id": run["id"]})
                except Exception as exc:
                    self.store.event(run["id"], agent, "ERROR", "Slack delivery failed; the result is preserved in the control room.", {"error": type(exc).__name__})

    async def execute(self, run):
        results, task_ids, created_schedules = {}, {}, []
        cloud = None
        error = None

        def event(agent, kind, text, details=None):
            details = details or {}
            tid = task_ids.get(agent)
            if tid and details.get("sandbox_id"):
                self.store.update_task(tid, sandbox_id=details["sandbox_id"])
            if tid and kind == "CODE":
                self.store.update_task(tid, last_code=details.get("code", ""))
            self.store.event(run["id"], agent, kind, text, details, tid)

        async def execute_agent(agent, instruction, upstream):
            tid = task_ids[agent]
            self.store.update_task(tid, status="running", started=time.time())
            event(agent, "DECIDE", "Run this evidence check because Chief assigned it to answer the current objective.", {"instruction": instruction})
            try:
                context = "Founder objective: " + run["objective"] + "\nAssignment: " + instruction
                if created_schedules and agent == "chief":
                    context += "\nActual schedules successfully created: " + json.dumps(created_schedules)
                result = await asyncio.to_thread(cloud.agent, agent, role_data(agent, data), context, upstream)
                result["explanation"] = result.get("explanation", "")[:4000]
                self.store.update_task(tid, status="done", finished=time.time(), result_json=json.dumps(result))
                for proposed in result.get("proposed_actions", [])[:3]:
                    self.store.event(run["id"], agent, "RECOMMENDATION", proposed, task_id=tid, action_state="proposed")
                if agent == "chief":
                    text = result.get("explanation") or result["summary"]
                    text += "\n\nNext step (proposed): " + result.get("recommendation", "Review the evidence.")
                    text += "\nConfidence: " + result.get("confidence", "low") + " · synthetic demo evidence"
                else:
                    text = result["summary"]
                await self.publish(run, agent, text, result)
            except Exception as exc:
                label = type(exc).__name__
                result = {"agent": agent, "run_id": run["id"], "status": "error", "findings": [], "source_ids": [], "summary": "Evidence check failed; no recommendation is supported by this task.", "confidence": "low", "limitations": [label], "sandbox_id": cloud.sandboxes.get(agent)}
                self.store.update_task(tid, status="error", finished=time.time(), error=label + ": cloud evidence check failed; retry this task.", result_json=json.dumps(result))
                event(agent, "ERROR", "Cloud evidence check failed; inspect the task and retry.", {"error": label})
                await self.publish(run, agent, result["summary"], result)
            results[agent] = result

        try:
            data = json.loads((ROOT / "data/loopdesk.json").read_text())
            cloud = self.cloud_factory(self.settings, run["id"], event=event)
            if run["mode"] == "chief":
                chief_id = self.store.task(run["id"], "chief", run["objective"], "Choose relevant specialists and reconcile their evidence.", [])
                task_ids["chief"] = chief_id
                self.store.update_task(chief_id, status="running", started=time.time())
                event("chief", "PLAN", "Choosing specialists for this objective.")
                history = self.store.rows("SELECT role,agent,content FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT 12", (run["conversation_id"],))
                plan = await asyncio.to_thread(self.planner, cloud.model, self.settings.model, run["objective"], list(reversed(history)), run.get("timezone") or "Europe/London")
                # Scheduled analyses must never recursively create more schedules.
                if run["source"] == "schedule":
                    plan.schedules = []
                    plan.execute_now = True
                self.store.write("UPDATE runs SET plan_json=? WHERE id=?", (plan.model_dump_json(), run["id"]))
                await self.publish(run, "chief", "Proposed plan: " + plan.reply)
                for spec in plan.schedules:
                    try:
                        schedule = self.store.create_schedule(spec.model_dump(), run["conversation_id"])
                        created_schedules.append({"id": schedule["id"], "title": schedule["spec"]["title"], "next_run": schedule["next_run"], "timezone": schedule["spec"]["timezone"]})
                        event("chief", "SCHEDULE", "Created schedule: " + schedule["spec"]["title"], schedule)
                        await self.publish(run, "chief", "Schedule created: " + schedule["spec"]["title"] + " · " + schedule["spec"]["timezone"] + ". View next run and controls in Schedules.")
                    except ValueError as exc:
                        event("chief", "ERROR", "Schedule not created: " + str(exc))
                        await self.publish(run, "chief", "Schedule not created: " + str(exc))
                assignments = plan.tasks if plan.execute_now else []
                for assignment in assignments:
                    task_ids[assignment.agent] = self.store.task(run["id"], assignment.agent, assignment.instruction, assignment.reason, assignment.depends_on)
                    event("chief", "DELEGATE", assignment.agent.upper() + ": " + assignment.instruction + " Because " + assignment.reason, assignment.model_dump())
                self.store.update_task(chief_id, status="waiting")
            else:
                assignments = []
                task_ids[run["agent"]] = self.store.task(run["id"], run["agent"], run["objective"], "Direct operator or scheduled agent request.", [])

            await asyncio.to_thread(cloud.start)
            parent = {}
            if run.get("parent_run"):
                previous = self.store.one("SELECT result_json FROM runs WHERE id=?", (run["parent_run"],))
                parent = json.loads(previous["result_json"] or "{}") if previous else {}
            if run["mode"] == "chief":
                pending = {a.agent: a for a in assignments}
                while pending:
                    ready = [a for a in pending.values() if set(a.depends_on) <= set(results)]
                    if not ready:
                        raise ValueError("No executable task in the dependency plan")
                    await asyncio.gather(*(execute_agent(a.agent, a.instruction, {key: results[key] for key in a.depends_on}) for a in ready))
                    for assignment in ready:
                        pending.pop(assignment.agent)
                await execute_agent("chief", "Answer the founder, synthesise only requested specialist results, and distinguish created schedules from proposed business actions. " + plan.reply, dict(results) or parent)
            else:
                await execute_agent(run["agent"], run["objective"], parent)
        except Exception as exc:
            error = str(exc)[:300] if isinstance(exc, ValueError) else type(exc).__name__ + ": orchestration failed; retry the run."
            event("chief", "ERROR", error)
            for tid in task_ids.values():
                task = self.store.one("SELECT status FROM tasks WHERE id=?", (tid,))
                if task and task["status"] not in ("done", "error"):
                    self.store.update_task(tid, status="error", finished=time.time(), error=error)
            await self.publish(run, "chief", "This run could not complete: " + error)
        finally:
            if cloud:
                await asyncio.to_thread(cloud.close)
                for item in cloud.cleanup_errors:
                    event("chief", "ERROR", "Cloud cleanup needs attention; sandbox TTL remains one hour.", item)
            self.store.complete(run, results, error)
            event("chief", "COMPLETE", "Run finished; recommendations remain proposed actions.", {"successful_agents": [k for k, v in results.items() if v.get("status") == "ok"]})
            print("DONTDIE_RUN_COMPLETE " + run["id"], flush=True)
