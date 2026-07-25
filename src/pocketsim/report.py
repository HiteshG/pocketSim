"""Reports: markdown for the terminal, HTML for sharing, verdict.json for machines.

Reporting is deliberately a separate command from simulating. Simulating is slow and
costs money; reporting is instant and free. You simulate a script once and re-report it
many times as metrics get added or the slicing changes — merged into one command, every
tweak to a table would cost another full run.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Template

from .metrics import Comparison, RunMetrics
from .personas import AuditReport
from .schema import Population

SPARK = "▁▂▃▄▅▆▇█"

FLAG_MEANING = {
    "OVER_RESOLVED": "Closed its own loop — listeners left satisfied. End on the open question instead.",
    "BORING": "Nothing pulled at any point. Needs stakes, not restructuring.",
    "WORKING_HOOK": "High need-to-know and genuine disagreement about what's next. This is what a cliffhanger looks like.",
    "PREDICTABLE_BUT_WANTED": "They know what's coming and want it anyway. Fragile — one subversion from a drop.",
    "HIGH_DROP": "Drop rate well above this script's own median.",
}

DISCLAIMER = (
    "Personas are synthesised from hand-authored archetypes, not fitted from listening "
    "logs, and no backtest has been run. Every number here is **relative** — valid for "
    "ranking episodes within this script and for measuring a rewrite against its own "
    "baseline. None of it is a prediction of real retention."
)


def sparkline(values: list[float]) -> str:
    if not values:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    return "".join(SPARK[min(int((v - lo) / span * (len(SPARK) - 1)), len(SPARK) - 1)] for v in values)


def verdict(m: RunMetrics) -> dict[str, Any]:
    """Machine-readable summary — the thing a pipeline or dashboard consumes."""
    worst = m.fix_list[0] if m.fix_list else {}
    return {
        "run_id": m.run_id,
        "series": m.series,
        "market": m.market,
        "population_size": m.population_size,
        "generated_at": datetime.now(UTC).isoformat(),
        "provisional": m.provisional,
        "claim_scope": "relative-only",
        "headline": {
            "worst_episode": worst.get("episode_no"),
            "worst_episode_score": worst.get("score"),
            "worst_episode_flags": worst.get("flags", []),
            "recommended_paywall_episode": m.paywall.get("recommended_gate"),
            "hook_score": m.hook.get("score"),
            "final_active_share": round(m.final_retention, 4),
        },
        "fix_list": m.fix_list,
        "paywall": m.paywall,
        "hook": m.hook,
        "cohorts": [c.model_dump() for c in m.cohorts],
        "regions": [r.model_dump() for r in m.regions],
        "cohort_fit": m.cohort_fit,
        "filler_beats": m.filler_beats,
        "episodes_planned": m.planned_episodes,
        "episodes_simulated": len(m.episodes),
        "episodes": [e.model_dump() for e in m.episodes],
        "switch_to": m.switch_to,
        "trope_fatigue": m.trope_fatigue,
    }


# Field names that would assert a calibrated real-world prediction. Nothing in this
# pipeline has earned one: the personas are hand-authored and no backtest exists, so a
# key like `predicted_retention` would be a claim the numbers cannot support no matter
# how the surrounding prose is worded.
BANNED_FIELD_PATTERNS = (
    "predicted_",
    "forecast",
    "expected_retention",
    "retention_pct",
    "actual_",
    "true_",
)


def levels_lint(payload: dict[str, Any]) -> list[str]:
    """Check the machine-readable output makes no absolute predictive claim.

    Scope, stated plainly so nobody mistakes this for more than it is: this lints FIELD
    NAMES in verdict.json, not prose and not values. Panel-relative shares
    (`final_active_share`, `drop_rate`) are legitimate and stay — they describe what this
    simulated panel did, which is a fact about the run. What is banned is a name that
    reads as a forecast of real listeners.
    """
    warnings: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                low = k.lower()
                for pattern in BANNED_FIELD_PATTERNS:
                    if pattern in low:
                        warnings.append(
                            f"{path}.{k}: field name asserts a calibrated prediction "
                            f"('{pattern}'); this run cannot support one"
                        )
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node[:50]):
                walk(v, f"{path}[{i}]")

    walk(payload, "verdict")
    if payload.get("claim_scope") != "relative-only":
        warnings.append("verdict.claim_scope must be 'relative-only' while personas are provisional")
    return warnings


def render_learning_markdown(
    m: RunMetrics,
    *,
    meta: dict[str, Any] | None = None,
    population: Population | None = None,
    audit: AuditReport | None = None,
) -> str:
    """Run-level audit trail for improving the harness after each smoke test."""
    usage = {}
    if meta and meta.get("usage_json"):
        try:
            usage = json.loads(meta["usage_json"])
        except json.JSONDecodeError:
            usage = {}

    planned = m.planned_episodes
    simulated = len(m.episodes)
    stopped_early = simulated < planned
    final_active = m.final_retention
    top_fix = m.fix_list[0] if m.fix_list else {}
    top_cohort = max(m.cohorts, key=lambda c: c.survived_to_end, default=None)
    any_drops = any(e.drop_rate > 0 for e in m.episodes)
    max_revenue_at_risk = max((e.revenue_at_risk for e in m.episodes), default=0.0)

    lines = [
        f"# Run Learning Report — {m.run_id}",
        "",
        "## What Ran",
        "",
        f"- Series: `{m.series}`",
        f"- Market: `{m.market}`",
        f"- Provider: `{(meta or {}).get('provider', 'unknown')}`",
        f"- Model: `{(meta or {}).get('model', 'unknown')}`",
        f"- Episodes: `{simulated}` simulated of `{planned}` planned",
        f"- Population: `{m.population_size}` listeners",
        f"- Population fingerprint: `{(meta or {}).get('population_fingerprint', 'unknown')}`",
        f"- LLM calls: `{usage.get('calls', 'unknown')}`",
        f"- Schema failures: `{usage.get('schema_failures', 0)}`",
        f"- Invalid drop-beat ids: `{usage.get('invalid_drop_beats', 0)}`",
        f"- Missing switch-away labels on drops: `{usage.get('missing_switch_to', 0)}`",
    ]
    if usage.get("wall_seconds") is not None:
        lines.append(f"- Simulation wall time: `{usage['wall_seconds']:.1f}s`")
    lines += ["", "## Persona Generation", ""]

    if population:
        lines += [
            f"- Source market: `{population.market}`",
            f"- Seed: `{population.seed}`",
            f"- Generator provider: `{population.generator_provider or 'unknown'}`",
            f"- Generator model: `{population.generator_model}`",
            "- Method: sampled numeric skeletons from declared market distributions, then generated only prose around those fixed values.",
            "- Reuse rule: this exact population fingerprint must be shared across baseline and rewrite runs.",
            "",
            "| Cohort | Personas | Share |",
            "|---|---:|---:|",
        ]
        grouped = population.by_cohort()
        for cohort_id, people in sorted(grouped.items()):
            lines.append(f"| {cohort_id} | {len(people)} | {len(people) / population.count:.1%} |")
    else:
        lines.append("- Population snapshot was unavailable, so generation details could not be reconstructed.")

    lines += [
        "",
        "## Persona Validation",
        "",
    ]
    if audit:
        lines += [
            f"- Automated audit: **{'PASS' if audit.ok else 'FAIL'}**",
            "- Human validity gate: inspect sample personas and confirm the content team recognises them as plausible listeners.",
            "",
            "| Check | Result | Detail |",
            "|---|---|---|",
        ]
        for check in audit.checks:
            result = "PASS" if check.passed else "FAIL"
            lines.append(f"| {check.name} | {result} | {check.detail} |")
    else:
        lines.append("- Automated audit was unavailable.")

    lines += [
        "",
        "## Outcomes",
        "",
        f"- Final active share after the last simulated episode: `{final_active:.1%}`",
        f"- Worst episode by revenue at risk: `{top_fix.get('episode_no', 'n/a')}`",
        f"- Worst episode score: `{top_fix.get('score', 'n/a')}`",
        f"- Recommended paywall episode: `{m.paywall.get('recommended_gate', 'n/a')}`",
        f"- Hook score: `{m.hook.get('score', 'n/a')}`",
    ]
    if top_cohort and top_cohort.survived_to_end > 0:
        lines.append(
            f"- Strongest cohort in this run: `{top_cohort.cohort_id}` "
            f"({top_cohort.survived_to_end:.1%} survived to smoke end)"
        )
    elif top_cohort:
        lines.append("- Strongest cohort in this run: none survived to the smoke end.")
    if m.switch_to:
        label, count = m.switch_to[0]
        lines.append(f"- Top switch-away destination: `{label}` ({count} listeners)")

    lines += [
        "",
        "## Harness Learnings",
        "",
    ]
    if stopped_early:
        lines.append(
            f"- Simulation stopped before planned depth because all listeners dropped by episode {m.episodes[-1].episode_no}."
        )
    if usage.get("schema_failures", 0):
        lines.append(
            f"- Provider produced `{usage['schema_failures']}` schema failures; downstream metrics exclude those rows."
        )
    if usage.get("invalid_drop_beats", 0):
        lines.append(
            f"- Provider produced `{usage['invalid_drop_beats']}` invalid drop-beat ids; they were nulled before metrics."
        )
    if usage.get("missing_switch_to", 0):
        lines.append(
            f"- Provider omitted `switch_to` on `{usage['missing_switch_to']}` drop decisions; drop-reason prompting needs tightening."
        )
    if population and population.count < 25:
        lines.append(
            "- Population is a small smoke panel; use it for harness validation, not cohort-level conclusions."
        )
    if audit and not audit.ok:
        lines.append("- Persona audit failed; treat the run as a harness/debug artifact, not a decision artifact.")
    if max_revenue_at_risk == 0:
        lines.append("- No drops occurred by the simulated depth; Fix List ordering is not meaningful yet.")
    if any_drops and not m.switch_to:
        lines.append("- No switch-away labels were captured; check whether drop prompts or provider outputs are too uniform.")
    if not any(
        [
            stopped_early,
            usage.get("schema_failures", 0),
            usage.get("invalid_drop_beats", 0),
            usage.get("missing_switch_to", 0),
            population and population.count < 25,
            audit and not audit.ok,
            max_revenue_at_risk == 0,
            any_drops and not m.switch_to,
        ]
    ):
        lines.append("- No automatic harness warnings were detected in this run.")

    lines += [
        "",
        "## Claim Boundary",
        "",
        DISCLAIMER,
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Markdown
# ─────────────────────────────────────────────────────────────────────────────


def render_markdown(m: RunMetrics) -> str:
    L: list[str] = []
    a = L.append

    a(f"# {m.series} — simulated audience report")
    a("")
    ep_label = (
        f"{len(m.episodes)} of {m.planned_episodes} episodes"
        if len(m.episodes) != m.planned_episodes
        else f"{len(m.episodes)} episodes"
    )
    a(f"`{m.run_id}` · market **{m.market}** · {m.population_size} synthetic listeners · "
      f"{ep_label}")
    a("")
    a(f"> ⚠️ **Relative claims only.** {DISCLAIMER}")
    a("")

    a("## The Fix List")
    a("")
    a("Episodes ranked by **revenue at risk** — drop rate weighted by how many listeners are "
      "still present and how much series is left to monetise. This is the answer to "
      "*where do I spend limited rewrite time*, which raw drop rate cannot give you: the "
      "same weakness costs far more at episode 4 than at episode 18.")
    a("")
    a("| Rank | Episode | Score | Drop | Still listening | Eps left | Flags | Worst beat |")
    a("|---:|---:|---:|---:|---:|---:|---|---|")
    for i, f in enumerate(m.fix_list[:10], 1):
        flags = ", ".join(f["flags"]) or "—"
        a(f"| {i} | **{f['episode_no']}** | {f['score']:.0f} | {f['drop_rate']:.1%} | "
          f"{f['active_share']:.0%} | {f['episodes_remaining']} | {flags} | "
          f"`{f['top_drop_beat'] or '—'}` |")
    a("")

    seen = {fl for f in m.fix_list for fl in f["flags"]}
    if seen:
        a("**What the flags mean**")
        a("")
        for fl in sorted(seen):
            a(f"- `{fl}` — {FLAG_MEANING.get(fl, '')}")
        a("")

    a("## Retention")
    a("")
    a(f"`{sparkline([e.active_after_share for e in m.episodes])}`  "
      f"ep1 → ep{m.episodes[-1].episode_no if m.episodes else 0}, "
      f"ending at {m.final_retention:.0%} still active")
    a("")
    a("| Ep | Heard | Active after | Continue | Drop | Pay | Craving mid → end | Δ | Entropy | Flags |")
    a("|---:|---:|---:|---:|---:|---:|:--|---:|---:|---|")
    for e in m.episodes:
        a(f"| {e.episode_no} | {e.active_share:.0%} | {e.active_after_share:.0%} | "
          f"{e.continue_rate:.1%} | {e.drop_rate:.1%} | "
          f"{e.pay_rate:.1%} | {e.craving_mid:.1f} → {e.craving_end:.1f} | {e.craving_delta:+.1f} | "
          f"{e.prediction_entropy:.2f} | {', '.join(e.flags) or '—'} |")
    a("")

    a("## Paywall placement")
    a("")
    gate = m.paywall.get("recommended_gate")
    a(f"Recommended gate: **episode {gate}**.")
    a("")
    a("Conversion happens once, at the gate: whoever is still listening at that episode "
      "either converts or leaves, and the converts then monetise every remaining episode. "
      "Gate early and you reach more listeners but fewer are hooked enough to pay; gate "
      "late and conversion is higher but there is less series left to sell. "
      "Directional only until calibrated against real coin-spend data.")
    a("")
    a("| Gate at episode | Conversion at gate | Reach after gate | Expected coin-episodes |")
    a("|---:|---:|---:|---:|")
    for row in m.paywall.get("curve", []):
        mark = " ←" if row["gate_episode"] == gate else ""
        a(f"| {row['gate_episode']}{mark} | {row.get('conversion_at_gate', 0):.1%} | "
          f"{row.get('reach_after_gate', 0):.2f} | {row['expected_coin_episodes']:.3f} |")
    a("")

    a("## Hook (episode 1)")
    a("")
    if m.hook:
        a(f"- Continue rate: **{m.hook['continue_rate']:.1%}**")
        a(f"- Need-to-know at the end: **{m.hook['craving_end']:.1f}/10**")
        a(f"- Prediction disagreement: **{m.hook['prediction_entropy']:.2f}** "
          f"({'genuine disagreement about what happens next — a real hook' if m.hook['prediction_entropy'] >= 0.6 else 'listeners broadly agree what is coming, so the pull is weaker than the craving score suggests'})")
        a(f"- Hook score: **{m.hook['score']:.0f}/100**")
        a("")
        a("This is the highest-frequency, cheapest thing to test — twenty opening variants "
          "against the same population is a fraction of a full run, and the winner doubles "
          "as ad creative.")
    a("")

    if m.cohort_fit:
        a("## Who this story is for")
        a("")
        a("Need regions ranked for this script — what listeners wanted, not when they "
          "listened. Published as a **ranking**, not a score: if the panel is uniformly "
          "miscalibrated the absolute shares all move together and the ordering mostly "
          "does not, so the ordering is the part worth acting on. It is a pre-launch "
          "targeting map — which appetite to buy against, and which one this script will "
          "not hold no matter how well it is marketed.")
        a("")
        a("| # | Region | Listeners | Reads as | Evidence |")
        a("|---:|---|---:|---|---|")
        for f in m.cohort_fit:
            a(f"| {f['rank']} | **{f['label']}** | {f['listeners']} | {f['reason']} | "
              f"`{f['evidence']}` |")
        a("")

        risky = [f for f in m.cohort_fit if f["risks"]]
        if risky:
            a("**Dealbreakers this script actually trips**, and who they threaten. A "
              "dealbreaker is only listed against a region it is live for — the same beat "
              "that loses one region can be the reason another one stays.")
            a("")
            for f in risky:
                for r in f["risks"]:
                    beats = ", ".join(f"`{b}`" for b in r["beat_ids"])
                    a(f"- **{f['label']}** — `{r['dealbreaker_id']}` at {beats}: {r['text']}")
            a("")

        a(f"Evidence tiers are inherited from the shared ontology: `T-A` public evidence, "
          f"`T-B` industry prior, `T-C` this team's hypothesis. A region ranked highly on "
          f"`T-C` evidence is a hypothesis this run did not test — it says the script suits "
          f"that appetite, not that the appetite is there in the market.")
        a("")

    if m.regions:
        a("### Need regions in detail")
        a("")
        a("| Region | Listeners | Survived to end | Pay rate | Craving (end) | Median drop ep | Abandons at |")
        a("|---|---:|---:|---:|---:|---:|---|")
        for r in sorted(m.regions, key=lambda r: -r.survived_to_end):
            med = r.median_drop_episode if r.median_drop_episode is not None else "—"
            beat = f"`{r.abandon_beat}`" if r.abandon_beat else "—"
            a(f"| {r.label} | {r.listeners} | {r.survived_to_end:.0%} | {r.mean_pay_rate:.1%} | "
              f"{r.mean_craving_end:.1f} | {med} | {beat} |")
        a("")

    if m.filler_beats:
        a("### Filler")
        a("")
        a("Beats that move nothing and could be cut, ordered by the drop rate of the "
          "episode they sit in. A filler beat in an episode nobody leaves is a tidiness "
          "note; the same beat in a high-drop episode is a candidate for the drop itself.")
        a("")
        a("| Ep | Beat | Title | Risk | Drop rate at that episode |")
        a("|---:|---|---|---|---:|")
        for b in m.filler_beats[:12]:
            dr = f"{b['drop_rate_at_episode']:.0%}" if b["drop_rate_at_episode"] is not None else "—"
            a(f"| {b['episode_no']} | `{b['beat_id']}` | {b['title'][:40]} | {b['churn_risk']} | {dr} |")
        a("")

    a("## Listening occasion")
    a("")
    a("The other axis: *when* people listen rather than what they want. A cohort that "
      "survives well is a targeting instruction for UA spend; a cohort that drops where "
      "others do not is usually a session-length problem, not a writing one.")
    a("")
    a("| Cohort | Listeners | Survived to end | Pay rate | Craving (end) | Median drop ep |")
    a("|---|---:|---:|---:|---:|---:|")
    for c in sorted(m.cohorts, key=lambda c: -c.survived_to_end):
        med = c.median_drop_episode if c.median_drop_episode is not None else "—"
        a(f"| {c.cohort_id} | {c.listeners} | {c.survived_to_end:.0%} | {c.mean_pay_rate:.1%} | "
          f"{c.mean_craving_end:.1f} | {med} |")
    a("")

    if m.trope_fatigue:
        a("## Trope fatigue")
        a("")
        a("Episodes where long-tenure listeners drop materially harder than new ones. "
          "That gap is a *cliché* signal, not a weak-writing signal — the beat works fine "
          "for someone hearing it for the first time. Different diagnosis, different fix.")
        a("")
        a("| Ep | Veteran drop | New-user drop | Gap |")
        a("|---:|---:|---:|---:|")
        for t in m.trope_fatigue:
            a(f"| {t['episode_no']} | {t['veteran_drop_rate']:.1%} | "
              f"{t['new_user_drop_rate']:.1%} | +{t['gap']:.1%} |")
        a("")

    if m.switch_to:
        a("## What they switch to")
        a("")
        a("Aggregated from listeners who chose to leave. This is a map of what you are "
          "actually losing attention to, which no satisfaction rating produces.")
        a("")
        for label, count in m.switch_to:
            a(f"- {label} — {count}")
        a("")

    a("---")
    a("")
    a(f"_Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} by pocketsim._")
    return "\n".join(L)


def render_comparison_markdown(c: Comparison) -> str:
    L: list[str] = []
    a = L.append
    a("# Rewrite comparison")
    a("")
    a(f"`{c.base_run}` → `{c.against_run}`")
    a("")
    if not c.same_population:
        a("> 🛑 **INVALID COMPARISON.** " + c.summary)
    elif c.is_null_test:
        a(f"> 🔬 **{c.summary}**")
    else:
        a(f"**{c.summary}**")
        a("")
        a("Both runs used the same synthetic listeners, so persona-level bias cancels in "
          "the difference. This is the counterfactual you cannot get from real listeners, "
          "because a story ships once.")
    a("")
    a(f"Largest per-episode swing: {c.observed_noise:.1%}")
    a("")
    a(f"Final active share: {c.base_final_retention:.1%} → {c.new_final_retention:.1%} "
      f"({c.retention_delta:+.1%})")
    a("")
    a("| Ep | Drop (base) | Drop (new) | Δ | Craving end Δ | Verdict |")
    a("|---:|---:|---:|---:|---:|---|")
    for e in c.episodes:
        a(f"| {e.episode_no} | {e.base_drop_rate:.1%} | {e.new_drop_rate:.1%} | "
          f"{e.drop_delta:+.1%} | {e.craving_delta:+.1f} | {e.verdict} |")
    return "\n".join(L)


# ─────────────────────────────────────────────────────────────────────────────
# HTML
# ─────────────────────────────────────────────────────────────────────────────

HTML_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ m.series }} — simulated audience report</title>
<style>
:root{--bg:#fbfaf8;--panel:#fff;--ink:#1b1d21;--ink2:#4a4f57;--ink3:#767c86;
--line:#e4e2dd;--line2:#efedE8;--accent:#3d5a80;--accent-soft:#eef2f7;
--warn:#8a5a2b;--warn-soft:#fbf3e8;--good:#2f6b4f;--good-soft:#eef5f1;--r:10px}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-size:16px;line-height:1.65;
font-family:ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
-webkit-font-smoothing:antialiased}
main{max-width:960px;margin:0 auto;padding:0 28px 100px}
header{padding:52px 0 28px;border-bottom:1px solid var(--line);margin-bottom:12px}
.eyebrow{font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--accent);
font-weight:650;margin-bottom:12px}
h1{font-size:34px;line-height:1.15;letter-spacing:-.02em;margin:0 0 16px;font-weight:660}
.meta{display:flex;flex-wrap:wrap;gap:8px}
.chip{font-size:12px;padding:4px 11px;border-radius:100px;background:var(--panel);
border:1px solid var(--line);color:var(--ink2)}
.chip b{color:var(--ink);font-weight:600}
h2{font-size:13px;letter-spacing:.13em;text-transform:uppercase;color:var(--accent);
font-weight:650;margin:48px 0 6px}
h3{font-size:23px;line-height:1.25;letter-spacing:-.012em;margin:0 0 16px;font-weight:640}
p{margin:0 0 14px;max-width:72ch;color:var(--ink2)}
.note{border:1px solid var(--line);background:var(--panel);border-radius:var(--r);
padding:15px 18px;margin:0 0 20px;max-width:72ch}
.note.warn{border-color:#e8d9c2;background:var(--warn-soft)}
.note .tag{font-size:10.5px;letter-spacing:.13em;text-transform:uppercase;font-weight:650;
display:block;margin-bottom:6px;color:var(--warn)}
.note p{margin:0;color:#5c4630}
table{border-collapse:collapse;width:100%;font-size:14px;background:var(--panel);
border:1px solid var(--line);border-radius:var(--r);overflow:hidden;margin:0 0 22px}
th{text-align:left;font-size:11px;letter-spacing:.08em;text-transform:uppercase;
color:var(--ink3);font-weight:620;padding:10px 13px;background:#f7f6f3;
border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:10px 13px;border-bottom:1px solid var(--line2);color:var(--ink2);vertical-align:top}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover td{background:#fcfbf9}
.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.rank1 td{background:var(--accent-soft)!important}
.rank1 td:first-child{color:var(--accent);font-weight:660}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.87em;
background:#f5f4f1;padding:2px 5px;border-radius:4px}
.spark{font-family:ui-monospace,Menlo,monospace;font-size:20px;letter-spacing:2px;
color:var(--accent)}
.flag{display:inline-block;font-size:10.5px;letter-spacing:.06em;padding:2px 7px;
border-radius:100px;background:#f0eeea;color:var(--ink3);margin-right:4px;white-space:nowrap}
.flag.bad{background:var(--warn-soft);color:var(--warn)}
.flag.good{background:var(--good-soft);color:var(--good)}
dl{margin:0 0 20px;max-width:72ch}dt{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;
color:var(--ink);margin-top:10px}dd{margin:2px 0 0;color:var(--ink2);font-size:14px}
footer{margin-top:56px;padding-top:22px;border-top:1px solid var(--line);
font-size:13px;color:var(--ink3)}
</style></head><body><main>

<header>
  <div class="eyebrow">PocketSim · simulated audience report</div>
  <h1>{{ m.series }}</h1>
  <div class="meta">
    <span class="chip"><b>Market</b> {{ m.market }}</span>
    <span class="chip"><b>Listeners</b> {{ m.population_size }}</span>
    <span class="chip"><b>Episodes</b> {{ m.episodes|length }}{% if m.episodes|length != m.planned_episodes %}/{{ m.planned_episodes }}{% endif %}</span>
    <span class="chip"><b>Run</b> {{ m.run_id }}</span>
    <span class="chip"><b>Ends at</b> {{ '%.0f'|format(m.final_retention*100) }}% active</span>
  </div>
</header>

<div class="note warn">
  <span class="tag">Relative claims only</span>
  <p>Personas are synthesised from hand-authored archetypes, not fitted from listening logs,
  and no backtest has been run. Every number here is valid for <b>ranking episodes within this
  script</b> and for <b>measuring a rewrite against its own baseline</b>. None of it is a
  prediction of real retention.</p>
</div>

<h2>01 · The Fix List</h2>
<h3>Where to spend rewrite time</h3>
<p>Episodes ranked by <b>revenue at risk</b> — drop rate weighted by how many listeners are still
present and how much series is left to monetise. Raw drop rate cannot separate a weak episode at 4,
before the paywall with everyone still listening, from the identical weakness at 18.</p>
<table><thead><tr><th>#</th><th>Episode</th><th class="n">Score</th><th class="n">Drop</th>
<th class="n">Listening</th><th class="n">Eps left</th><th>Flags</th><th>Worst beat</th></tr></thead>
<tbody>
{% for f in m.fix_list[:10] %}
<tr {% if loop.index == 1 %}class="rank1"{% endif %}>
<td>{{ loop.index }}</td><td><b>Episode {{ f.episode_no }}</b></td>
<td class="n">{{ '%.0f'|format(f.score) }}</td>
<td class="n">{{ '%.1f'|format(f.drop_rate*100) }}%</td>
<td class="n">{{ '%.0f'|format(f.active_share*100) }}%</td>
<td class="n">{{ f.episodes_remaining }}</td>
<td>{% for fl in f.flags %}<span class="flag {{ 'good' if fl=='WORKING_HOOK' else 'bad' }}">{{ fl }}</span>{% else %}—{% endfor %}</td>
<td><code>{{ f.top_drop_beat or '—' }}</code></td></tr>
{% endfor %}
</tbody></table>

{% if flag_meanings %}
<dl>{% for k, v in flag_meanings %}<dt>{{ k }}</dt><dd>{{ v }}</dd>{% endfor %}</dl>
{% endif %}

<h2>02 · Retention</h2>
<h3>Episode by episode</h3>
<p class="spark">{{ spark }}</p>
<table><thead><tr><th class="n">Ep</th><th class="n">Heard</th><th class="n">Active after</th><th class="n">Continue</th>
<th class="n">Drop</th><th class="n">Pay</th><th>Craving mid → end</th><th class="n">Δ</th>
<th class="n">Entropy</th><th>Flags</th></tr></thead><tbody>
{% for e in m.episodes %}
<tr><td class="n">{{ e.episode_no }}</td>
<td class="n">{{ '%.0f'|format(e.active_share*100) }}%</td>
<td class="n">{{ '%.0f'|format(e.active_after_share*100) }}%</td>
<td class="n">{{ '%.1f'|format(e.continue_rate*100) }}%</td>
<td class="n">{{ '%.1f'|format(e.drop_rate*100) }}%</td>
<td class="n">{{ '%.1f'|format(e.pay_rate*100) }}%</td>
<td>{{ '%.1f'|format(e.craving_mid) }} → {{ '%.1f'|format(e.craving_end) }}</td>
<td class="n">{{ '%+.1f'|format(e.craving_delta) }}</td>
<td class="n">{{ '%.2f'|format(e.prediction_entropy) }}</td>
<td>{% for fl in e.flags %}<span class="flag {{ 'good' if fl=='WORKING_HOOK' else 'bad' }}">{{ fl }}</span>{% else %}—{% endfor %}</td></tr>
{% endfor %}
</tbody></table>

<h2>03 · Paywall</h2>
<h3>Recommended gate: episode {{ m.paywall.recommended_gate }}</h3>
<p>Conversion happens once, at the gate: whoever is still listening either converts or leaves, and
the converts then monetise every remaining episode. Gate early and you reach more listeners but
fewer are hooked enough to pay; gate late and conversion is higher but there is less series left
to sell. Directional until calibrated against real coin spend.</p>
<table><thead><tr><th class="n">Gate at</th><th class="n">Conversion at gate</th>
<th class="n">Reach after gate</th><th class="n">Expected coin-episodes</th></tr></thead><tbody>
{% for row in m.paywall.curve %}
<tr {% if row.gate_episode == m.paywall.recommended_gate %}class="rank1"{% endif %}>
<td class="n">Episode {{ row.gate_episode }}</td>
<td class="n">{{ '%.1f'|format(row.conversion_at_gate*100) }}%</td>
<td class="n">{{ '%.2f'|format(row.reach_after_gate) }}</td>
<td class="n">{{ '%.3f'|format(row.expected_coin_episodes) }}</td></tr>
{% endfor %}
</tbody></table>

{% if m.cohort_fit %}
<h2>04 · Who this story is for</h2>
<h3>Need regions, ranked</h3>
<p>What listeners wanted, not when they listened. Published as a <b>ranking</b>: if the panel is
uniformly miscalibrated the shares all move together and the ordering mostly does not, so the
ordering is the part worth acting on. This is the pre-launch targeting map — mistargeted CAC is
the most expensive waste in this business.</p>
<table><thead><tr><th class="n">#</th><th>Region</th><th class="n">Listeners</th><th>Reads as</th>
<th>Evidence</th></tr></thead><tbody>
{% for f in m.cohort_fit %}
<tr {% if loop.index == 1 %}class="rank1"{% endif %}>
<td class="n">{{ f.rank }}</td><td><b>{{ f.label }}</b></td><td class="n">{{ f.listeners }}</td>
<td>{{ f.reason }}</td><td><code>{{ f.evidence }}</code></td></tr>
{% endfor %}
</tbody></table>
{% set risky = m.cohort_fit | selectattr('risks') | list %}
{% if risky %}
<p><b>Dealbreakers this script actually trips</b>, and who they threaten. A dealbreaker is listed
only against a region it is live for — the same beat that loses one region can be why another
one stays.</p>
<ul>
{% for f in risky %}{% for r in f.risks %}
<li><b>{{ f.label }}</b> — <code>{{ r.dealbreaker_id }}</code> at
{% for b in r.beat_ids %}<code>{{ b }}</code>{% if not loop.last %}, {% endif %}{% endfor %}:
{{ r.text }}</li>
{% endfor %}{% endfor %}
</ul>
{% endif %}
<p class="muted">Evidence tiers come from the shared ontology: <code>T-A</code> public evidence,
<code>T-B</code> industry prior, <code>T-C</code> this team's hypothesis. A region ranked highly on
<code>T-C</code> evidence is a hypothesis this run did not test.</p>
{% endif %}

{% if m.filler_beats %}
<h3>Filler</h3>
<p>Beats that move nothing and could be cut, ordered by the drop rate of the episode they sit in.
Filler in an episode nobody leaves is a tidiness note; the same beat in a high-drop episode is a
candidate for the drop itself.</p>
<table><thead><tr><th class="n">Ep</th><th>Beat</th><th>Title</th><th>Risk</th>
<th class="n">Drop at that ep</th></tr></thead><tbody>
{% for b in m.filler_beats[:12] %}
<tr><td class="n">{{ b.episode_no }}</td><td><code>{{ b.beat_id }}</code></td>
<td>{{ b.title[:40] }}</td><td>{{ b.churn_risk }}</td>
<td class="n">{% if b.drop_rate_at_episode is not none %}{{ '%.0f'|format(b.drop_rate_at_episode*100) }}%{% else %}—{% endif %}</td></tr>
{% endfor %}
</tbody></table>
{% endif %}

<h2>05 · Listening occasion</h2>
<h3>When they listen, rather than what they want</h3>
<p>A cohort that drops where others do not is usually a session-length problem rather than a
writing one — a different fix from anything in the section above.</p>
<table><thead><tr><th>Cohort</th><th class="n">Listeners</th><th class="n">Survived</th>
<th class="n">Pay rate</th><th class="n">Craving end</th><th class="n">Median drop ep</th></tr></thead><tbody>
{% for c in cohorts %}
<tr {% if loop.index == 1 %}class="rank1"{% endif %}>
<td>{{ c.cohort_id }}</td><td class="n">{{ c.listeners }}</td>
<td class="n">{{ '%.0f'|format(c.survived_to_end*100) }}%</td>
<td class="n">{{ '%.1f'|format(c.mean_pay_rate*100) }}%</td>
<td class="n">{{ '%.1f'|format(c.mean_craving_end) }}</td>
<td class="n">{{ c.median_drop_episode or '—' }}</td></tr>
{% endfor %}
</tbody></table>

{% if m.trope_fatigue %}
<h2>06 · Trope fatigue</h2>
<h3>Cliché, not weak writing</h3>
<p>Episodes where long-tenure listeners drop materially harder than new ones. The beat works fine
for someone hearing it for the first time — that gap is a repetition signal, and it needs a
different fix and a different reviewer.</p>
<table><thead><tr><th class="n">Ep</th><th class="n">Veteran drop</th><th class="n">New-user drop</th>
<th class="n">Gap</th></tr></thead><tbody>
{% for t in m.trope_fatigue %}
<tr><td class="n">{{ t.episode_no }}</td>
<td class="n">{{ '%.1f'|format(t.veteran_drop_rate*100) }}%</td>
<td class="n">{{ '%.1f'|format(t.new_user_drop_rate*100) }}%</td>
<td class="n">+{{ '%.1f'|format(t.gap*100) }}%</td></tr>
{% endfor %}
</tbody></table>
{% endif %}

{% if m.switch_to %}
<h2>07 · What they switch to</h2>
<h3>What you are losing attention to</h3>
<p>Aggregated from listeners who chose to leave. No satisfaction rating produces this.</p>
<table><thead><tr><th>Switched to</th><th class="n">Listeners</th></tr></thead><tbody>
{% for label, count in m.switch_to %}<tr><td>{{ label }}</td><td class="n">{{ count }}</td></tr>{% endfor %}
</tbody></table>
{% endif %}

<footer>Generated {{ now }} by pocketsim · run <code>{{ m.run_id }}</code> ·
population {{ m.population_size }} synthetic listeners · claims are relative only</footer>
</main></body></html>""")


