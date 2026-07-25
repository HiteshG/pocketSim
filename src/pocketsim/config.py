"""Market configuration: cohort archetypes and the distributions personas are sampled from.

The governing principle of persona synthesis is *sample the numbers, generate the prose*.
Every numeric attribute a persona carries is drawn from a distribution declared here, so
any number in the population can be traced back to a stated assumption in a YAML file.
When real listening data arrives, these hand-authored archetypes are replaced by clusters
discovered from behavioural logs — nothing downstream changes.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, ClassVar, Literal, get_args

import numpy as np
import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

MARKETS_DIR = Path(__file__).resolve().parents[2] / "markets"

DistName = Literal["normal", "lognormal", "exponential", "uniform", "beta", "constant"]


class Distribution(BaseModel):
    """A univariate distribution declared in YAML, e.g. ``{dist: normal, mean: 20, sd: 6}``."""

    dist: DistName
    # normal / lognormal
    mean: float | None = None
    sd: float | None = None
    median: float | None = None
    sigma: float | None = None
    # uniform
    low: float | None = None
    high: float | None = None
    # beta
    alpha: float | None = None
    beta: float | None = None
    # constant
    value: float | None = None
    # post-processing
    clamp: tuple[float, float] | None = None
    integer: bool = False

    @model_validator(mode="after")
    def _check_params(self) -> Distribution:
        required: dict[str, tuple[str, ...]] = {
            "normal": ("mean", "sd"),
            "lognormal": ("median", "sigma"),
            "exponential": ("mean",),
            "uniform": ("low", "high"),
            "beta": ("alpha", "beta"),
            "constant": ("value",),
        }
        missing = [f for f in required[self.dist] if getattr(self, f) is None]
        if missing:
            raise ValueError(f"dist '{self.dist}' requires {required[self.dist]}, missing {missing}")
        return self

    def sample(self, rng: np.random.Generator) -> float:
        if self.dist == "normal":
            x = rng.normal(self.mean, self.sd)
        elif self.dist == "lognormal":
            # Parameterised by median so YAML stays readable: median = exp(mu).
            x = rng.lognormal(math.log(self.median), self.sigma)
        elif self.dist == "exponential":
            x = rng.exponential(self.mean)
        elif self.dist == "uniform":
            x = rng.uniform(self.low, self.high)
        elif self.dist == "beta":
            x = rng.beta(self.alpha, self.beta)
        else:
            x = float(self.value)

        if self.clamp is not None:
            x = min(max(x, self.clamp[0]), self.clamp[1])
        if self.integer:
            x = int(math.floor(x + 0.5))
        return x


def sample_categorical(weights: dict[str, float], rng: np.random.Generator) -> str:
    """Weighted choice over a ``{label: weight}`` mapping. Weights need not sum to 1."""
    labels = list(weights.keys())
    probs = np.array([weights[k] for k in labels], dtype=float)
    total = probs.sum()
    if total <= 0:
        raise ValueError(f"categorical weights must sum > 0, got {weights}")
    return str(rng.choice(labels, p=probs / total))


# ─────────────────────────────────────────────────────────────────────────────
# Need regions — the second axis
#
# The occasion cohort below says *when and how* someone listens. A need region says
# *what they want a story to do for them*. Neither subsumes the other, and a variable
# lives on exactly one of them — see the ownership rule in markets/_ontology.yaml.
#
# Regions, drivers and the hook/dealbreaker banks are declared once in that shared
# file and imported by every market, so editing a region changes every market with
# no other edit. Markets contribute the join (`Cohort.region_mix`) and may narrow a
# region's register only.
# ─────────────────────────────────────────────────────────────────────────────

Intensity = Literal["low", "med", "high"]
Register = Literal["pulp", "mid", "literary"]
EvidenceTier = Literal["T-A", "T-B", "T-C"]

INTENSITY_ORDER: tuple[Intensity, ...] = ("low", "med", "high")

MBTI_TYPES: tuple[str, ...] = (
    "ISTJ", "ISFJ", "INFJ", "INTJ", "ISTP", "ISFP", "INFP", "INTP",
    "ESTP", "ESFP", "ENFP", "ENTP", "ESTJ", "ESFJ", "ENFJ", "ENTJ",
)


class BankEntry(BaseModel):
    """One hook or dealbreaker from Block D.

    ``aff`` boosts an entry for those drivers, regions or style predicates; ``excl``
    removes it for them entirely. Both validate against a closed vocabulary at load
    time so a typo is a startup error rather than a silently inert tag.
    """

    id: str
    text: str
    scope: Literal["universal", "affinity"] = "affinity"
    aff: list[str] = Field(default_factory=list)
    excl: list[str] = Field(default_factory=list)


class AntiStereotype(BaseModel):
    """The declared low-probability variant of a region.

    Its job is preventing behavioural collapse, not being right. Without it every
    member of a region behaves like the region's centroid, and a population of
    centroids produces a clean retention curve describing nobody.
    """

    share: float = Field(gt=0, lt=1)
    label: str
    note: str


class Region(BaseModel):
    """A high-density behavioural area — a reporting bucket, not a fixed persona."""

    id: str
    label: str
    """Behavioural name. Used verbatim in every report, chart and deck surface:
    'Household-Catharsis Devotees', never 'Tier-2 women'. Demographics belong in
    sampling weights, never in a label."""

    evidence: EvidenceTier
    evidence_note: str = ""

    drivers: dict[str, Intensity]
    narrative_patience: Distribution
    exploration_propensity: Distribution
    commitment_mix: dict[str, float]
    register_mix: dict[str, float]

    pay_threshold_shift: float = 0.0
    """Modifies the cohort-sampled pay_threshold, re-clipped to [0,1]. Encodes which
    *gate* converts this region, not a second willingness-to-pay draw — the base rate
    stays owned by the occasion cohort's payment tier."""

    hooks: list[str] = Field(default_factory=list)
    dealbreakers: list[str] = Field(default_factory=list)
    pay_psychology: str = ""
    """Analyst-facing. Goes in reports."""

    pay_voice: str = ""
    """The same fact addressed to the listener. Goes in the simulation prompt.

    Kept separate from `pay_psychology` because a persona told "you are the most
    pay-selective region" has been handed the answer sheet — it starts reasoning about
    its own label instead of about the episode it just heard."""

    churn_triggers: list[str] = Field(default_factory=list)
    anti_stereotype: AntiStereotype | None = None

    style_tags: list[str] = Field(default_factory=list)
    """Style predicates this region satisfies as a matter of identity, e.g. `romance_centric`.

    Declared rather than inferred: the alternative is a region-id-to-predicate table in
    code, which is exactly the hardcoded cohort knowledge the shared ontology exists to
    prevent. Predicates derived from a *persona's* sampled values (patience, register) are
    computed instead — see `Ontology.predicates_for`."""

    @field_validator("commitment_mix", "register_mix")
    @classmethod
    def _positive_mix(cls, v: dict[str, float]) -> dict[str, float]:
        if not v or any(w < 0 for w in v.values()) or sum(v.values()) <= 0:
            raise ValueError(f"mix must be non-empty with non-negative weights summing > 0: {v}")
        return v

    @property
    def primary_drivers(self) -> list[str]:
        """Drivers at HIGH, then MED — the order a persona would describe themselves in."""
        return [d for d in self.drivers if self.drivers[d] == "high"] + [
            d for d in self.drivers if self.drivers[d] == "med"
        ]


