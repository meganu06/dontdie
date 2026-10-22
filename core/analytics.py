"""Auditable, network-free tools executed inside each agent's Google sandbox.

This module deliberately uses only the Python standard library.
"""
from collections import Counter


def analyse(agent, data, upstream=None):
    upstream = upstream or {}
    facts = []

    def fact(claim, value, unit, source_ids, account_ids=None, period="2026-Q3 (demo)"):
        facts.append(dict(claim=claim, value=value, unit=unit, period=period,
                          source_ids=source_ids, account_ids=account_ids or []))

    if agent == "pmf":
        tickets = data["support"]
        matching = [t for t in tickets if t["feature"] == "team_accounts"]
        ids = sorted({t["account_id"] for t in matching})
        agencies = [a for a in data["accounts"] if a["id"] in ids and a["segment"] == "agency" and a["staff"] >= 20]
        fact("Team-account requests", len(matching), "tickets", [t["id"] for t in matching], ids)
        fact("Unique accounts requesting teams", len(ids), "accounts", [t["id"] for t in matching], ids)
        fact("Requesting agencies with at least 20 staff", len(agencies), "accounts", [a["id"] for a in agencies], [a["id"] for a in agencies])
    elif agent == "retention":
        rows = data["cancellations"]
        teams = [r for r in rows if r["reason"] == "needs_team_accounts"]
        fact("Cancellations mentioning team features", len(teams), "of " + str(len(rows)) + " cancellations", [r["id"] for r in rows], [r["account_id"] for r in teams], "2026-09 (demo)")
        fact("Cancelled MRR mentioning team features", sum(r["mrr_gbp"] for r in teams), "GBP/month", [r["id"] for r in teams], [r["account_id"] for r in teams], "2026-09 (demo)")
    elif agent == "competitor":
        rows = data["competitors"]
        teams = [r for r in rows if r["team_accounts"]]
        fact("Competitors offering team accounts", len(teams), "of " + str(len(rows)) + " competitors", [r["id"] for r in rows])
        for row in teams:
            fact(row["name"] + " team tier", row["gbp_per_seat_month"], "GBP/seat/month", [row["id"]])
    elif agent == "gtm":
        rows = [r for r in data["deals"] if r["blocker"] == "team_accounts"]
        fact("Stalled team-feature deals", len(rows), "deals", [r["id"] for r in rows], [r["account_id"] for r in rows], "2026-09 (demo)")
        fact("Stalled pipeline annual recurring value", sum(r["arr_gbp"] for r in rows), "GBP/year unbooked", [r["id"] for r in rows], [r["account_id"] for r in rows], "2026-09 (demo)")
        fact("Stalled deal segments", dict(Counter(r["segment"] for r in rows)), "deal counts", [r["id"] for r in rows])
        fact("Documented shared-network links", len(data["relationships"]), "links", [r["id"] for r in data["relationships"]])
    elif agent == "product":
        events = data["product_usage"]
        active = {r["account_id"] for r in events if r["active"]}
        sharing = {r["account_id"] for r in events if r["active"] and r["sharing"]}
        fact("Active accounts using sharing", round(100 * len(sharing) / len(active), 1) if active else None,
             f"percent ({len(sharing)}/{len(active)} active accounts)", ["posthog-september"], sorted(sharing), "2026-09 (demo)")
        fact("Team-accounts full engineering estimate", data["engineering"]["weeks"], "weeks", ["linear-teams"])
        fact("Smallest pilot scope", data["engineering"]["pilot_scope"], "scope", ["linear-teams"])
    elif agent == "finance":
        f = data["finance"]
        cost = data["engineering"]["weeks"] * f["incremental_contractor_cost_per_week_gbp"]
        runway = f["cash_gbp"] / f["net_burn_gbp_month"]
        fact("Baseline runway", round(runway, 2), "months", ["xero-snapshot"])
        fact("Incremental contractor build cost", cost, "GBP one-off", ["linear-teams", "xero-snapshot"])
        fact("Runway after incremental build cost", round((f["cash_gbp"] - cost) / f["net_burn_gbp_month"], 2), "months excluding any new revenue", ["xero-snapshot", "linear-teams"])
        deals = [r for r in data["deals"] if r["blocker"] == "team_accounts"]
        potential_mrr = sum(r["arr_gbp"] for r in deals) / 12
        for conversion in (0, 0.5, 1.0):
            gross_profit = potential_mrr * conversion * f["gross_margin"]
            fact(f"Payback assuming {conversion:.0%} stalled pipeline converts", round(cost / gross_profit, 1) if gross_profit else None,
                 "months from full launch; steady gross profit; no ramp", ["xero-snapshot"] + [r["id"] for r in deals])
        fact("Marginal seat cost floor", f["seat_cost_gbp_month"], "GBP/seat/month before fixed overhead", ["xero-snapshot"])
        fact("Unvalidated price experiments", [15, 20, 25], "GBP/seat/month; willingness to pay unknown", ["pricing-hypothesis"])
        fact("Specialist results received", sorted(upstream), "agents", [])
    elif agent == "chief":
        k = data["kpis"]
        fact("Current registered users", k["users"], "users", ["kpi-snapshot"], period="2026-09 (demo)")
        fact("Monthly user growth", k["users"] - k["previous_users"], "users", ["kpi-snapshot"], period="2026-09 (demo)")
        fact("Monthly user growth rate", round(100 * (k["users"] - k["previous_users"]) / k["previous_users"], 2), "percent", ["kpi-snapshot"], period="2026-09 (demo)")
        fact("Current MRR", k["mrr_gbp"], "GBP/month", ["kpi-snapshot"], period="2026-09 (demo)")
        # Only demand/churn/pipeline are purchase signals; usage is not another buying vote.
        evidence_accounts = set()
        for role in ("pmf", "retention", "gtm"):
            for finding in upstream.get(role, {}).get("findings", []):
                evidence_accounts.update(finding.get("account_ids", []))
        fact("Unique accounts across demand, churn and pipeline signals", len(evidence_accounts), "accounts, deduplicated", [], sorted(evidence_accounts))
        fact("Unavailable specialist results", [r for r in ("pmf", "retention", "competitor", "finance", "gtm", "product") if upstream.get(r, {}).get("status") != "ok"], "agents", [])
    else:
        raise ValueError("Unknown agent")
    return facts
