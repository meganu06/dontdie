"""Real Gemini inference and seven isolated, short-lived Google code sandboxes."""
import json
import logging
from pathlib import Path

import agentplatform
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import Literal

from agents.roles import COMMON, ROLES


class AgentReply(BaseModel):
    summary: str
    recommendation: str
    confidence: Literal["low", "medium"]
    source_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def concise(text, limit=20):
    text = " ".join(text.split())
    words = text.split()
    return text if len(words) <= limit else " ".join(words[:limit]).rstrip(".,;:") + "…"


class CloudRun:
    def __init__(self, settings, run_id):
        self.settings = settings
        self.run_id = run_id
        self.platform = agentplatform.Client(project=settings.project, location=settings.sandbox_location, http_options={"timeout": 120000})
        self.model = genai.Client(vertexai=True, project=settings.project, location=settings.location, http_options=types.HttpOptions(timeout=90000))
        self.runtime = None
        self.sandboxes = {}
        self.cleanup_errors = []

    def start(self):
        self.runtime = self.platform.runtimes.create(config={"display_name": "dontdie-" + self.run_id})

    def tool(self, agent, data, upstream):
        operation = self.platform.sandboxes.create(
            name=self.runtime.api_resource.name,
            spec={"code_execution_environment": {}},
            config={"display_name": "dontdie-" + agent + "-" + self.run_id, "ttl": "3600s"},
        )
        sandbox_id = operation.response.name
        self.sandboxes[agent] = sandbox_id
        # Only this agent's input is passed. No credentials or host environment enter the sandbox.
        source = Path(__file__).with_name("analytics.py").read_text()
        payload = json.dumps({"data": data, "upstream": upstream})
        code = source + "\nimport json\npayload = json.loads(" + repr(payload) + ")\nprint(json.dumps(analyse(" + repr(agent) + ", payload['data'], payload['upstream'])))\n"
        response = self.platform.sandboxes.execute_code(name=sandbox_id, input_data={"code": code})
        output = ""
        for chunk in response.outputs or []:
            if chunk.mime_type == "application/json":
                value = json.loads(chunk.data)
                if value.get("msg_err"):
                    raise RuntimeError("Sandbox calculation failed")
                output += value.get("msg_out", "")
        if not output.strip():
            raise RuntimeError("Sandbox returned no calculation")
        return json.loads(output), sandbox_id

    def agent(self, agent, data, question, upstream=None):
        upstream = upstream or {}
        findings, sandbox_id = self.tool(agent, data, upstream)
        evidence = {"question": question, "data_mode": "synthetic demo", "findings": findings, "specialist_results": upstream}
        response = self.model.models.generate_content(
            model=self.settings.model,
            contents=json.dumps(evidence),
            config=types.GenerateContentConfig(
                system_instruction=COMMON + "\nYour role: " + ROLES[agent],
                response_mime_type="application/json", response_schema=AgentReply,
                temperature=0.2, max_output_tokens=4096,
            ),
        )
        reply = AgentReply.model_validate_json(response.text).model_dump()
        allowed_sources = {s for f in findings for s in f["source_ids"]}
        for result in upstream.values():
            allowed_sources.update(s for f in result.get("findings", []) for s in f["source_ids"])
        reply["source_ids"] = [s for s in reply["source_ids"] if s in allowed_sources]
        reply["summary"] = concise(reply["summary"])
        reply["recommendation"] = concise(reply["recommendation"])
        if any(r.get("status") != "ok" for r in upstream.values()):
            reply["confidence"] = "low"
        return dict(run_id=self.run_id, agent=agent, status="ok", findings=findings, sandbox_id=sandbox_id, **reply)

    def close(self):
        for agent, name in self.sandboxes.items():
            try:
                self.platform.sandboxes.delete(name=name)
            except Exception as exc:
                self.cleanup_errors.append({"resource": name, "error": type(exc).__name__})
                logging.warning("Sandbox cleanup pending: %s", agent)
        if self.runtime:
            try:
                self.runtime.delete()
            except Exception as exc:
                self.cleanup_errors.append({"resource": self.runtime.api_resource.name, "error": type(exc).__name__})
                logging.warning("Runtime cleanup pending for %s", self.run_id)