class Ontology(BaseModel):
    """The shared need model. One copy, imported by every market."""

    ontology_version: str = "1.0"
    drivers: list[str]
    """PRD §2.2 vocabulary — frozen. Every driver referenced anywhere must be in here."""

    style_predicates: list[str] = Field(default_factory=list)
    driver_jitter: float = Field(default=0.25, ge=0.0, le=1.0)

    mbti_mix: dict[str, float] = Field(default_factory=dict)
    """Declared population frequencies for the 16 types. Sampled like every other
    categorical, so a persona's type traces to a line in YAML rather than to model whim.
    Conditions voice and decision style only — see the scope note in the ontology file."""
    hook_bank: list[BankEntry] = Field(default_factory=list)
    dealbreaker_bank: list[BankEntry] = Field(default_factory=list)
    regions: list[Region]
    invalid_combinations: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> Ontology:
        ids = [r.id for r in self.regions]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate region ids: {ids}")

        if self.mbti_mix:
            unknown = set(self.mbti_mix) - set(MBTI_TYPES)
            if unknown:
                raise ValueError(f"mbti_mix has unknown types: {sorted(unknown)}")
            missing = set(MBTI_TYPES) - set(self.mbti_mix)
            if missing:
                raise ValueError(f"mbti_mix is missing types: {sorted(missing)}")
            total = sum(self.mbti_mix.values())
            if abs(total - 1.0) > 0.01:
                raise ValueError(
                    f"mbti_mix must sum to ~1.0 (population frequencies), got {total:.4f}"
                )

        known_drivers = set(self.drivers)
        # A bank tag may name a driver, a region or a declared style predicate. Anything
        # else is a typo, and a typo in a tag is invisible at runtime — the entry simply
        # never applies to anyone — so it has to fail at load.
        taggable = known_drivers | set(ids) | set(self.style_predicates)
        banks = {"hook_bank": self.hook_bank, "dealbreaker_bank": self.dealbreaker_bank}
        seen: set[str] = set()
        for bank_name, bank in banks.items():
            for entry in bank:
                if entry.id in seen:
                    raise ValueError(f"duplicate bank id '{entry.id}'")
                seen.add(entry.id)
                unknown = (set(entry.aff) | set(entry.excl)) - taggable
                if unknown:
                    raise ValueError(
                        f"{bank_name} entry '{entry.id}' tags unknown terms {sorted(unknown)}; "
                        f"tags must name a driver, a region id or a declared style predicate"
                    )

        hook_ids = {e.id for e in self.hook_bank}
        dealbreaker_ids = {e.id for e in self.dealbreaker_bank}
        for region in self.regions:
            unknown_drivers = set(region.drivers) - known_drivers
            if unknown_drivers:
                raise ValueError(
                    f"region '{region.id}' uses drivers outside the frozen vocabulary: "
                    f"{sorted(unknown_drivers)}"
                )
            missing_hooks = set(region.hooks) - hook_ids
            missing_dbs = set(region.dealbreakers) - dealbreaker_ids
            if missing_hooks or missing_dbs:
                raise ValueError(
                    f"region '{region.id}' references bank ids that do not exist: "
                    f"hooks {sorted(missing_hooks)}, dealbreakers {sorted(missing_dbs)}"
                )
            unknown_registers = set(region.register_mix) - set(get_args(Register))
            if unknown_registers:
                raise ValueError(
                    f"region '{region.id}' register_mix has unknown registers: "
                    f"{sorted(unknown_registers)}"
                )
            unknown_tags = set(region.style_tags) - set(self.style_predicates)
            if unknown_tags:
                raise ValueError(
                    f"region '{region.id}' style_tags are not declared style_predicates: "
                    f"{sorted(unknown_tags)}"
                )
        return self

    # Thresholds for the two predicates derived from a persona's sampled values. The gap
    # between them is deliberate: a listener at 0.5 patience is neither notably patient nor
    # notably impatient, and forcing every persona into one bucket would make both tags
    # meaningless.
    LOW_PATIENCE_BELOW: ClassVar[float] = 0.40
    HIGH_PATIENCE_AT_OR_ABOVE: ClassVar[float] = 0.60

    def predicates_for(
        self, region: Region, drivers: dict[str, str], register: str, patience: float
    ) -> set[str]:
        """Everything a bank tag can match against for one specific listener."""
        tags = {region.id, *drivers, *region.style_tags, f"{register}_register"}
        if patience < self.LOW_PATIENCE_BELOW:
            tags.add("low_patience")
        if patience >= self.HIGH_PATIENCE_AT_OR_ABOVE:
            tags.add("high_patience")
        return tags

    def applies(self, entry: BankEntry, predicates: set[str]) -> bool:
        """Whether a hook or dealbreaker is live for a listener with these predicates.

        `excl` beats everything — that is what makes Slow-Burn Comfort Seekers the one
        region that will pay at a resolved episode (D6) instead of resenting the gate.
        """
        if predicates & set(entry.excl):
            return False
        if entry.scope == "universal":
            return True
        return bool(predicates & set(entry.aff))

    def bank_for(
        self,
        region: Region,
        drivers: dict[str, str],
        register: str,
        patience: float,
        limit: int = 6,
    ) -> tuple[list[BankEntry], list[BankEntry]]:
        """The hooks and dealbreakers that are live for one listener, most specific first.

        Region-declared entries lead because they are what distinguishes this listener from
        the rest of the panel; universals follow to fill the budget. The cap exists because
        listing all thirty flattens the discrimination we are paying for — a persona told
        everything is a dealbreaker drops on everything.
        """

        def pick(bank: list[BankEntry], declared: list[str]) -> list[BankEntry]:
            predicates = self.predicates_for(region, drivers, register, patience)
            live = [e for e in bank if self.applies(e, predicates)]
            order = {eid: i for i, eid in enumerate(declared)}
            live.sort(key=lambda e: (order.get(e.id, len(order)), e.id))
            return live[:limit]

        return pick(self.hook_bank, region.hooks), pick(self.dealbreaker_bank, region.dealbreakers)

    @property
    def region_ids(self) -> list[str]:
        return [r.id for r in self.regions]

    def region(self, region_id: str) -> Region:
        for r in self.regions:
            if r.id == region_id:
                return r
        raise KeyError(f"no region '{region_id}' in the ontology")

    def bank_entry(self, entry_id: str) -> BankEntry:
        for entry in (*self.hook_bank, *self.dealbreaker_bank):
            if entry.id == entry_id:
                return entry
        raise KeyError(f"no bank entry '{entry_id}'")