def render_html(m: RunMetrics) -> str:
    seen = sorted({fl for f in m.fix_list for fl in f["flags"]})
    return HTML_TEMPLATE.render(
        m=m,
        spark=sparkline([e.active_after_share for e in m.episodes]),
        cohorts=sorted(m.cohorts, key=lambda c: -c.survived_to_end),
        flag_meanings=[(k, FLAG_MEANING.get(k, "")) for k in seen],
        now=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    )


def write_report(
    m: RunMetrics,
    out_dir: Path,
    *,
    meta: dict[str, Any] | None = None,
    population: Population | None = None,
    audit: AuditReport | None = None,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "verdict": out_dir / "verdict.json",
        "markdown": out_dir / "report.md",
        "html": out_dir / "report.html",
        "learning": out_dir / "learning.md",
    }
    payload = verdict(m)
    # Fail loudly rather than shipping a report that overclaims. A field name asserting a
    # calibrated prediction is the one error nobody catches by reading the output, because
    # it looks exactly like a number that was earned.
    if warnings := levels_lint(payload):
        raise ValueError(
            "verdict.json makes claims this run cannot support:\n  "
            + "\n  ".join(warnings)
        )
    paths["verdict"].write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    paths["markdown"].write_text(render_markdown(m), encoding="utf-8")
    paths["html"].write_text(render_html(m), encoding="utf-8")
    paths["learning"].write_text(
        render_learning_markdown(m, meta=meta, population=population, audit=audit),
        encoding="utf-8",
    )
    return paths
