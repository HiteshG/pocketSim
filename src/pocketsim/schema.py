"""Data models and the strict JSON Schemas the model is forced to answer in.

Free-text reactions are not aggregatable. Every reaction is constrained with OpenAI
Structured Outputs (``strict: true``), so the model *cannot* return something the
metrics layer can't parse — a 3% failure rate across ~4,000 reactions would be a
silently biased retention curve, which is worse than a loud crash.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, get_args

from pydantic import BaseModel, Field

# ─────────────────────────────────────────────────────────────────────────────
# Personas
# ─────────────────────────────────────────────────────────────────────────────

PaymentTier = Literal["free", "occasional", "regular", "whale"]
SessionPattern = Literal["binge", "drip"]
Intensity = Literal["low", "med", "high"]
Register = Literal["pulp", "mid", "literary"]


class Persona(BaseModel):
    """One synthetic listener, described on two orthogonal axes.

    ``cohort_id`` is the listening occasion — when and how they listen. ``region_id`` is
    the need region — what they want a story to do for them. A gig worker and a homemaker
    can share a need region and drop at the same narrative failure at different points on
    the clock; two people on the same commute can want opposite things from a story. One
    axis alone predicts the wrong half of the behaviour.

    Numeric fields are sampled from distributions declared in YAML; prose fields are
    written by an LLM around that numeric skeleton. The split is deliberate — it keeps
    every number traceable to a stated assumption.
    """

    persona_id: str
    cohort_id: str
    region_id: str

    # Prose (LLM-generated)
    realname: str
    profession: str
    persona: str
    interested_topics: list[str] = Field(default_factory=list)

    # Sampled demographics
    age: int
    gender: str
    country: str = "IN"
    city: str
    city_tier: int

    # Sampled behaviour — owned by the occasion cohort (tempo and money)
    genre_affinity: dict[str, float]
    avg_daily_minutes: int
    session_minutes: float
    session_pattern: SessionPattern
    gap_hours: float
    coin_spend_tier: PaymentTier
    historical_completion: float
    churn_sensitivity: float
    pay_threshold: float
    tenure_months: int
    playback_speed: float
    listening_privacy: str

    interruption_load: float = 0.4
    """0-1: how often this listening situation gets broken into. A session that keeps
    getting interrupted is abandoned for reasons that have nothing to do with the script,
    which is a large share of real churn and was entirely unmodelled before."""

    discovery_channel: str = "browsing"
    """How they arrived at this series. An ad-acquired listener was promised something
    specific by a creative and churns when the episodes are not it; a friend-recommended
    listener extends more credit. Also the link back to UA spend."""

    # Sampled behaviour — owned by the need region (taste and tolerance)
    drivers: dict[str, Intensity] = Field(default_factory=dict)
    """2-3 psychological drivers from the frozen PRD §2.2 vocabulary, with intensity."""

    narrative_patience: float = 0.5
    """0-1. How long they will wait for a payoff before the waiting itself is the problem."""

    commitment_tolerance: int = 100
    """Episodes they can imagine committing to: 20, 100 or 500. Sets what a 'long' story is
    for this person, which is the difference between an epic and an ordeal."""

    exploration_propensity: float = 0.5
    """0-1. How readily they sample something new rather than staying with what works."""

    language_register: Register = "mid"

    mbti: str = "ISTJ"
    """Sampled from the declared population frequencies in the ontology.

    Conditions how this listener deliberates and speaks, and nothing else — no numeric
    axis is derived from it and no metric consumes it. Kept deliberately inert on the
    numbers because MBTI's predictive validity does not support carrying any."""

    anti_stereotype: str | None = None
    """Set on the declared low-probability slice of a region. Its job is preventing
    behavioural collapse, not being right: without it every member of a region behaves
    like its centroid, and a population of centroids yields a clean curve describing
    nobody."""

    provisional: bool = True

    @property
    def is_veteran(self) -> bool:
        """Long-tenure listeners carry trope fatigue — they drop on cliché where a new
        user tolerates it. Splitting drop-off by this is how you tell 'weak writing'
        from 'we've all heard this before', which are different fixes."""
        return self.tenure_months >= 18

    def top_genres(self, n: int = 3) -> list[str]:
        return [g for g, _ in sorted(self.genre_affinity.items(), key=lambda kv: -kv[1])[:n]]

    @property
    def primary_drivers(self) -> list[str]:
        """HIGH drivers first, then MED — the order this person would describe themselves in."""
        return [d for d, i in self.drivers.items() if i == "high"] + [
            d for d, i in self.drivers.items() if i == "med"
        ]