class Cohort(BaseModel):
    """A listening-occasion archetype. The population is a weighted mixture of these."""

    id: str
    weight: float = Field(gt=0)
    label: str
    occasion: str
    """Prose description of *when and how* this cohort listens. Goes into the persona prompt."""

    region_mix: dict[str, float] = Field(default_factory=dict)
    """The join to the need axis: given that someone listens THIS way, what do they want
    from a story? Hand-authored per market, because the same region is reached through
    different occasions in different places."""

    session_pattern: Literal["binge", "drip"]
    """Binge listeners hear several episodes back to back, so the episode boundary is barely a
    decision point. Drip listeners return a day later, having forgotten most of it — the gap
    decay in simulate.py tests whether the cliffhanger survived the night."""

    # Behavioural distributions
    session_minutes: Distribution
    gap_hours: Distribution
    tenure_months: Distribution
    age: Distribution
    churn_sensitivity: Distribution
    pay_threshold: Distribution
    historical_completion: Distribution
    avg_daily_minutes: Distribution

    interruption_load: Distribution | None = None
    """0-1: how often this listening situation gets broken into. Optional — when absent
    it falls back to the session pattern, since a drip listener is interrupted by
    definition and a binge listener mostly is not. Declared explicitly only where a
    cohort departs from that (a traveller on a six-hour train, a parent at home)."""

    discovery_mix: dict[str, float] = Field(default_factory=dict)
    """How this cohort arrived at the series. Falls back to the market default."""

    # Categorical mixes
    payment_mix: dict[str, float]
    city_tier_mix: dict[str, float]
    gender_mix: dict[str, float]
    playback_speed_mix: dict[str, float]

    genre_priors: dict[str, float]
    listening_privacy: str
    typical_professions: list[str]
    provisional: bool = True

    @field_validator("payment_mix", "city_tier_mix", "gender_mix", "playback_speed_mix", "region_mix")
    @classmethod
    def _positive_weights(cls, v: dict[str, float]) -> dict[str, float]:
        if not v or any(w < 0 for w in v.values()) or sum(v.values()) <= 0:
            raise ValueError(f"mix must be non-empty with non-negative weights summing > 0: {v}")
        return v


