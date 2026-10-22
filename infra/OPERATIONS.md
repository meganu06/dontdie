# Cloud operations

Project: `moonfire-build26lon-695`. Intended VM: `dontdie-slack` in `us-east4-a`, small `e2-medium`, dedicated service account `dontdie-bot`, dedicated VPC `dontdie-net` with no inbound firewall rules. Slack requires no public HTTP endpoint.

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

The coordinator saves local JSON run receipts under `/opt/dontdie/runs`. Sandboxes are deleted in cleanup and have a one-hour TTL as a fallback. A runtime deletion failure is recorded for manual cleanup; TTL applies to the sandbox, not its parent runtime. For the demo, one coordinator processes one decision at a time, and Slack duplicate events are tracked in memory for one hour. A restart clears that memory. This is a hackathon service, not durable production queueing.
