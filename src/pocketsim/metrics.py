"""Roll-ups: turning ~4,000 raw reactions into things a person can act on.

The headline is the **Fix List** — episodes ranked by revenue at risk rather than by raw
drop rate. A weak episode at 6, before the paywall with the whole cohort still listening,
is a revenue emergency; the identical weakness at 18 is a nuisance. Drop rate alone
cannot tell those apart, and "which episode do I give my one available writer to" is the
question the writers' room actually has.

Everything here is RELATIVE. With no fitted personas and no backtest there is no basis
for an absolute retention claim, so no function in this module returns one.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from pydantic import BaseModel, Field

from .config import Market
from .schema import Beat

STOPWORDS = set(
    """the a an and or but of to in on at for with from by is are was were be been being
    will would could should may might can it its this that these those he she they them
    his her their i you we as if then than so about into over after before out up down
    not no yes get gets got go goes going come comes back next episode story who what
    which when where why how more most some any all one two three another""".split()
)


def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]{4,}", (text or "").lower()) if w not in STOPWORDS]


MAX_PAIRWISE_SAMPLE = 150


def prediction_disagreement(predictions: list[str]) -> tuple[float, str]:
    """How much listeners *disagree* about what happens next, and the shared theme.

    Returns ``(disagreement, consensus_label)``, disagreement in 0..1.

    Mean pairwise Jaccard **distance** between predictions, treated as token sets.
    Identical predictions → 0. Entirely unrelated predictions → ~1.

    Two rejected alternatives, both of which are wrong in instructive ways:

    * *Shannon entropy over token counts* measures vocabulary spread and runs backwards.
      Three hundred listeners predicting the identical thing produce a uniform
      distribution over their shared vocabulary and score maximum entropy, when the true
      answer is total agreement.
    * *1 − max document frequency* fails on the case that matters most. "Arjun confesses"
      and "Arjun is killed" are opposite predictions, but the character's name appears in
      both — and in a serialized story the protagonist's name appears in nearly every
      prediction, pinning the score at total agreement no matter how much listeners
      actually diverge.

    Pairwise set distance is robust to that shared scaffolding, because it weighs the
    whole overlap rather than a single most-common token.

    Why it matters: predictable is the death of the next-episode open. High craving with
    low disagreement means they already know what is coming and have no reason to hurry
    back. High craving with high disagreement is what a working cliffhanger looks like.
    """
    sets = [s for s in (set(_tokens(p)) for p in predictions if p and p.strip()) if s]
    if len(sets) < 2:
        return 0.0, "—"

    # Deterministic truncation keeps this O(k²) bounded without a random sample.
    sample = sets[:MAX_PAIRWISE_SAMPLE]
    total, pairs = 0.0, 0
    for i in range(len(sample)):
        for j in range(i + 1, len(sample)):
            union = sample[i] | sample[j]
            if union:
                total += 1.0 - len(sample[i] & sample[j]) / len(union)
                pairs += 1
    disagreement = total / pairs if pairs else 0.0

    df: Counter[str] = Counter()
    for s in sets:
        df.update(s)
    label = ", ".join(w for w, c in df.most_common(3) if c >= 2) or "—"
    return round(disagreement, 4), label


# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────


class EpisodeMetrics(BaseModel):
    episode_no: int
    listeners: int
    active_share: float
    active_after_share: float
    continue_rate: float
    drop_rate: float
    pay_rate: float
    craving_mid: float
    craving_end: float
    craving_delta: float
    prediction_entropy: float
    consensus_prediction: str
    top_drop_beats: list[tuple[str, int]]
    revenue_at_risk: float
    veteran_drop_rate: float | None
    new_user_drop_rate: float | None
    flags: list[str]


class CohortMetrics(BaseModel):
    cohort_id: str
    listeners: int
    survived_to_end: float
    mean_pay_rate: float
    mean_craving_end: float
    median_drop_episode: int | None


class RegionMetrics(BaseModel):
    """The same roll-up on the need axis: not *when* they listen, but what they wanted.

    Occasion answers "when does this story lose people"; region answers "which appetite is
    this story failing to feed". Two different fixes — reschedule the beat, or rewrite it.
    """

    region_id: str
    label: str
    evidence: str
    listeners: int
    survived_to_end: float
    mean_pay_rate: float
    mean_craving_end: float
    median_drop_episode: int | None
    abandon_beat: str | None
    """The beat this region most often leaves at. Module B's 'where do they abandon',
    computed from actual reactions rather than inferred from the script."""


class RunMetrics(BaseModel):
    run_id: str
    series: str
    market: str
    population_size: int
    planned_episodes: int
    episodes: list[EpisodeMetrics]
    cohorts: list[CohortMetrics]
    regions: list[RegionMetrics] = Field(default_factory=list)
    cohort_fit: list[dict[str, Any]] = Field(default_factory=list)
    filler_beats: list[dict[str, Any]] = Field(default_factory=list)
    fix_list: list[dict[str, Any]]
    paywall: dict[str, Any]
    hook: dict[str, Any]
    switch_to: list[tuple[str, int]]
    trope_fatigue: list[dict[str, Any]]
    provisional: bool = True

    @property
    def final_retention(self) -> float:
        return self.episodes[-1].active_after_share if self.episodes else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Computation
# ─────────────────────────────────────────────────────────────────────────────


def _rate(rows: list[dict], key: str) -> float:
    return sum(r[key] for r in rows) / len(rows) if rows else 0.0


def _mean(rows: list[dict], key: str) -> float:
    vals = [r[key] for r in rows if r.get(key) is not None]
    return sum(vals) / len(vals) if vals else 0.0


def classify_episode(
    drop_rate: float,
    craving_mid: float,
    craving_end: float,
    entropy: float,
    median_drop: float,
) -> list[str]:
    """Distinguish failure modes that need genuinely different fixes."""
    flags: list[str] = []
    delta = craving_end - craving_mid

    # Over-resolution: the episode closed its own loop. On a serialized platform a
    # satisfying ending is a churn event, and it is invisible to satisfaction ratings —
    # the listener enjoyed it and left. The fix is to end on the open loop, not to
    # "make it better".
    if delta <= -1.0 and drop_rate > median_drop:
        flags.append("OVER_RESOLVED")

    # Genuinely inert: nothing pulled at any point. The fix is stakes, not structure.
    if craving_mid < 5 and craving_end < 5 and drop_rate > median_drop:
        flags.append("BORING")

    # Working cliffhanger: high need-to-know and genuine disagreement about what comes
    # next. Predictable is the death of the next-episode open, so entropy matters as
    # much as craving.
    if craving_end >= 7 and entropy >= 0.75:
        flags.append("WORKING_HOOK")

    # They know exactly what's coming and want it anyway. Fine, but fragile — one
    # subverted expectation away from a drop.
    if craving_end >= 7 and entropy < 0.45:
        flags.append("PREDICTABLE_BUT_WANTED")

    if drop_rate >= median_drop * 1.6 and drop_rate > 0.05:
        flags.append("HIGH_DROP")
    return flags


def rank_cohort_fit(
    regions: list[RegionMetrics],
    market: Market,
    beats: dict[str, list[Beat]] | None = None,
) -> list[dict[str, Any]]:
    """Rank need regions 1..N for this story — the Story Intelligence cohort-fit vector.

    Deliberately ORDINAL. The underlying survival shares exist and are reported elsewhere,
    but the fit itself is published as a ranking because the ranking is the part that
    survives persona miscalibration: if every simulated listener is uniformly too patient,
    the absolute numbers all move and the ordering mostly does not. A percentage here
    would be read as a forecast, and nothing in this pipeline has earned that.

    The risk flag names which dealbreaker the script actually trips that is live for this
    region — evidence from the beat map, not a generic warning attached to the card.
    """
    tripped: dict[str, list[str]] = {}
    for ep_beats in (beats or {}).values():
        for beat in ep_beats:
            if beat.dealbreaker_id:
                tripped.setdefault(beat.dealbreaker_id, []).append(beat.beat_id)

    ontology = market.ontology
    ordered = sorted(
        regions, key=lambda r: (-r.survived_to_end, -r.mean_craving_end, r.region_id)
    )

    out: list[dict[str, Any]] = []
    for rank, rm in enumerate(ordered, start=1):
        region = ontology.region(rm.region_id)
        # A dealbreaker only threatens a region it is live for; D6 tripping is not a risk
        # to Slow-Burn Comfort Seekers, which is exactly the distinction the excl tags
        # exist to carry.
        predicates = {region.id, *region.drivers, *region.style_tags}
        risks = [
            {"dealbreaker_id": did, "beat_ids": bids[:3], "text": ontology.bank_entry(did).text}
            for did, bids in sorted(tripped.items())
            if ontology.applies(ontology.bank_entry(did), predicates)
        ]

        if rank == 1 and rm.survived_to_end > 0:
            reason = "survives longest and wants what this story is doing"
        elif rank == 1:
            # Nobody reached the end. Ranking first here means "held on longest", which is
            # a materially weaker claim than "this story is for them", and saying the
            # stronger thing would be the single most misleading line in the report.
            reason = "ranks first only on holding out longest — no listener reached the end"
        elif rm.median_drop_episode is not None:
            reason = f"typically leaves around episode {rm.median_drop_episode}"
        else:
            reason = "no clear drop point in this run"
        if rm.abandon_beat:
            reason += f"; most often at beat {rm.abandon_beat}"

        out.append(
            {
                "rank": rank,
                "region_id": rm.region_id,
                "label": rm.label,
                "evidence": rm.evidence,
                "listeners": rm.listeners,
                "reason": reason,
                "abandon_beat": rm.abandon_beat,
                "risks": risks,
            }
        )
    return out


def compute(
    rows: list[dict[str, Any]],
    *,
    run_id: str,
    series: str,
    market_name: str,
    population_size: int,
    total_episodes: int | None = None,
    market: Market | None = None,
    beats: dict[str, list[Beat]] | None = None,
) -> RunMetrics:
    by_ep: dict[int, list[dict]] = {}
    for r in rows:
        by_ep.setdefault(r["episode_no"], []).append(r)
    ep_nos = sorted(by_ep)
    n_eps = total_episodes or (max(ep_nos) if ep_nos else 0)

    # Pass 1 — per-episode primitives.
    raw: dict[int, dict[str, Any]] = {}
    for ep in ep_nos:
        er = by_ep[ep]
        entropy, consensus = prediction_disagreement([r.get("next_prediction") or "" for r in er])

        vets = [r for r in er if (r.get("tenure_months") or 0) >= 18]
        news = [r for r in er if (r.get("tenure_months") or 0) <= 2]

        raw[ep] = {
            "listeners": len(er),
            "active_share": len(er) / population_size if population_size else 0.0,
            "continue_rate": _rate(er, "will_continue"),
            "pay_rate": _rate(er, "would_pay"),
            "craving_mid": _mean(er, "craving_mid"),
            "craving_end": _mean(er, "craving_end"),
            "entropy": entropy,
            "consensus": consensus,
            "drop_beats": Counter(
                r["drop_beat"] for r in er if r.get("drop_beat") and not r.get("will_continue")
            ).most_common(5),
            "vet_drop": (1 - _rate(vets, "will_continue")) if len(vets) >= 5 else None,
            "new_drop": (1 - _rate(news, "will_continue")) if len(news) >= 5 else None,
        }

    drop_rates = sorted(1 - raw[e]["continue_rate"] for e in ep_nos)
    median_drop = drop_rates[len(drop_rates) // 2] if drop_rates else 0.0

    # Pass 2 — Revenue at Risk. A drop costs you every episode that listener would
    # otherwise have monetised, so weight by how much series is left to sell.
    episodes: list[EpisodeMetrics] = []
    for ep in ep_nos:
        d = raw[ep]
        drop = 1 - d["continue_rate"]
        remaining = max(n_eps - ep, 0)
        rar = drop * d["active_share"] * remaining
        episodes.append(
            EpisodeMetrics(
                episode_no=ep,
                listeners=d["listeners"],
                active_share=round(d["active_share"], 4),
                active_after_share=round(d["active_share"] * (1 - drop), 4),
                continue_rate=round(d["continue_rate"], 4),
                drop_rate=round(drop, 4),
                pay_rate=round(d["pay_rate"], 4),
                craving_mid=round(d["craving_mid"], 2),
                craving_end=round(d["craving_end"], 2),
                craving_delta=round(d["craving_end"] - d["craving_mid"], 2),
                prediction_entropy=round(d["entropy"], 3),
                consensus_prediction=d["consensus"],
                top_drop_beats=d["drop_beats"],
                revenue_at_risk=round(rar, 4),
                veteran_drop_rate=None if d["vet_drop"] is None else round(d["vet_drop"], 4),
                new_user_drop_rate=None if d["new_drop"] is None else round(d["new_drop"], 4),
                flags=classify_episode(
                    drop, d["craving_mid"], d["craving_end"], d["entropy"], median_drop
                ),
            )
        )

    max_rar = max((e.revenue_at_risk for e in episodes), default=0.0) or 1.0
    fix_list = [
        {
            "episode_no": e.episode_no,
            "revenue_at_risk": e.revenue_at_risk,
            "score": round(100 * e.revenue_at_risk / max_rar, 1),
            "drop_rate": e.drop_rate,
            "active_share": e.active_share,
            "episodes_remaining": max(n_eps - e.episode_no, 0),
            "flags": e.flags,
            "top_drop_beat": e.top_drop_beats[0][0] if e.top_drop_beats else None,
        }
        for e in sorted(episodes, key=lambda e: -e.revenue_at_risk)
    ]

    # Paywall. Conversion happens ONCE, at the gate: of the listeners still present at
    # episode g, pay_rate(g) convert, and that converted cohort then monetises every
    # remaining episode they hear.
    #
    #     revenue(g) = pay_rate(g) × Σ_{ep ≥ g} active_share(ep)
    #
    # The trade-off is real in both directions: gate early and the sum is large but few
    # are hooked enough to convert; gate late and conversion is high but there is little
    # series left to sell. Summing active_share × pay_rate per episode instead — the
    # obvious formulation — is monotonically decreasing in g and would always "recommend"
    # episode 1, which is not a recommendation, it is an artefact.
    paywall_curve = []
    for gate in ep_nos:
        reach = sum(raw[e]["active_share"] for e in ep_nos if e >= gate)
        value = raw[gate]["pay_rate"] * reach
        paywall_curve.append(
            {
                "gate_episode": gate,
                "expected_coin_episodes": round(value, 4),
                "conversion_at_gate": round(raw[gate]["pay_rate"], 4),
                "reach_after_gate": round(reach, 4),
            }
        )
    best = max(paywall_curve, key=lambda x: x["expected_coin_episodes"]) if paywall_curve else {}

    first = episodes[0] if episodes else None
    hook = (
        {
            "episode_no": first.episode_no,
            "continue_rate": first.continue_rate,
            "drop_rate": first.drop_rate,
            "craving_end": first.craving_end,
            "prediction_entropy": first.prediction_entropy,
            "score": round(100 * first.continue_rate * (first.craving_end / 10), 1),
        }
        if first
        else {}
    )

    # Cohorts
    by_cohort: dict[str, list[dict]] = {}
    for r in rows:
        by_cohort.setdefault(r["cohort_id"], []).append(r)
    cohorts: list[CohortMetrics] = []
    for cid, cr in sorted(by_cohort.items()):
        personas = {r["persona_id"] for r in cr}
        last_ep = max(ep_nos) if ep_nos else 0
        survived = {r["persona_id"] for r in cr if r["episode_no"] == last_ep and r["will_continue"]}
        drops = sorted(r["episode_no"] for r in cr if not r["will_continue"])
        cohorts.append(
            CohortMetrics(
                cohort_id=cid,
                listeners=len(personas),
                survived_to_end=round(len(survived) / len(personas), 4) if personas else 0.0,
                mean_pay_rate=round(_rate(cr, "would_pay"), 4),
                mean_craving_end=round(_mean(cr, "craving_end"), 2),
                median_drop_episode=drops[len(drops) // 2] if drops else None,
            )
        )

    # Need regions — the second axis.
    regions: list[RegionMetrics] = []
    cohort_fit: list[dict[str, Any]] = []
    if market is not None:
        by_region: dict[str, list[dict]] = {}
        for r in rows:
            if r.get("region_id"):
                by_region.setdefault(r["region_id"], []).append(r)

        for region in market.ontology.regions:
            rr = by_region.get(region.id, [])
            if not rr:
                continue
            personas = {r["persona_id"] for r in rr}
            last_ep = max(ep_nos) if ep_nos else 0
            survived = {
                r["persona_id"] for r in rr if r["episode_no"] == last_ep and r["will_continue"]
            }
            drops = sorted(r["episode_no"] for r in rr if not r["will_continue"])
            abandon = Counter(
                r["drop_beat"] for r in rr if r.get("drop_beat") and not r.get("will_continue")
            ).most_common(1)
            regions.append(
                RegionMetrics(
                    region_id=region.id,
                    label=region.label,
                    evidence=region.evidence,
                    listeners=len(personas),
                    survived_to_end=round(len(survived) / len(personas), 4) if personas else 0.0,
                    mean_pay_rate=round(_rate(rr, "would_pay"), 4),
                    mean_craving_end=round(_mean(rr, "craving_end"), 2),
                    median_drop_episode=drops[len(drops) // 2] if drops else None,
                    abandon_beat=abandon[0][0] if abandon else None,
                )
            )

        cohort_fit = rank_cohort_fit(regions, market, beats)

    # Filler: beats that move nothing and could be cut. Reported with the drop rate at
    # their episode, because a filler beat in an episode nobody leaves is a tidiness note,
    # while the same beat in a high-drop episode is the drop.
    filler_beats: list[dict[str, Any]] = []
    if beats:
        drop_by_ep = {e.episode_no: e.drop_rate for e in episodes}
        for ep_key, ep_beats in beats.items():
            try:
                ep_no = int(ep_key)
            except ValueError:
                continue
            for beat in ep_beats:
                if beat.is_filler:
                    filler_beats.append(
                        {
                            "episode_no": ep_no,
                            "beat_id": beat.beat_id,
                            "title": beat.title,
                            "churn_risk": beat.churn_risk,
                            "drop_rate_at_episode": drop_by_ep.get(ep_no),
                        }
                    )
        filler_beats.sort(key=lambda b: -(b["drop_rate_at_episode"] or 0.0))

    switch_to = Counter(
        (r.get("switch_to") or "").strip().lower() for r in rows if r.get("switch_to")
    ).most_common(10)

    # Trope fatigue: veterans dropping where new users don't is cliché, not weak writing.
    # Different diagnosis, different fix, different reviewer.
    trope = [
        {
            "episode_no": e.episode_no,
            "veteran_drop_rate": e.veteran_drop_rate,
            "new_user_drop_rate": e.new_user_drop_rate,
            "gap": round(e.veteran_drop_rate - e.new_user_drop_rate, 4),
        }
        for e in episodes
        if e.veteran_drop_rate is not None
        and e.new_user_drop_rate is not None
        and e.veteran_drop_rate - e.new_user_drop_rate >= 0.10
    ]

    return RunMetrics(
        run_id=run_id,
        series=series,
        market=market_name,
        population_size=population_size,
        planned_episodes=n_eps,
        episodes=episodes,
        cohorts=cohorts,
        regions=regions,
        cohort_fit=cohort_fit,
        filler_beats=filler_beats,
        fix_list=fix_list,
        paywall={"recommended_gate": best.get("gate_episode"), "curve": paywall_curve},
        hook=hook,
        switch_to=switch_to,
        trope_fatigue=trope,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Paired comparison
# ─────────────────────────────────────────────────────────────────────────────


class EpisodeDelta(BaseModel):
    episode_no: int
    base_drop_rate: float
    new_drop_rate: float
    drop_delta: float
    base_craving_end: float
    new_craving_end: float
    craving_delta: float
    verdict: str


class Comparison(BaseModel):
    base_run: str
    against_run: str
    same_population: bool
    is_null_test: bool = False
    episodes: list[EpisodeDelta]
    base_final_retention: float
    new_final_retention: float
    retention_delta: float
    observed_noise: float
    summary: str


def compare(
    base: RunMetrics,
    new: RunMetrics,
    same_population: bool,
    is_null_test: bool = False,
) -> Comparison:
    """Diff two runs episode by episode.

    Only meaningful on the *same* population — persona-level bias then cancels in the
    difference, which is exactly why relative claims survive miscalibration where
    absolute ones do not. If the populations differ, the delta measures the audience.

    When both runs used the same *script* as well, this is a **null test**: the delta is
    pure run-to-run noise, and it is the single most important number to measure before
    trusting any rewrite result. A rewrite that moves retention by less than the noise
    floor has not been shown to do anything.
    """
    b = {e.episode_no: e for e in base.episodes}
    n = {e.episode_no: e for e in new.episodes}
    deltas: list[EpisodeDelta] = []

    for ep in sorted(set(b) & set(n)):
        dd = n[ep].drop_rate - b[ep].drop_rate
        cd = n[ep].craving_end - b[ep].craving_end
        if abs(dd) < 0.005:
            verdict = "no change"
        elif dd < 0:
            verdict = f"improved — {abs(dd) * 100:.1f} pts fewer drops"
        else:
            verdict = f"regressed — {dd * 100:.1f} pts more drops"
        deltas.append(
            EpisodeDelta(
                episode_no=ep,
                base_drop_rate=b[ep].drop_rate,
                new_drop_rate=n[ep].drop_rate,
                drop_delta=round(dd, 4),
                base_craving_end=b[ep].craving_end,
                new_craving_end=n[ep].craving_end,
                craving_delta=round(cd, 2),
                verdict=verdict,
            )
        )

    rd = new.final_retention - base.final_retention
    # Largest per-episode swing, as a stand-in for how much this pair moves at all.
    noise = max((abs(e.drop_delta) for e in deltas), default=0.0)

    if not same_population:
        summary = (
            "POPULATIONS DIFFER — this comparison is not valid. Re-run both against the "
            "same population file so persona bias cancels in the difference."
        )
    elif is_null_test:
        if noise < 0.005 and abs(rd) < 0.005:
            summary = (
                "NULL TEST PASSED — the same script compared against itself moves nothing. "
                "Any delta a real rewrite produces is signal, not noise."
            )
        else:
            summary = (
                f"NULL TEST — same script, same audience, run twice. Final retention moved "
                f"{abs(rd) * 100:.1f} points and the largest per-episode swing was "
                f"{noise * 100:.1f} points with NOTHING changed. That is this "
                f"configuration's noise floor: treat any rewrite delta below it as "
                f"unproven, and raise the population size or lower sampling temperature "
                f"if you need to resolve smaller effects."
            )
    elif abs(rd) < 0.005:
        summary = "No material difference in final retention."
    else:
        direction = "improves" if rd > 0 else "regresses"
        summary = (
            f"Rewrite {direction} final retention by {abs(rd) * 100:.1f} points. "
            f"Run a null test (same script, same population, two run-ids) to confirm this "
            f"exceeds the noise floor before reporting it."
        )

    return Comparison(
        base_run=base.run_id,
        against_run=new.run_id,
        same_population=same_population,
        is_null_test=is_null_test,
        episodes=deltas,
        base_final_retention=round(base.final_retention, 4),
        new_final_retention=round(new.final_retention, 4),
        retention_delta=round(rd, 4),
        observed_noise=round(noise, 4),
        summary=summary,
    )