class Market(BaseModel):
    """One language-market. Adding a market is adding a YAML file, never a code change."""

    market: str
    language: str
    script_system: str
    reasoning_language: str
    currency: str
    money_anchor: str
    """Willingness-to-pay is anchored in local relative terms. A model reasoning about an
    abstract '₹49' misjudges; told it is 'about two cups of roadside chai' it reasons sensibly."""

    coin_pack_label: str
    alternatives: list[str]
    """What listeners switch *to*. Makes the continuation question an opportunity cost rather
    than an evaluation, which is how the decision actually happens."""

    genres: list[str]
    cities_by_tier: dict[str, list[str]]
    genre_noise: float = 0.15
    cohorts: list[Cohort]

    discovery_mix: dict[str, float] = Field(
        default_factory=lambda: {
            "ad": 0.40,
            "in_app_recommendation": 0.30,
            "browsing": 0.18,
            "friend": 0.12,
        }
    )
    """Market-wide default for how listeners arrive at a series; cohorts may override."""

    ontology: Ontology
    """Resolved at load time from the shared file this market names. Never authored inline
    — Story Intelligence Ontology §1 requires regions to be imported and not restated, so
    that editing a card propagates everywhere with no consumer-side edit."""

    @model_validator(mode="after")
    def _check_cohorts(self) -> Market:
        if not self.cohorts:
            raise ValueError("market must declare at least one cohort")
        ids = [c.id for c in self.cohorts]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate cohort ids: {ids}")
        region_ids = set(self.ontology.region_ids)
        for c in self.cohorts:
            unknown = set(c.genre_priors) - set(self.genres)
            if unknown:
                raise ValueError(f"cohort '{c.id}' has genre_priors not in market genres: {unknown}")
            unknown_tiers = set(c.city_tier_mix) - set(self.cities_by_tier)
            if unknown_tiers:
                raise ValueError(f"cohort '{c.id}' references unknown city tiers: {unknown_tiers}")
            if not c.region_mix:
                raise ValueError(
                    f"cohort '{c.id}' declares no region_mix. Every occasion cohort must say "
                    f"which need regions it draws from; without it the need axis is missing "
                    f"for {c.weight:.0%} of the population."
                )
            unknown_regions = set(c.region_mix) - region_ids
            if unknown_regions:
                raise ValueError(
                    f"cohort '{c.id}' region_mix references unknown regions: {sorted(unknown_regions)}"
                )
        return self

    @property
    def region_marginals(self) -> dict[str, float]:
        """Population-level share of each need region, implied by cohort weights × region_mix.

        Reported in the population audit so the join's aggregate consequence is visible
        rather than buried in eight separate mixes — it is easy to author eight plausible
        rows that sum to an implausible market.
        """
        total_w = sum(c.weight for c in self.cohorts)
        out = dict.fromkeys(self.ontology.region_ids, 0.0)
        for c in self.cohorts:
            mix_total = sum(c.region_mix.values())
            for rid, w in c.region_mix.items():
                out[rid] += (c.weight / total_w) * (w / mix_total)
        return out

    @property
    def cohort_weights(self) -> dict[str, float]:
        return {c.id: c.weight for c in self.cohorts}

    def cohort(self, cohort_id: str) -> Cohort:
        for c in self.cohorts:
            if c.id == cohort_id:
                return c
        raise KeyError(f"no cohort '{cohort_id}' in market '{self.market}'")

    def sample_cohort(self, rng: np.random.Generator) -> Cohort:
        return self.cohort(sample_categorical(self.cohort_weights, rng))

    @property
    def is_provisional(self) -> bool:
        """True while any cohort is still hand-authored rather than fitted from real logs."""
        return any(c.provisional for c in self.cohorts)


