# Don't Die

Seven Gemini agents in Slack pressure-test a founder's decision. Chief coordinates PMF, Retention, Competitor, Finance, GTM and Product. Each agent runs its calculation in a **different Google-managed code-execution sandbox**; every decision creates seven sandbox IDs and removes them afterwards. Slack is the interface, not the sandbox.

**Business data is synthetic.** `data/loopdesk.json` is a fictional Loopdesk dataset based on the demo brief, not a live SaaS connection. Gemini inference and Google sandbox execution are real. We do not claim live Stripe, Xero, HubSpot, Zendesk, Intercom, PostHog, Linear, G2 or website access. Nothing charges customers, changes prices or sends outreach.

## Run locally

Requires Python 3.11+, an authenticated Google Cloud project with billing and Agent Platform/Vertex AI enabled, and a Slack app with Socket Mode enabled.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill .env locally. Never commit tokens.
gcloud auth application-default login
python bot.py
```

Install the app into the workspace and invite `@crew` to the configured channel. Required bot scopes are `app_mentions:read`, `chat:write`, and `chat:write.customize`; the app token needs `connections:write`. Subscribe to the `app_mention` bot event. See `slack-manifest.json`.

1. Send `@crew hello` to test the connection (no cloud computation).
2. Send `@crew Should Loopdesk build team accounts next?` to run all seven agents.
3. Chief acknowledges in a thread. Six specialists reply, then Chief gives a recommendation, next step, confidence and caveat. Replies are paced at least two seconds apart. Cloud cold starts can take several minutes.

Run the same decision without posting to Slack:

```sh
python bot.py --once "Should Loopdesk build team accounts next?"
pip install pytest
python -m pytest -q
```

Results, source references, findings, distinct sandbox IDs and cleanup failures are saved in ignored `runs/<run_id>.json` files. Source IDs refer to records in the synthetic fixture. Logs avoid tokens and full API exception payloads. Use only one Socket Mode listener per app for this demo; two laptops running it can split events unpredictably.

## The seven-agent contract

| Agent | Task and sandbox tool | Supplied data |
|---|---|---|
| Chief | Deduplicate evidence, report users/growth/MRR, challenge assumptions and choose a next step | KPI snapshot and six specialist results |
| PMF | Count unique feature-demand accounts and segments, separating tickets from customers | Synthetic support records and account profiles |
| Retention | Count cancellation reasons and associated cancelled MRR | Synthetic Stripe cancellation export |
| Competitor | Compare team features and published seat-price snapshots | Three fictional competitor snapshots |
| Finance | Calculate incremental cost, runway, conversion-sensitive gross-profit payback and price hypotheses | Synthetic Xero, engineering and HubSpot data; specialist results |
| GTM | Group stalled deals by segment; quantify unbooked ARR; inspect supplied relationships | Synthetic HubSpot export; empty network data is reported as missing |
| Product | Compute sharing adoption with its denominator; identify pilot scope and effort | Synthetic PostHog usage and Linear estimate |

Chief dispatches PMF, Retention, Competitor, GTM and Product concurrently. Finance follows with GTM, Product and Retention context. Chief receives all six results and runs a seventh independent sandbox check. Agent-to-agent communication is structured JSON through the coordinator, shown as short named Slack replies in one thread. Slack text is never parsed as commands from another agent.

Each result contains `run_id`, `agent`, `status`, `findings` (claim, value, unit, period, source_ids, account_ids), `assumptions`, `limitations`, `recommendation`, `confidence`, and `sandbox_id`. Failed agents remain visible and lower Chief's confidence. There is no eighth Sceptic agent: Chief handles that responsibility.

The demo uses bounded, audited Python calculation tools in separate cloud sandboxes and one isolated Gemini request per agent. It does not implement open-ended autonomous coding, persistent agent memory, daily scheduling or trained willingness-to-pay prediction. The coordinator makes network/model calls; the code sandboxes receive only each role's selected input and no credentials. Sandbox TTL is one hour as a cleanup fallback.

## Financial assumptions

The six-week £30k build is assumed to be **additional contractor spending**, on top of existing payroll and monthly net burn. £450k cash and £50k net monthly burn produce 9 months of baseline runway and 8.4 months after that one-off cost, excluding any new revenue. £18k pipeline is annual recurring value, not monthly revenue or booked business. At 100% conversion and 80% gross margin it supports £1,200 monthly gross profit, so build payback is 25 months after launch; at 50%, 50 months; at zero, no payback. These simplified scenarios exclude ramp time. £15/£20/£25 prices are unvalidated experiments, not individual willingness-to-pay predictions.

## Three-person handoff

| Owner | Build responsibility | Final check |
|---|---|---|
| Emil + Codex | Google runtime, seven sandboxes, orchestration, calculations, deployment and GitHub integration | Full cloud rehearsal and seven distinct sandbox IDs |
| Megan | Slack app configuration, `#decisions`, membership and judging walkthrough | Mention `@crew`, verify threaded names/icons and invite teammates |
| Third teammate | Review demo inputs, agent prompts and pitch; replace fixtures only with authorized exports | Check sources, assumptions, arithmetic and one failure scenario |

Keep edits in separate files where possible and pull before pushing. The central implementation is ready for teammates to review; avoid starting a second bot while the cloud service is running.

## Cloud deployment

`infra/startup.sh` boots a small Compute Engine VM, checks out an exact public GitHub commit from instance metadata, installs dependencies, reads its environment from Secret Manager using the VM's service account, and starts `dontdie.service`. No credential files or account passwords are deployed. The VM needs Agent Platform User and access to the specific environment secret. It makes outbound Slack/Gemini calls and exposes no application port. See `infra/OPERATIONS.md` for operating and stopping it.
