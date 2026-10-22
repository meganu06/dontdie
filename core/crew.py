import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from core.cloud import CloudRun
from core.settings import ROOT

FIRST = ("pmf", "retention", "competitor", "gtm", "product")
DISPLAY_ORDER = ("pmf", "retention", "competitor", "finance", "gtm", "product")


def role_data(role, data):
    keys = {
        "pmf": ("support", "accounts"), "retention": ("cancellations",),
        "competitor": ("competitors",), "gtm": ("deals", "relationships"),
        "product": ("product_usage", "engineering"),
        "finance": ("finance", "engineering", "deals"), "chief": ("kpis",),
    }
    return {key: data[key] for key in keys[role]}


async def run_crew(settings, question, send, cloud_factory=CloudRun):
    run_id = uuid.uuid4().hex[:12]
    cloud = cloud_factory(settings, run_id)
    data = json.loads((ROOT / "data" / "loopdesk.json").read_text())
    results = {}
    record = {"run_id": run_id, "question": question, "started_at": datetime.now(timezone.utc).isoformat(), "data_mode": "synthetic demo exports", "model": settings.model, "agents": results}
    await send("chief", "I’m checking six specialists and seven isolated Google sandboxes using synthetic Loopdesk demo data.", {"run_id": run_id})

    async def run(role, upstream=None):
        try:
            result = await asyncio.to_thread(cloud.agent, role, role_data(role, data), question, upstream)
        except Exception as exc:
            logging.error("Agent %s failed (%s)", role, type(exc).__name__)
            result = {"run_id": run_id, "agent": role, "status": "error", "summary": "Evidence unavailable; this agent failed and cannot support the decision.", "findings": [], "source_ids": [], "sandbox_id": cloud.sandboxes.get(role), "assumptions": [], "recommendation": "Retry after resolving the failed check.", "limitations": [type(exc).__name__], "confidence": "low"}
        results[role] = result
        return result

    try:
        await asyncio.to_thread(cloud.start)
        await asyncio.gather(*(run(role) for role in FIRST))
        await run("finance", {r: results[r] for r in ("retention", "gtm", "product")})
        for role in DISPLAY_ORDER:
            await send(role, results[role]["summary"], results[role])
        chief = await run("chief", dict(results))
        if chief["status"] == "ok":
            kpi = data["kpis"]
            summary = "\n".join([
                "Decision: " + chief["summary"],
                f"Demo business: {kpi['users']:,} users, +{kpi['users'] - kpi['previous_users']:,} this month; £{kpi['mrr_gbp']:,} MRR.",
                "Next step: " + chief["recommendation"],
                "Confidence: " + chief["confidence"] + " · synthetic demo evidence",
                "Caveat: " + ("; ".join(chief["limitations"])[:450] or "Live customer and revenue validation still required."),
            ])
        else:
            summary = "I cannot give a reliable verdict because the Chief check failed; review the specialist evidence and retry."
        await send("chief", summary, chief)
        return record
    finally:
        await asyncio.to_thread(cloud.close)
        record["cleanup_errors"] = cloud.cleanup_errors
        record["finished_at"] = datetime.now(timezone.utc).isoformat()
        folder = ROOT / "runs"
        folder.mkdir(exist_ok=True)
        (folder / (run_id + ".json")).write_text(json.dumps(record, indent=2))
