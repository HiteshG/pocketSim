"""Persona synthesis — six layers, from a YAML archetype to a reviewable population.

Governing principle: **sample the numbers, generate the prose.**

The model never invents a numeric attribute. Every number a persona carries is drawn
from a distribution declared in the market YAML; the LLM only writes biography around
that skeleton. That split is what makes a population of 300 invented listeners
auditable (each number traces to a line a human can argue with), reproducible under a
seed, and correctable when real behavioural data arrives — at which point the
archetypes are swapped for discovered clusters and nothing else changes.

    Layer 1  market definition          markets/*.yaml
    Layer 2  cohort archetypes          markets/*.yaml
    Layer 3  numeric sampling           here, seeded
    Layer 4  biographical enrichment    here, LLM, batched for diversity
    Layer 5  automated diversity audit  here
    Layer 6  human validity gate        `pocketsim personas inspect`
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel

from .config import INTENSITY_ORDER, Cohort, Market, Region, sample_categorical
from .llm import LLMProvider
from .schema import PERSONA_PROSE_RESPONSE_FORMAT, Persona, Population

PROSE_CACHE = Path("populations/.prose_cache.json")
BATCH_SIZE = 20

MAX_RESAMPLE = 24
"""Attempts to draw a coherent skeleton before giving up. A cohort whose region mix and
distributions make most draws invalid is a YAML bug, and it should surface as a loud
failure at build time rather than as a quietly skewed population."""


# ─────────────────────────────────────────────────────────────────────────────
# Layer 3 — numeric sampling
# ─────────────────────────────────────────────────────────────────────────────


def allocate_cohorts(market: Market, count: int) -> dict[str, int]:
    """Split ``count`` across cohorts by declared weight, using largest remainder.

    Deliberately *not* a random draw: exact proportions mean two populations of the
    same size have identical cohort structure, so cross-population comparisons aren't
    confounded by sampling noise in the mixture itself.
    """
    weights = market.cohort_weights
    total = sum(weights.values())
    exact = {k: count * w / total for k, w in weights.items()}
    floors = {k: int(math.floor(v)) for k, v in exact.items()}
    remainder = count - sum(floors.values())
    for cid, _ in sorted(exact.items(), key=lambda kv: -(kv[1] - floors[kv[0]]))[:remainder]:
        floors[cid] += 1
    return floors


def sample_drivers(region: Region, jitter: float, rng: np.random.Generator) -> dict[str, str]:
    """The region's declared drivers, with at most one shifted a level.

    Without the jitter every member of a region carries byte-identical drivers, which
    makes the region a fixed persona rather than a high-density behavioural area — and a
    population of six repeated people produces a clean retention curve describing nobody.
    """
    drivers = dict(region.drivers)
    if drivers and rng.random() < jitter:
        names = list(drivers)
        name = names[int(rng.integers(len(names)))]
        pos = INTENSITY_ORDER.index(drivers[name])
        step = 1 if rng.random() < 0.5 else -1
        drivers[name] = INTENSITY_ORDER[min(max(pos + step, 0), len(INTENSITY_ORDER) - 1)]
    return drivers


# Predicates an `invalid_combinations` rule may test. Closed on purpose: an unrecognised
# key would silently make a rule inert, and a rule that never fires looks exactly like a
# rule that never needed to fire.
_RULE_PREDICATES: dict[str, Any] = {
    "commitment_max": lambda s, v: s["commitment_tolerance"] <= v,
    "commitment_min": lambda s, v: s["commitment_tolerance"] >= v,
    "patience_max": lambda s, v: s["narrative_patience"] <= v,
    "patience_min": lambda s, v: s["narrative_patience"] >= v,
    "pay_threshold_max": lambda s, v: s["pay_threshold"] <= v,
    "pay_threshold_min": lambda s, v: s["pay_threshold"] >= v,
    "churn_sensitivity_max": lambda s, v: s["churn_sensitivity"] <= v,
    "churn_sensitivity_min": lambda s, v: s["churn_sensitivity"] >= v,
    "exploration_max": lambda s, v: s["exploration_propensity"] <= v,
    "exploration_min": lambda s, v: s["exploration_propensity"] >= v,
    "region_in": lambda s, v: s["region_id"] in v,
    "register_in": lambda s, v: s["language_register"] in v,
}


def violated_rule(skeleton: dict[str, Any], rules: list[dict[str, Any]]) -> str | None:
    """Return the note of the first incoherent-combination rule this skeleton trips.

    A rule fires only when *every* predicate it declares holds, so a rule is a conjunction
    ("20-episode commitment AND a 500-episode region"), not a list of independent bans.
    """
    for rule in rules:
        predicates = {k: v for k, v in rule.items() if k != "note"}
        unknown = set(predicates) - set(_RULE_PREDICATES)
        if unknown:
            raise ValueError(
                f"invalid_combinations rule {rule.get('note', '')!r} uses unknown predicates "
                f"{sorted(unknown)}; known: {sorted(_RULE_PREDICATES)}"
            )
        if predicates and all(_RULE_PREDICATES[k](skeleton, v) for k, v in predicates.items()):
            return str(rule.get("note", "unnamed rule"))
    return None


def _draw(market: Market, cohort: Cohort, rng: np.random.Generator, idx: int) -> dict[str, Any]:
    """One unvalidated draw across both axes."""
    ontology = market.ontology

    tier = sample_categorical(cohort.city_tier_mix, rng)
    cities = market.cities_by_tier[tier]
    city = str(rng.choice(cities))

    affinity: dict[str, float] = {}
    for genre, prior in cohort.genre_priors.items():
        jittered = float(np.clip(prior + rng.normal(0, market.genre_noise), 0.0, 1.0))
        affinity[genre] = round(jittered, 3)

    # Axis 2. Sampled conditionally on the occasion cohort, per the ontology's sampling
    # order: market -> region|occasion -> style|region. Drawing the two independently
    # would produce homemakers who want system-progression epics at the population rate.
    region = ontology.region(sample_categorical(cohort.region_mix, rng))

    # Willingness-to-pay stays owned by the occasion cohort's payment tier; the region
    # only shifts it, because pay *psychology* (which gate converts you) is a taste fact
    # while pay *capacity* is an income fact.
    pay_threshold = float(
        np.clip(cohort.pay_threshold.sample(rng) + region.pay_threshold_shift, 0.0, 1.0)
    )

    anti = region.anti_stereotype
    is_anti = bool(anti) and rng.random() < anti.share

    return {
        "persona_id": f"pf_{idx:05d}",
        "cohort_id": cohort.id,
        "region_id": region.id,
        "age": int(cohort.age.sample(rng)),
        "gender": sample_categorical(cohort.gender_mix, rng),
        "city": city,
        "city_tier": int(tier),
        "genre_affinity": affinity,
        "avg_daily_minutes": int(cohort.avg_daily_minutes.sample(rng)),
        "session_minutes": round(cohort.session_minutes.sample(rng), 1),
        "session_pattern": cohort.session_pattern,
        "gap_hours": round(cohort.gap_hours.sample(rng), 1),
        "coin_spend_tier": sample_categorical(cohort.payment_mix, rng),
        "historical_completion": round(cohort.historical_completion.sample(rng), 3),
        "churn_sensitivity": round(cohort.churn_sensitivity.sample(rng), 3),
        "pay_threshold": round(pay_threshold, 3),
        "tenure_months": int(cohort.tenure_months.sample(rng)),
        "playback_speed": float(sample_categorical(cohort.playback_speed_mix, rng)),
        "listening_privacy": cohort.listening_privacy,
        # Falls back to the session pattern: a drip listener is interrupted by definition,
        # a binge listener mostly is not. Cohorts that genuinely depart from that — a
        # traveller on a six-hour train, someone at home with family around — declare it.
        "interruption_load": round(
            float(cohort.interruption_load.sample(rng))
            if cohort.interruption_load is not None
            else (0.60 if cohort.session_pattern == "drip" else 0.25),
            3,
        ),
        "discovery_channel": sample_categorical(
            cohort.discovery_mix or market.discovery_mix, rng
        ),
        "drivers": sample_drivers(region, ontology.driver_jitter, rng),
        "narrative_patience": round(float(region.narrative_patience.sample(rng)), 3),
        "commitment_tolerance": int(sample_categorical(region.commitment_mix, rng)),
        "exploration_propensity": round(float(region.exploration_propensity.sample(rng)), 3),
        "language_register": sample_categorical(region.register_mix, rng),
        # Drawn from declared population frequencies, independent of the behavioural
        # axes. Not conditioned on region on purpose: there is no evidence that a need
        # region implies a type, and inventing that correlation would smuggle MBTI into
        # the behavioural model through the back door.
        "mbti": sample_categorical(ontology.mbti_mix, rng) if ontology.mbti_mix else "ISTJ",
        "anti_stereotype": anti.label if is_anti else None,
        "provisional": cohort.provisional,
    }


def sample_skeleton(market: Market, cohort: Cohort, rng: np.random.Generator, idx: int) -> dict[str, Any]:
    """Draw one persona's numeric attributes across both axes, rejecting incoherent draws.

    Rejection is not tidying. A 20-episode attention span paired with a 500-episode epic
    preference is not a rare listener, it is a contradiction, and one of those in the panel
    argues against every finding it touches. Rare-but-coherent combinations are the
    opposite case and are preserved deliberately — see each region's anti-stereotype.

    Retries consume the seeded generator in a fixed order, so the population stays
    byte-identical under a given seed.
    """
    rules = market.ontology.invalid_combinations
    for _ in range(MAX_RESAMPLE):
        skeleton = _draw(market, cohort, rng, idx)
        if violated_rule(skeleton, rules) is None:
            return skeleton
    raise RuntimeError(
        f"cohort '{cohort.id}' could not produce a coherent skeleton in {MAX_RESAMPLE} draws. "
        f"Its region_mix and the regions' distributions are contradicting an "
        f"invalid_combinations rule — fix the market or the ontology, do not raise the cap."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Layer 4 — biographical enrichment
# ─────────────────────────────────────────────────────────────────────────────

PROSE_SYSTEM = """You write realistic listener profiles for an audio-fiction platform's
audience research. You are given numeric skeletons already sampled from behavioural
distributions. Your job is ONLY to write the human detail around each one.