class Population(BaseModel):
    """A generated persona population. Saved once and reused across runs — `compare`
    is only meaningful if both runs used the *same* listeners."""

    market: str
    seed: int
    count: int
    generator_provider: str = ""
    generator_model: str
    created_at: str
    personas: list[Persona]

    def by_cohort(self) -> dict[str, list[Persona]]:
        out: dict[str, list[Persona]] = {}
        for p in self.personas:
            out.setdefault(p.cohort_id, []).append(p)
        return out

    def by_region(self) -> dict[str, list[Persona]]:
        out: dict[str, list[Persona]] = {}
        for p in self.personas:
            out.setdefault(p.region_id, []).append(p)
        return out

    @property
    def fingerprint(self) -> str:
        """Content hash over the personas alone, excluding generation metadata.

        Two builds with the same seed produce the same fingerprint even though their
        `created_at` differs. Recorded in every run manifest so `compare` can refuse to
        diff two runs that heard the story with different audiences — a delta across
        different populations measures the audience, not the rewrite.
        """
        blob = json.dumps(
            [p.model_dump(mode="json") for p in self.personas], sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────────────
# Per-listener carried state
# ─────────────────────────────────────────────────────────────────────────────


class ListenerState(BaseModel):
    """What this listener carries into the next episode.

    Per-persona rather than global on purpose: different listeners remember different
    things, and that divergence is itself signal.
    """

    persona_id: str
    episodes_heard: int = 0
    active: bool = True
    dropped_at: int | None = None
    story_summary: str = ""
    character_sentiment: dict[str, float] = Field(default_factory=dict)
    unresolved_questions: list[str] = Field(default_factory=list)
    coins_spent: int = 0
    paid_episodes: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Reactions
# ─────────────────────────────────────────────────────────────────────────────


class Reaction(BaseModel):
    """One listener's decision at one episode boundary."""

    will_continue: bool
    continue_reason: str
    switch_to: str | None = None
    would_pay: bool
    pay_reason: str
    drop_beat: str | None = None
    craving_mid: int = Field(ge=1, le=10)
    craving_end: int = Field(ge=1, le=10)
    next_prediction: str
    emotional_state: str
    memory_update: str = ""
    """One line the listener would still remember tomorrow. Feeds the rolling summary."""

    @property
    def craving_delta(self) -> int:
        """End-of-episode need-to-know minus mid-episode. A *negative* delta on an
        otherwise-liked episode is the over-resolution signature: the story closed its
        own loop, which on a serialized platform is a churn event."""
        return self.craving_end - self.craving_mid


def strict_schema(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Wrap a raw JSON Schema in OpenAI's ``response_format`` envelope with strict mode."""
    return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}


REACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "will_continue": {
            "type": "boolean",
            "description": "True if you would play the next episode now rather than switch away.",
        },
        "continue_reason": {
            "type": "string",
            "description": "One or two sentences, in your own voice, on why.",
        },
        "switch_to": {
            "type": ["string", "null"],
            "description": "If you would switch away, what you'd play or do instead. Null if continuing.",
        },
        "would_pay": {
            "type": "boolean",
            "description": "If the next episode were locked behind coins right now, would you spend?",
        },
        "pay_reason": {"type": "string"},
        "drop_beat": {
            "type": ["string", "null"],
            "description": "The beat_id where your attention drifted, or null if it held throughout.",
        },
        # The anchors are repeated here, next to the point of generation, because stating
        # them only in the system prompt did not bind: across two live runs of ~400
        # reactions the mode was exactly 7 both times (56% then 62%) and the range never
        # opened past 4-9. The model was emitting a fixed "engaged" prior rather than
        # reading the scale, and a scale nobody reads cannot detect an over-resolved
        # episode, which is the one failure mode craving exists to catch.
        "craving_mid": {
            "type": "integer",
            "minimum": 1,
            "maximum": 10,
            "description": (
                "How badly you needed to know what happens next, MIDWAY through. "
                "1-2 do not care · 3-4 mild curiosity · 5-6 can wait days · "
                "7-8 want it soon · 9-10 cannot stop. Ordinary competent episodes are 3-6. "
                "Do not default to the middle."
            ),
        },
        "craving_end": {
            "type": "integer",
            "minimum": 1,
            "maximum": 10,
            "description": (
                "How badly you need to know what happens next, at the END. Same anchors: "
                "1-2 do not care · 3-4 mild curiosity · 5-6 can wait days · 7-8 want it soon · "
                "9-10 cannot stop. If this episode resolved its tension, this must be LOW even "
                "if you enjoyed it. Reserve 8+ for a genuine cliffhanger — most episodes are not."
            ),
        },
        "next_prediction": {
            "type": "string",
            "description": "What you think happens next. Be specific and commit to a guess.",
        },
        "emotional_state": {
            "type": "string",
            "description": "Two or three words for how this episode left you feeling.",
        },
        "memory_update": {
            "type": "string",
            "description": "The one thing from this episode you'd still remember tomorrow.",
        },
    },
    "required": [
        "will_continue",
        "continue_reason",
        "switch_to",
        "would_pay",
        "pay_reason",
        "drop_beat",
        "craving_mid",
        "craving_end",
        "next_prediction",
        "emotional_state",
        "memory_update",
    ],
    "additionalProperties": False,
}

