# Don’t Die — control room

One Chief, six specialists, a visible work queue and schedules that keep running on Google Cloud. The seven roles are **Chief, PMF, Retention, Competitor, Finance, GTM and Product**.

**All business inputs are synthetic Loopdesk demo data.** Gemini inference and Google code-sandbox execution are real. There are no live Stripe, Zendesk, Intercom, Xero, HubSpot, PostHog, Linear, G2 or competitor-site integrations. Recommendations never change prices, charge customers, contact people or edit external systems.

## Open the deployed app

HTTPS URL: **https://dontdie.136.70.191.164.sslip.io**

The operator access key is delivered privately, not committed. On the builder’s laptop it is in ignored `runs/control-room-access.txt`. A key grants control of all demo conversations, agents and schedules. Sign-in uses an HTTP-only session cookie with CSRF and origin checks. Secrets stay on the server in Secret Manager and a restricted local environment file.

## Demo walkthrough

1. Sign in, then ask Chief: **“Assess cancellation reasons and cancelled revenue; focus only on retention evidence.”** Watch Chief choose Retention rather than running every specialist.
2. Inspect a task. Expand sources, findings, the full Google sandbox ID and the actual Python code. Public activity records show instructions, execution, findings and failures; recommendations are marked **proposed**.
3. Use **Request follow-up** to ask “What are the strongest limitations of this conclusion?” Or use **Run** on any of the seven agents.
4. Ask Chief: **“Schedule Finance to review runway in two minutes.”** Open Schedules to see its timezone, next run and status. Close the browser: the VM scheduler still executes the task. Reopen and inspect its last result.
5. Create an interval/daily/weekly schedule, then test Pause, Resume and Delete. In History, reopen earlier conversations and runs.
6. In Slack `#decisions`, send **`@crew hello`**, then a decision question. Slack-initiated conversations appear in the same web workspace. Web follow-ups inside those conversations also reply in their Slack thread. New web-only conversations are not broadcast to Slack.

Cloud work usually takes tens of seconds to a few minutes. The queue is serial between objectives; independent specialist tasks within a Chief plan run concurrently.

## Agent responsibilities

| Agent | Evidence and responsibility |
|---|---|
| Chief | Select relevant specialists, issue instructions, validate dependencies, reconcile results, report users/growth/MRR and propose the next step. Create requested analysis schedules. |
| PMF | Support-ticket feature demand, unique accounts and company segments. |
| Retention | Cancellation reasons, already-lost MRR and churn hypotheses. |
| Competitor | Compare supplied fictional team-feature and price snapshots. |
| Finance | Incremental build costs, cash runway, gross-profit payback and unvalidated price experiments. |
| GTM | Stalled deals, unbooked ARR, segments and supplied relationship data. |
| Product | Sharing adoption with denominators, engineering estimates and pilot scope. |

Chief produces a request-specific task graph, not a fixed pipeline. Each executing role receives a separate, temporary Google-managed code-execution sandbox and an independent Gemini request. A retention question may use only Retention and Chief; a broad decision can use all seven. The coordinator handles network calls outside the sandboxes. The Python tools are bounded and audited, not open-ended autonomous code generation. Each sandbox receives selected synthetic inputs and no credentials.

## Persistence and scheduling

One Python/aiohttp service runs the web API, Slack Socket Mode, a durable work queue and a scheduler. SQLite WAL lives at `runs/controlroom.sqlite3` on the Compute Engine persistent disk. Conversations, tasks, source evidence, code, events, schedules, sessions and results survive service/VM restarts.

Schedule types: one-off local date/time, intervals of 1–10,080 minutes, daily local time and weekly day/time. Every schedule stores an IANA timezone. A due occurrence and its queue entry are committed together. If its previous occurrence is queued/running, a recurring occurrence is coalesced rather than overlapped. On restart, overdue schedules catch up once; missed intervals are not replayed individually. Daily times in spring-forward gaps move to the first valid local minute; fall-back uses the first occurrence.

Pause/delete cancel queued occurrences and prevent future runs; work already executing finishes. Resume calculates a fresh next deadline. Completed one-off schedules need a new schedule to run again. Interrupted tasks are marked as failures with explicit Retry controls; they are not silently claimed successful. Schedules are limited to 50 in this demo. Chief creates schedules only from explicit scheduling requests; scheduled Chief runs cannot recursively create more schedules.

The schedule loop runs on the VM, not in browser JavaScript. Keeping the VM powered on is required. Persistent disk survives a restart; this prototype has no automatic off-VM backup or multi-VM failover.

## Local development

Requires Python 3.11+, Google ADC, a billed Google project with the Agent Platform/Vertex AI API, and the dependencies below.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Set the project and optional Slack values in .env; never commit it.
python scripts/init_web_access.py
gcloud auth application-default login
python server.py --local
```

Open `http://127.0.0.1:8080`, using the key in `runs/control-room-access.txt`. Local mode disables its Slack listener so it does not compete with the cloud bot. It still runs real Google-backed jobs and its local scheduler. `python bot.py` starts the shared web/Slack/scheduler service; do not run a second listener against the deployed Slack app.

```sh
pip install pytest
python -m pytest -q
python bot.py --check-cloud
```

The legacy `python bot.py --once "Should Loopdesk build team accounts next?"` remains a console-only full-seven rehearsal. Its JSON receipts are independent of the web queue. `examples/cloud-rehearsal.json` records the original successful seven-sandbox rehearsal, not a fabricated response.

## Deployment and operations

See `infra/OPERATIONS.md`. `infra/startup.sh` pins an exact GitHub commit, installs dependencies, retrieves its environment from Secret Manager, verifies Gemini/sandbox access and starts the unified systemd service. Caddy handles public HTTPS; Python binds only to localhost. Ports 80 and 443 are the only inbound application access on the dedicated VPC.

The event project’s existing Compute service account has a pre-existing Editor role. The event user cannot grant narrower project roles; no new project-wide IAM grant was made. Secret Accessor was granted only on the app’s specific secret. An administrator should move production workloads to a dedicated least-privilege identity. No Google service-account keys or personal account passwords are deployed.

## Financial scenario assumptions

The six-week £30k build is additional contractor spending above existing payroll and net burn. £450k cash / £50k monthly net burn gives nine months of baseline runway, falling to 8.4 after the one-off cost, excluding new revenue. £18k stalled pipeline is assumed to be **annual recurring value**, not MRR or booked business. At 100% conversion and 80% margin it yields £1,200 monthly gross profit: 25-month payback after full launch; at 50%, 50 months; at zero, no finite payback. Ramp time is excluded. £15/£20/£25 prices are unvalidated experiments, not individual willingness-to-pay predictions.

## Deliberate limits

Single-operator access key, single VM and SQLite; no full account management, failover or automated backups. No arbitrary cron expressions, calendar invitations, schedule editing or cancellation of already-running sandboxes from the UI. Change a schedule by deleting it and creating a replacement. No live SaaS connectors, web research, trained pricing model, external business writes or private chain-of-thought display. Human review remains necessary for model-generated interpretations of synthetic evidence.
