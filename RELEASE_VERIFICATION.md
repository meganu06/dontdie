# Control room release evidence

22 October 2026, Europe/London. Live application: https://dontdie.136.70.191.164.sslip.io. Operator access is private in the builder's ignored `runs/control-room-access.txt`; do not include it in a recording or repository.

Deployed application revision: `8e679a2`. At 19:43 London time, the restarted release returned HTTPS 200, served the navigation race fix, and preserved both scheduled results. The prior restart also verified global live-work fields and Slack reconnection. Later documentation-only commits do not change the deployed application.

## Demonstrated on Google Cloud

| Path | Observed result |
|---|---|
| Protected access | Public HTTPS certificate verified; unauthenticated API returned 401; authenticated mutation without CSRF returned 403. |
| Adaptive Chief delegation | Run `4b6a9d3048584257` selected PMF and Retention, then dependent Product, then Chief synthesis. Four distinct Google sandbox IDs, completed results and no cleanup errors. Other specialists stayed idle. |
| Specialist follow-up | Run `9c69001e5a0345d6` completed a Retention follow-up using previous results. |
| Chief creates a schedule | Chat run `8aa9fd6358eb48f3` created Finance schedule `5a523a489c4c4ad5`, using Europe/London and an explicit next-run time. |
| Browser-independent one-off execution | The browser test page was on `about:blank` and the local worker was stopped when the VM dispatched Finance run `2be5822028ef4941`. It completed with real sandbox execution and a saved result. |
| Browser-independent recurring execution | Interval schedule `626b13e73f6c47f5` dispatched Competitor run `3f009d9451724868`, which completed. It is now paused to prevent further test runs. |
| Recurring controls | A daily Retention schedule was created through the web form, paused, resumed, paused again and deleted. |
| VM restart persistence | Completed runs, 10 conversation messages, session authentication and both then-existing schedules survived a real stop/start of the Compute Engine VM. |
| Responsive UI | All seven roles rendered at 1440px and 390px widths without horizontal page overflow. |
| Slack connection | The unified service logged `DONTDIE_SLACK_CONNECTED` after deployment and restart. A human mention-and-response rehearsal has not yet been observed for this expanded release. |

Fifteen automated tests pass, covering calculation evidence, task selection, dependency validation, failure visibility, retries, follow-ups, authentication, CSRF, scheduling, daylight-saving handling, persistent queue claims, restart recovery and visibility across conversations. Failure/retry checks deliberately simulate a cloud failure in tests; the demo does not fabricate a production failure.

Local execution receipts and screenshots are in ignored `runs/production-*.json` and `runs/production-*.png`. These are evidence of actual test execution, separate from the deliberately synthetic business inputs.

## Three-minute demonstration

1. Sign in and open the saved team-feature conversation. Show Chief's delegation, PMF/Retention findings, dependent Product task and final recommendation.
2. Inspect a completed task. Expand sources, assumptions, sandbox ID and actual calculation code. Point out the **proposed** labels on business recommendations.
3. Open Schedules. Show the completed Finance one-off and paused recurring Competitor check, including last results. Explain that both were dispatched by the VM with the browser closed.
4. For a fresh live run, ask: **Assess cancellation reasons and cancelled revenue; focus only on retention evidence.** Allow tens of seconds to a few minutes for Google execution. Alternatively, use an agent's Run or Request follow-up control.
5. For a new schedule, ask: **Schedule Finance to review runway in two minutes.** Show its next run, timezone and controls, then return to its result after the deadline and queue processing.

## Honest boundaries

Business data is fictional Loopdesk fixtures. There are no live SaaS connectors, competitor browsing, trained willingness-to-pay model or external business writes. Analysis, scheduling and Slack replies are implemented; suggested outreach, pricing changes and product changes remain proposals.

Each executing role has its own temporary Google code sandbox; model requests and orchestration run outside those sandboxes. The tools execute bounded, audited calculations, not arbitrary generated programs.

Single operator key, single VM, SQLite persistent disk. No account-management system, failover or automatic off-VM backup. The VM must remain running. Work queues behind other objectives; independent specialists within a plan can run concurrently. Schedule editing is delete-and-recreate; pause/delete stop future or queued work, not a running calculation.

The earlier four-agent panel under the separate `dont-die` directory is not deployed. Its earlier design-hook findings were left outside this release; no suppressions were added. The current seven-agent interface has a stronger heading hierarchy and no thick side-card accent border.