REACTION_RESPONSE_FORMAT = strict_schema("listener_reaction", REACTION_SCHEMA)


# ─────────────────────────────────────────────────────────────────────────────
# Ingest: beat mapping
# ─────────────────────────────────────────────────────────────────────────────


BeatPurpose = Literal["reveal", "escalate", "reverse", "complicate", "payoff", "none"]
ChurnRisk = Literal["none", "boredom", "confusion", "dealbreaker"]


class Beat(BaseModel):
    """One unit of dramatic movement, with the structural read the reports need.

    The extra fields beyond ``title``/``summary`` are the Episode Intelligence beat table:
    they let a drop be diagnosed rather than merely located. Knowing listeners left at
    beat 4 is a fact; knowing beat 4 is a `purpose: none` beat they could have skipped, or
    that it trips dealbreaker D3, is a fix.

    ``churn_risk`` and ``dealbreaker_id`` are split rather than encoded as one
    `"dealbreaker:D3"` string, because a strict enum the model cannot spell wrong is worth
    more than compactness.
    """

    beat_id: str
    title: str
    summary: str

    purpose: BeatPurpose = "none"
    emotional_intensity: int = Field(default=5, ge=1, le=10)
    suspense: int = Field(default=5, ge=1, le=10)
    churn_risk: ChurnRisk = "none"
    dealbreaker_id: str | None = None
    """Bank ID when ``churn_risk`` is ``dealbreaker``. Names which listeners are at risk,
    since a dealbreaker is only live for the regions whose tags it matches."""

    hooks_hit: list[str] = Field(default_factory=list)
    removable: bool = False
    """``purpose: none`` and ``removable`` together are the filler detector."""

    @property
    def is_filler(self) -> bool:
        return self.purpose == "none" and self.removable


class EpisodeBeats(BaseModel):
    beats: list[Beat]


