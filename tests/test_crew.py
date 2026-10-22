import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

from bot import EventDeduper, SlackPublisher
from core.analytics import analyse
from core.cloud import concise
from core.settings import AGENTS, ROOT, Settings
from core.crew import run_crew

DATA = json.loads((ROOT / "data/loopdesk.json").read_text())


def by_claim(role):
    return {f["claim"]: f["value"] for f in analyse(role, DATA)}


def test_support_deduplicates_accounts():
    facts = by_claim("pmf")
    assert facts["Team-account requests"] == 18
    assert facts["Unique accounts requesting teams"] == 14
    assert facts["Requesting agencies with at least 20 staff"] == 3


def test_cash_and_arr_payback_are_not_confused():
    facts = by_claim("finance")
    assert facts["Baseline runway"] == 9
    assert facts["Runway after incremental build cost"] == 8.4
    assert facts["Payback assuming 100% stalled pipeline converts"] == 25
    assert facts["Payback assuming 50% stalled pipeline converts"] == 50
    assert facts["Payback assuming 0% stalled pipeline converts"] is None


def test_chief_deduplicates_across_sources():
    upstream = {r: {"findings": analyse(r, DATA), "status": "ok"} for r in ("pmf", "retention", "gtm")}
    facts = {f["claim"]: f["value"] for f in analyse("chief", DATA, upstream)}
    assert facts["Unique accounts across demand, churn and pipeline signals"] == 14


def test_usage_has_explicit_denominator():
    fact = analyse("product", DATA)[0]
    assert fact["value"] == 60
    assert "60/100" in fact["unit"]
    empty = {**DATA, "product_usage": []}
    assert analyse("product", empty)[0]["value"] is None


def test_slack_thread_and_literal_content():
    client = AsyncMock()
    publisher = SlackPublisher(client, "C1", "123.456", delay=0)
    asyncio.run(publisher.send("pmf", "<!channel> inspect <script>"))
    call = client.chat_postMessage.call_args.kwargs
    assert call["thread_ts"] == "123.456"
    assert call["username"] == "Don't Die · PMF"
    assert "<!channel>" not in call["text"]
    assert call["blocks"][0]["text"]["type"] == "plain_text"


def test_dedupe_and_concise():
    deduper = EventDeduper()
    assert not deduper.duplicate("event1")
    assert deduper.duplicate("event1")
    assert len(concise("word " * 30).split()) <= 20


def test_seven_agents_failure_is_visible_and_cleanup_happens(monkeypatch, tmp_path):
    import core.crew as module
    (tmp_path / "data").mkdir()
    (tmp_path / "data/loopdesk.json").write_text(json.dumps(DATA))
    monkeypatch.setattr(module, "ROOT", tmp_path)

    class FakeCloud:
        def __init__(self, settings, run_id):
            self.sandboxes = {}
            self.cleanup_errors = []
        def start(self):
            pass
        def agent(self, role, data, question, upstream):
            self.sandboxes[role] = "isolated-" + role
            if role == "competitor":
                raise RuntimeError("simulated unavailable evidence")
            if role == "chief":
                assert len(upstream) == 6
                assert upstream["competitor"]["status"] == "error"
            return {"agent": role, "summary": "Evidence checked.", "status": "ok", "findings": [], "recommendation": "Run a pilot.", "confidence": "low", "limitations": [], "sandbox_id": self.sandboxes[role]}
        def close(self):
            self.cleanup_errors.append("cleanup was called")

    sent = []
    async def send(role, text, result):
        sent.append(role)
    record = asyncio.run(run_crew(Settings("test"), "Question", send, FakeCloud))
    assert set(record["agents"]) == set(AGENTS)
    assert record["agents"]["competitor"]["status"] == "error"
    assert sent == ["chief", "pmf", "retention", "competitor", "finance", "gtm", "product", "chief"]
    assert record["cleanup_errors"] == ["cleanup was called"]
    assert list((tmp_path / "runs").glob("*.json"))