Hard rules:
- NEVER contradict the numbers you are given. If the skeleton says age 41, tier-3 city,
  free tier, the biography must be consistent with all three.
- Every person must be clearly distinct from the others in this batch and from the names
  already used. Vary region, community, family situation, education and job. Do not
  reuse a first name or a surname that has already appeared.
- `persona` is 3-5 sentences of ENGLISH prose covering: who they are; exactly when and
  where they listen; their phone and mobile-data situation; what else competes for that
  same time slot; and what they grew up watching or listening to.
- Write specific jobs ("Swiggy delivery rider", "LIC field agent"), never categories
  ("worker", "professional").
- "What they want from a story" is a fact about this person, not a label to repeat. Let it
  show in what they say they liked before, not in a sentence announcing their psychology.
  Never write "they seek catharsis"; write what that looks like on a Tuesday evening.
- Do not evaluate or flatter these people. Describe them plainly."""


def _skeleton_digest(skel: dict[str, Any], market: str) -> str:
    stable = {k: v for k, v in skel.items() if k != "persona_id"}
    return hashlib.sha256(
        json.dumps({"m": market, **stable}, sort_keys=True).encode()
    ).hexdigest()[:24]


def _load_cache() -> dict[str, Any]:
    if PROSE_CACHE.exists():
        try:
            return json.loads(PROSE_CACHE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_cache(cache: dict[str, Any]) -> None:
    PROSE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    PROSE_CACHE.write_text(json.dumps(cache, indent=0, sort_keys=True), encoding="utf-8")


def _batch_prompt(market: Market, cohorts: dict[str, Cohort], skels: list[dict], used: list[str]) -> str:
    lines = [
        f"MARKET: {market.market} — listeners of {market.language} audio fiction in India.",
        f"They pay in {market.currency}; {market.money_anchor}.",
        "",
        "Write one profile per skeleton below. Return them in the same order.",
        "",
    ]
    if used:
        recent = used[-60:]
        lines += [f"NAMES ALREADY USED (do not reuse any first or last name): {', '.join(recent)}", ""]

    for i, s in enumerate(skels):
        c = cohorts[s["cohort_id"]]
        r = market.ontology.region(s["region_id"])
        drivers = ", ".join(f"{d.replace('_', ' ')} ({lvl})" for d, lvl in s["drivers"].items())
        lines += [
            f"#{i}",
            f"  cohort: {c.label}",
            f"  listening occasion: {' '.join(c.occasion.split())}",
            f"  age {s['age']}, {s['gender']}, {s['city']} (tier {s['city_tier']})",
            f"  typical jobs for this cohort: {', '.join(c.typical_professions)}",
            f"  listens ~{s['avg_daily_minutes']} min/day in ~{int(s['session_minutes'])} min sessions"
            f" at {s['playback_speed']}x, {s['session_pattern']} pattern",
            f"  on the platform {s['tenure_months']} months; spending tier: {s['coin_spend_tier']}",
            f"  listens: {s['listening_privacy'].replace('_', ' ')}",
            f"  favours: {', '.join(sorted(s['genre_affinity'], key=lambda g: -s['genre_affinity'][g])[:3])}",
            f"  what they want from a story: {drivers}",
            f"  personality type: {s['mbti']} — let this show in temperament and how they "
            f"talk, never as a label they would apply to themselves",
            f"  will commit to about {s['commitment_tolerance']} episodes; "
            f"{'patient' if s['narrative_patience'] >= 0.55 else 'impatient'} with slow build-up; "
            f"prefers {s['language_register']} writing",
        ]
        if s.get("anti_stereotype"):
            lines.append(
                f"  unusual for this type: {r.anti_stereotype.note}"
                if r.anti_stereotype
                else f"  unusual for this type: {s['anti_stereotype']}"
            )
        lines.append("")
    return "\n".join(lines)


async def enrich(
    provider: LLMProvider,
    market: Market,
    skeletons: list[dict[str, Any]],
    model: str | None = None,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """Attach prose to each skeleton, in batches, avoiding name collisions.

    Prose is cached by skeleton digest so a re-run with the same seed reproduces the
    same population byte-for-byte — LLM output is not otherwise deterministic, and
    `compare` is meaningless if the audience shifts between runs.
    """
    model = model or provider.model
    cohorts = {c.id: c for c in market.cohorts}
    cache = _load_cache() if use_cache else {}

    todo: list[int] = []
    out: list[dict[str, Any] | None] = [None] * len(skeletons)
    for i, s in enumerate(skeletons):
        hit = cache.get(_skeleton_digest(s, market.market)) if use_cache else None
        if hit:
            out[i] = {**s, **hit}
        else:
            todo.append(i)

    used_names: list[str] = [o["realname"] for o in out if o]

    for start in range(0, len(todo), BATCH_SIZE):
        idxs = todo[start : start + BATCH_SIZE]
        batch = [skeletons[i] for i in idxs]
        res = await provider.complete_json(
            system=PROSE_SYSTEM,
            user=_batch_prompt(market, cohorts, batch, used_names),
            response_format=PERSONA_PROSE_RESPONSE_FORMAT,
            model=model,
        )
        people = res.data.get("people", [])
        by_index = {int(p.get("index", n)): p for n, p in enumerate(people)}

        for n, i in enumerate(idxs):
            p = by_index.get(n) or (people[n] if n < len(people) else None)
            if p is None:  # model returned a short batch; fill rather than crash
                p = {
                    "realname": f"Listener {skeletons[i]['persona_id']}",
                    "profession": cohorts[skeletons[i]["cohort_id"]].typical_professions[0],
                    "persona": cohorts[skeletons[i]["cohort_id"]].occasion.strip(),
                    "interested_topics": [],
                }
            prose = {
                "realname": str(p.get("realname", "")).strip(),
                "profession": str(p.get("profession", "")).strip(),
                "persona": " ".join(str(p.get("persona", "")).split()),
                "interested_topics": list(p.get("interested_topics") or []),
            }
            out[i] = {**skeletons[i], **prose}
            used_names.append(prose["realname"])
            if use_cache:
                cache[_skeleton_digest(skeletons[i], market.market)] = prose

    if use_cache:
        _save_cache(cache)
    return [o for o in out if o is not None]


# ─────────────────────────────────────────────────────────────────────────────
# Build
# ─────────────────────────────────────────────────────────────────────────────


async def build_population(
    market: Market,
    count: int,
    seed: int,
    provider: LLMProvider,
    model: str | None = None,
    use_cache: bool = True,
) -> Population:
    rng = np.random.default_rng(seed)
    allocation = allocate_cohorts(market, count)

    skeletons: list[dict[str, Any]] = []
    idx = 0
    for cohort in market.cohorts:  # iterate in declared order → seed-stable
        for _ in range(allocation[cohort.id]):
            skeletons.append(sample_skeleton(market, cohort, rng, idx))
            idx += 1

    enriched = await enrich(provider, market, skeletons, model=model, use_cache=use_cache)
    return Population(
        market=market.market,
        seed=seed,
        count=len(enriched),
        generator_provider=provider.name,
        generator_model=model or provider.model,
        created_at=datetime.now(UTC).isoformat(),
        personas=[Persona.model_validate(e) for e in enriched],
    )


def save_population(pop: Population, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pop.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_population(path: Path) -> Population:
    if not path.exists():
        raise FileNotFoundError(f"population not found: {path}. Run `pocketsim personas build` first.")
    return Population.model_validate_json(path.read_text(encoding="utf-8"))


def population_report_paths(path: Path) -> dict[str, Path]:
    return {
        "audit_json": path.with_name(f"{path.stem}.audit.json"),
        "audit_markdown": path.with_name(f"{path.stem}.audit.md"),
    }


def render_population_report(pop: Population, market: Market, report: AuditReport) -> str:
    grouped = pop.by_cohort()
    lines = [
        f"# Population Report — {Path(report.population).name or pop.market}",
        "",
        "## Generation",
        "",
        f"- Market: `{pop.market}`",
        f"- Count: `{pop.count}`",
        f"- Seed: `{pop.seed}`",
        f"- Provider: `{pop.generator_provider or 'unknown'}`",
        f"- Model: `{pop.generator_model}`",
        f"- Fingerprint: `{pop.fingerprint}`",
        "- Method: numeric attributes sampled from market YAML distributions; prose generated around those fixed skeletons.",
        "",
        "## Cohort Mix",
        "",
        "| Cohort | Personas | Share |",
        "|---|---:|---:|",
    ]
    for cohort in market.cohorts:
        n = len(grouped.get(cohort.id, []))
        lines.append(f"| {cohort.id} | {n} | {n / pop.count:.1%} |")

    by_region = pop.by_region()
    marginals = market.region_marginals
    lines += [
        "",
        "## Need Regions",
        "",
        "The second axis. Cohorts above say *when* these listeners listen; regions say "
        "*what they want a story to do for them*. Sampled per persona from each cohort's "
        "declared `region_mix`, so the share moves within binomial noise rather than "
        "landing exactly on the declared marginal.",
        "",
        "| Region | Personas | Share | Declared | Evidence | Anti-stereotype |",
        "|---|---:|---:|---:|---|---:|",
    ]
    for region in market.ontology.regions:
        members = by_region.get(region.id, [])
        k = len(members)
        anti = sum(1 for p in members if p.anti_stereotype)
        lines.append(
            f"| {region.label} | {k} | {k / pop.count:.1%} | {marginals[region.id]:.1%} | "
            f"`{region.evidence}` | {anti} |"
        )

    driver_counts: Counter[str] = Counter()
    for p in pop.personas:
        driver_counts.update(p.drivers.keys())
    lines += [
        "",
        "Driver coverage across the frozen vocabulary: "
        + ", ".join(
            f"{d} {driver_counts[d]}" for d in market.ontology.drivers if driver_counts[d]
        )
        + ".",
        "",
        "Evidence tiers are inherited from `markets/_ontology.yaml`: `T-A` public evidence, "
        "`T-B` industry prior, `T-C` this team's hypothesis. A region tagged `T-C` is an "
        "assumption we own, not something we know.",
    ]

    lines += [
        "",
        "## Validation",
        "",
        f"Audit result: **{'PASS' if report.ok else 'FAIL'}**",
        "",
        "| Check | Result | Detail |",
        "|---|---|---|",
    ]
    for check in report.checks:
        result = "PASS" if check.passed else "FAIL"
        lines.append(f"| {check.name} | {result} | {check.detail} |")

    lines += [
        "",
        "## Human Gate",
        "",
        "Before using this population for claims, inspect a sample with `pocketsim personas inspect` and confirm these listeners are recognisable for the target market.",
    ]
    return "\n".join(lines)


def write_population_report(pop: Population, market: Market, report: AuditReport, path: Path) -> dict[str, Path]:
    paths = population_report_paths(path)
    paths["audit_json"].write_text(report.model_dump_json(indent=2), encoding="utf-8")
    paths["audit_markdown"].write_text(render_population_report(pop, market, report), encoding="utf-8")
    return paths


# ─────────────────────────────────────────────────────────────────────────────
# Layer 5 — diversity audit
# ─────────────────────────────────────────────────────────────────────────────


class Check(BaseModel):
    name: str
    passed: bool
    detail: str


class AuditReport(BaseModel):
    population: str
    count: int
    checks: list[Check]

    @property
    def ok(self) -> bool:
        return all(c.passed for c in self.checks)


def audit_population(pop: Population, market: Market, path: str = "") -> AuditReport:
    """Catch mode collapse before it silently poisons every downstream number.

    The default failure of LLM persona generation is 300 delivery riders called Rakesh
    in Indore. A population that has collapsed still produces a clean-looking retention
    curve — it just describes one imaginary person, repeated.
    """
    checks: list[Check] = []
    n = len(pop.personas)

    names = [p.realname.strip().lower() for p in pop.personas]
    dup_full = n - len(set(names))
    checks.append(
        Check(
            name="name-collisions",
            passed=dup_full <= max(1, int(0.02 * n)),
            detail=f"{dup_full} duplicate full names out of {n} ({dup_full / n:.1%})",
        )
    )

    first_names = Counter(nm.split()[0] for nm in names if nm)
    top_first, top_first_n = (first_names.most_common(1) or [("-", 0)])[0]
    checks.append(
        Check(
            name="first-name-concentration",
            passed=top_first_n <= max(3, int(0.12 * n)),
            detail=f"most common first name '{top_first}' appears {top_first_n}x ({top_first_n / n:.1%})",
        )
    )

    professions = Counter(p.profession.strip().lower() for p in pop.personas)
    uniq_ratio = len(professions) / n
    top_prof, top_prof_n = (professions.most_common(1) or [("-", 0)])[0]
    checks.append(
        Check(
            name="profession-diversity",
            passed=uniq_ratio >= 0.25 and top_prof_n <= max(5, int(0.20 * n)),
            detail=f"{len(professions)} distinct professions ({uniq_ratio:.0%}); "
            f"most common '{top_prof}' {top_prof_n}x",
        )
    )

    cities = Counter(p.city for p in pop.personas)
    checks.append(
        Check(
            name="city-spread",
            passed=len(cities) >= min(6, len({c for v in market.cities_by_tier.values() for c in v})),
            detail=f"{len(cities)} distinct cities; top: "
            + ", ".join(f"{c}({k})" for c, k in cities.most_common(3)),
        )
    )

    actual = Counter(p.cohort_id for p in pop.personas)
    expected = allocate_cohorts(market, n)
    worst = max((abs(actual[c] - e), c) for c, e in expected.items()) if expected else (0, "-")
    checks.append(
        Check(
            name="cohort-proportions",
            passed=worst[0] <= 1,
            detail=f"largest deviation from declared weights: {worst[1]} off by {worst[0]}",
        )
    )

    genre_dev: list[tuple[float, float, str]] = []
    for cohort in market.cohorts:
        members = [p for p in pop.personas if p.cohort_id == cohort.id]
        if not members:
            continue
        for genre, prior in cohort.genre_priors.items():
            mean = float(np.mean([p.genre_affinity.get(genre, 0.0) for p in members]))
            # The fixed 0.10 tolerance is appropriate around full 300-person panels, but
            # 25-person smoke tests have cohorts of only 2-4 listeners. Their sampled
            # means legitimately move more, so widen the tolerance by cohort sample size.
            tolerance = max(0.10, 0.55 / math.sqrt(len(members)))
            genre_dev.append((abs(mean - prior), tolerance, f"{cohort.id}/{genre}"))
    worst_genre = max(genre_dev) if genre_dev else (0.0, 0.10, "-")
    checks.append(
        Check(
            name="genre-affinity-fidelity",
            passed=worst_genre[0] <= worst_genre[1],
            detail=(
                f"largest |sample mean - declared prior|: {worst_genre[2]} = "
                f"{worst_genre[0]:.3f} (tolerance {worst_genre[1]:.3f})"
            ),
        )
    )

    empty_prose = sum(1 for p in pop.personas if len(p.persona.split()) < 15)
    checks.append(
        Check(
            name="prose-substance",
            passed=empty_prose <= max(1, int(0.02 * n)),
            detail=f"{empty_prose} personas with a biography under 15 words",
        )
    )

    # ── Need axis ────────────────────────────────────────────────────────────
    # The occasion axis is checked above. These check the second axis independently,
    # because a population can have perfect cohort proportions and still be collapsed
    # on what those listeners actually want from a story.

    region_counts = Counter(p.region_id for p in pop.personas)
    expected_regions = market.region_marginals
    worst_region = max(
        (abs(region_counts[r] / n - share), r) for r, share in expected_regions.items()
    )
    # Regions are sampled per persona rather than allocated exactly, so the deviation is
    # binomial and legitimately larger in small panels. Three standard errors at the
    # market's largest region, floored so a 25-person smoke test is not held to a
    # 300-person tolerance.
    region_tol = max(0.08, 3 * math.sqrt(0.25 / n))
    checks.append(
        Check(
            name="region-proportions",
            passed=worst_region[0] <= region_tol,
            detail=(
                f"largest |sample share - declared marginal|: {worst_region[1]} = "
                f"{worst_region[0]:.3f} (tolerance {region_tol:.3f})"
            ),
        )
    )

    missing_regions = [r for r in market.ontology.region_ids if region_counts[r] == 0]
    checks.append(
        Check(
            name="region-coverage",
            passed=not missing_regions or n < 2 * len(market.ontology.regions),
            detail=(
                f"{len(region_counts)}/{len(market.ontology.regions)} regions present"
                + (f"; absent: {', '.join(missing_regions)}" if missing_regions else "")
            ),
        )
    )

    # Every driver in the frozen vocabulary that no persona carries is a driver no
    # simulated listener can ever act on — the story dimension it represents becomes
    # untestable for this population, silently.
    driver_counts: Counter[str] = Counter()
    for p in pop.personas:
        driver_counts.update(p.drivers.keys())
    unused = [d for d in market.ontology.drivers if driver_counts[d] == 0]
    checks.append(
        Check(
            name="driver-coverage",
            passed=len(unused) <= 4,
            detail=(
                f"{len(market.ontology.drivers) - len(unused)}/{len(market.ontology.drivers)} "
                f"drivers represented"
                + (f"; unused: {', '.join(unused)}" if unused else "")
            ),
        )
    )

    # MBTI is sampled from declared population frequencies, so the panel should look like
    # that population rather than like the four common types. A panel that is 80% ISTJ/ESFJ
    # deliberates in two voices, which is the opposite of why the field was added.
    if market.ontology.mbti_mix:
        mbti_counts = Counter(p.mbti for p in pop.personas)
        worst_mbti = max(
            (abs(mbti_counts[t] / n - share), t) for t, share in market.ontology.mbti_mix.items()
        )
        mbti_tol = max(0.07, 3 * math.sqrt(0.25 / n))
        checks.append(
            Check(
                name="mbti-fidelity",
                passed=worst_mbti[0] <= mbti_tol,
                detail=(
                    f"{len(mbti_counts)}/16 types present; largest |sample - declared|: "
                    f"{worst_mbti[1]} = {worst_mbti[0]:.3f} (tolerance {mbti_tol:.3f})"
                ),
            )
        )

    # Anti-stereotype slices are what stop each region collapsing to its centroid. If
    # they vanish, the population is six repeated people wearing different names.
    anti = sum(1 for p in pop.personas if p.anti_stereotype)
    expected_anti = sum(
        expected_regions[r.id] * (r.anti_stereotype.share if r.anti_stereotype else 0.0)
        for r in market.ontology.regions
    )
    anti_tol = max(0.06, 3 * math.sqrt(max(expected_anti, 0.01) / n))
    checks.append(
        Check(
            name="anti-stereotype-share",
            passed=abs(anti / n - expected_anti) <= anti_tol,
            detail=(
                f"{anti}/{n} ({anti / n:.1%}) carry a low-probability variant; "
                f"declared {expected_anti:.1%} (tolerance {anti_tol:.3f})"
            ),
        )
    )

    return AuditReport(population=path or pop.market, count=n, checks=checks)