def beats_schema(hook_ids: list[str], dealbreaker_ids: list[str]) -> dict[str, Any]:
    """Build the beat schema with this ontology's bank IDs baked into the enums.

    Generated rather than declared so the banks stay imported from YAML — a hook added
    there becomes citable here with no edit, and the model cannot cite an ID that does
    not exist, which is the cheapest available guard against confabulated evidence.
    """
    return {
        "type": "object",
        "properties": {
            "beats": {
                "type": "array",
                "description": "5-10 sequential story beats covering the whole episode.",
                "items": {
                    "type": "object",
                    "properties": {
                        "beat_id": {
                            "type": "string",
                            "description": "Short stable slug, e.g. 'b3-wedding-confrontation'.",
                        },
                        "title": {"type": "string", "description": "3-6 word English label."},
                        "summary": {"type": "string", "description": "One English sentence."},
                        "purpose": {
                            "type": "string",
                            "enum": list(get_args(BeatPurpose)),
                            "description": (
                                "What this beat does to the story. 'none' means it moves "
                                "nothing — do not reach for a purpose that is not there."
                            ),
                        },
                        "emotional_intensity": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10,
                            "description": "Relative to the other beats in this episode.",
                        },
                        "suspense": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10,
                            "description": "How much is unresolved and pressing at this beat.",
                        },
                        "churn_risk": {
                            "type": "string",
                            "enum": list(get_args(ChurnRisk)),
                            "description": (
                                "'boredom' if nothing is at stake, 'confusion' if the listener "
                                "cannot follow, 'dealbreaker' if it trips a listed dealbreaker."
                            ),
                        },
                        "dealbreaker_id": {
                            "type": ["string", "null"],
                            "enum": [*dealbreaker_ids, None],
                            "description": "The dealbreaker ID tripped, or null. Only when churn_risk is 'dealbreaker'.",
                        },
                        "hooks_hit": {
                            "type": "array",
                            "items": {"type": "string", "enum": hook_ids},
                            "description": "Hook IDs this beat lands, or an empty array. Do not stretch.",
                        },
                        "removable": {
                            "type": "boolean",
                            "description": "True if cutting this beat would cost the episode nothing.",
                        },
                    },
                    "required": [
                        "beat_id",
                        "title",
                        "summary",
                        "purpose",
                        "emotional_intensity",
                        "suspense",
                        "churn_risk",
                        "dealbreaker_id",
                        "hooks_hit",
                        "removable",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["beats"],
        "additionalProperties": False,
    }


def beats_response_format(hook_ids: list[str], dealbreaker_ids: list[str]) -> dict[str, Any]:
    return strict_schema("episode_beats", beats_schema(hook_ids, dealbreaker_ids))


# ─────────────────────────────────────────────────────────────────────────────
# Persona synthesis: biographical enrichment
# ─────────────────────────────────────────────────────────────────────────────


class PersonaProse(BaseModel):
    index: int
    realname: str
    profession: str
    persona: str
    interested_topics: list[str]


class PersonaProseBatch(BaseModel):
    people: list[PersonaProse]


PERSONA_PROSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "people": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {
                        "type": "integer",
                        "description": "The index of the skeleton you are writing for.",
                    },
                    "realname": {"type": "string"},
                    "profession": {
                        "type": "string",
                        "description": "Specific job title, not a category.",
                    },
                    "persona": {
                        "type": "string",
                        "description": (
                            "3-5 sentences in English: who they are, when and how they listen, "
                            "what device and data situation they're in, what else competes for "
                            "the same time slot, and what they grew up watching or listening to."
                        ),
                    },
                    "interested_topics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "3-5 short interest tags.",
                    },
                },
                "required": ["index", "realname", "profession", "persona", "interested_topics"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["people"],
    "additionalProperties": False,
}

PERSONA_PROSE_RESPONSE_FORMAT = strict_schema("persona_prose_batch", PERSONA_PROSE_SCHEMA)
