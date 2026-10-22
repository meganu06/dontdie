# Cloud operations

Project: `moonfire-build26lon-695`. VM: `dontdie-slack` in `us-east4-a`, small `e2-medium`, dedicated VPC `dontdie-net`. Reserved external address `dontdie-web-ip`: `136.70.191.164`. The `dontdie-web-https` rule allows only TCP 80/443 to instances tagged `dontdie-web`; no public SSH or Python port is exposed.

Control room: https://dontdie.136.70.191.164.sslip.io. Caddy terminates HTTPS and proxies to `127.0.0.1:8080`. The unified `dontdie.service` runs `server.py`: web API, Slack Socket Mode, persistent queue and scheduler. Its preflight checks Gemini and a real temporary sandbox before starting.

Private operator access is in the builder’s ignored `runs/control-room-access.txt`. The server stores only its SHA-256 hash in the Secret Manager environment (the random key has 192 bits of entropy). Sessions are HTTP-only, Secure, SameSite=Strict and expire after 24 hours; mutation endpoints require both CSRF token and expected Origin. Do not publish the access file.

The event project pre-authorizes `715043009535-compute@developer.gserviceaccount.com` with Editor, and permits our event user to attach it. The demo uses that existing identity plus Secret Accessor on only `dontdie-slack-env`. No new project-wide IAM grant was made. A new `dontdie-bot` account was created during setup but is unused because the event user cannot grant project roles; an administrator can later grant it the narrower Agent Platform User role and secret access, then switch the VM identity.

Read boot and service console output:

```sh
gcloud compute instances get-serial-port-output dontdie-slack --zone=us-east4-a --project=moonfire-build26lon-695
```

Stop the bot after the hackathon (also stops new model/sandbox runs):

```sh
gcloud compute instances stop dontdie-slack --zone=us-east4-a --project=moonfire-build26lon-695
```

Restart:

```sh
gcloud compute instances start dontdie-slack --zone=us-east4-a --project=moonfire-build26lon-695
```

The startup script uses the exact commit in instance metadata `dontdie-revision`; update that value deliberately before rebooting for a new release. The environment comes from the Secret Manager secret named by `dontdie-secret`. Replace exposed Slack credentials with new secret versions; never paste them into issues, commits, logs or metadata. Restart after replacement. VM credentials come from its attached service account.

The coordinator stores conversations, messages, runs, tasks, source evidence, code, events, sessions, schedules and Slack event IDs in `/opt/dontdie/runs/controlroom.sqlite3` (SQLite WAL). This directory is retained on the persistent boot disk across stop/start and deployments; do not delete the VM/disk to restart the app. The database is not automatically backed up off-VM. Legacy console receipts remain as JSON under the same directory.

The queue processes objectives one at a time; independent specialists in one plan execute concurrently. Due scheduled occurrences are claimed transactionally in the database, not triggered by a browser. Restart recovery marks interrupted runs for explicit retry and preserves queued jobs/schedules. A schedule overdue after downtime catches up once. Pause/delete cancel queued occurrences; already-running work finishes. A single-instance file lock prevents competing workers in the same checkout.

Sandboxes are deleted in cleanup and have a one-hour TTL as a fallback. A runtime deletion failure is recorded for manual cleanup; TTL applies to the sandbox, not its parent runtime. Review ERROR activity when cleanup fails. Stopping the VM stops scheduling until it resumes.

Deployment metadata: `dontdie-revision` is the exact GitHub commit, `dontdie-secret` names the environment secret, and `dontdie-web-host` names the HTTPS host. Update the pinned commit and `startup-script` together, add a new secret version if configuration changed, then stop/start. The script leaves the database intact. Wait for `DONTDIE_WEB_READY`, `DONTDIE_SLACK_CONNECTED`, and a successful HTTPS `/healthz` response before declaring readiness. `DONTDIE_RUN_COMPLETE` log entries identify completed cloud runs.