DEFAULT_ONTOLOGY = "_ontology"


def market_path(name_or_path: str) -> Path:
    """Resolve a market by bare name (``india-hindi``) or explicit path."""
    p = Path(name_or_path)
    if p.suffix in {".yaml", ".yml"} and p.exists():
        return p
    candidate = MARKETS_DIR / f"{name_or_path}.yaml"
    if candidate.exists():
        return candidate
    available = list_markets()
    raise FileNotFoundError(f"market '{name_or_path}' not found. Available: {available or '(none)'}")


def load_ontology(name_or_path: str = DEFAULT_ONTOLOGY) -> Ontology:
    p = Path(name_or_path)
    if not (p.suffix in {".yaml", ".yml"} and p.exists()):
        p = MARKETS_DIR / f"{name_or_path}.yaml"
    if not p.exists():
        raise FileNotFoundError(f"ontology '{name_or_path}' not found at {p}")
    return Ontology.model_validate(yaml.safe_load(p.read_text(encoding="utf-8")))


def load_market(name_or_path: str) -> Market:
    raw: dict[str, Any] = yaml.safe_load(market_path(name_or_path).read_text(encoding="utf-8"))

    ontology = load_ontology(raw.pop("ontology", DEFAULT_ONTOLOGY))

    # A market may narrow a region's register where its language genuinely moves the
    # distribution, and nothing else. Drivers, banks and pay psychology are platform
    # identity — allowing those to be overridden per market would fork the ontology
    # by the back door, which is the exact failure this shared file exists to prevent.
    overrides: dict[str, dict[str, Any]] = raw.pop("region_overrides", {}) or {}
    if overrides:
        known = set(ontology.region_ids)
        unknown = set(overrides) - known
        if unknown:
            raise ValueError(f"region_overrides names unknown regions: {sorted(unknown)}")
        allowed = {"register_mix"}
        for rid, patch in overrides.items():
            illegal = set(patch) - allowed
            if illegal:
                raise ValueError(
                    f"region_overrides['{rid}'] may only override {sorted(allowed)}; "
                    f"got {sorted(illegal)}. A region's drivers, banks and pay psychology "
                    f"are platform identity — change them in the shared ontology or not at all."
                )
        ontology = ontology.model_copy(
            update={
                "regions": [
                    r.model_copy(update=overrides[r.id]) if r.id in overrides else r
                    for r in ontology.regions
                ]
            }
        )

    raw["ontology"] = ontology
    return Market.model_validate(raw)


def list_markets() -> list[str]:
    """Playable markets. Files prefixed with ``_`` are shared fragments, not markets."""
    if not MARKETS_DIR.exists():
        return []
    return sorted(f.stem for f in MARKETS_DIR.glob("*.yaml") if not f.stem.startswith("_"))
