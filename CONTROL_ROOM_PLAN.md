# Control room implementation contract

Started 2026-10-22 17:53 UTC. Updated deadline: live-demo-ready by 18:45 UTC (19:45 Europe/London), with 18:50 emergency buffer only. Feature freeze by 18:25, deployed by 18:35, final ten minutes for the real end-to-end rehearsal. Scope froze early at 18:16 to allow more integration time.

The latest seven-agent, interactive web request supersedes the old four-agent view-only panel PRD. One builder (Codex) owns all implementation; no teammate work is assumed.

## Architecture

Existing Compute Engine VM, Google managed code sandboxes and Gemini. One aiohttp Python service runs the web API, Slack Socket Mode adapter, durable SQLite-backed queue and polling scheduler. SQLite WAL lives in `runs/controlroom.sqlite3` on the existing persistent boot disk. Caddy supplies HTTPS and proxies to localhost; a generated high-entropy access key protects a single operator session, with HTTP-only cookies, CSRF checks and server-side secrets.

Chief generates a bounded structured task plan with a public reason for each delegation. Only requested specialists run, respecting validated dependencies, followed by Chief synthesis. Each executing agent gets a unique Google code sandbox. Direct agent runs, follow-ups and retries enter the same persisted queue from web or Slack. Model suggestions never become external business actions.

The scheduler supports one-off local date/time, minute intervals, daily and weekly runs in an IANA timezone. Each due occurrence is claimed in the same SQLite transaction that creates its queued run. Overlapping occurrences are coalesced. Restart recovery marks interrupted runs for explicit retry and leaves queued work and schedules intact. No browser timer is involved.

## UI

Plain HTML, CSS and JavaScript. Palette: paper white #ffffff, cloud #f5f7fa, ink #162536, secondary #526376, action blue #245cbd, success #17764f. System sans for body, a larger bold system display heading, monospace timestamps and sandbox identifiers. No animation, ornamental side borders, gradients or external font dependency.

Three useful surfaces: Chief conversation, seven-agent work roster with activity and details, schedules with next/last execution and controls. A persistent synthetic-data label explains the current connector boundary. Executed operations, proposed recommendations and errors use distinct text labels. At narrow widths, panes stack without horizontal scrolling.

## Acceptance

- Authenticate; reject unauthorized API calls and requests without CSRF tokens.
- Ask a retention question; route relevant specialists rather than all six.
- Observe instructions, tool execution, outputs, source IDs and distinct sandbox IDs.
- Run one agent directly; follow up on an output; retry an interrupted/failed task.
- Create and operate one-off and recurring schedules, including from Chief chat.
- Scheduled rerun executes on the VM with browser closed.
- Restart preserves conversations, history, queued jobs and schedules.
- Slack and web share the same queue and persistent state.
- Verify HTTPS, deploy the pushed GitHub revision and record honest limitations.
