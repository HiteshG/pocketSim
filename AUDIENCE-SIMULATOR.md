# Audience Simulator — Technical & Product Specification

**For:** Pocket FM
**Status:** Draft v1 — pre-build spec
**Date:** 2026-07-25

---

## Contents

1. [Thesis](#1-thesis)
2. [Scope](#2-scope)
3. [The value model — what to extract and why](#3-the-value-model)
4. [Data model](#4-data-model)
5. [Framework evaluation](#5-framework-evaluation)
6. [Recommended architecture](#6-recommended-architecture)
7. [Implementation plan](#7-implementation-plan)
8. [Cost model](#8-cost-model)
9. [Validation — the backtest](#9-validation--the-backtest)
10. [Risks and mitigations](#10-risks-and-mitigations)
11. [Appendix: sources](#11-appendix-sources)

---

## 1. Thesis

Most "AI audience simulator" concepts produce **opinions**. Pocket FM does not monetize opinions. It monetizes one behaviour:

> Did the listener open the next episode, and did they spend coins to do it?

Therefore the reaction primitive this system captures must be **behavioural and episode-indexed**, not evaluative. "8,000 simulated users rated this 4.2/5" is a vanity number. "Episode 14 loses 22% of the Tier-2 male revenge-fantasy cohort at the 4-minute mark, and the rewrite recovers 9 points" is a production decision.

The second half of the thesis is the part that is genuinely defensible:

> Real user data tells you what happened. Simulation tells you what *would have* happened.

You cannot A/B test a story in reality — you release it once. Counterfactuals are the only thing simulation gives you that analytics cannot, and they are the reason the tool has a permanent place in the pipeline rather than being a one-off experiment.

---

## 2. Scope

### In scope

- Ingest a serialized audio-fiction story, episode by episode.
- Instantiate N synthetic listeners with cohort-realistic profiles.
- Run each listener through the episode sequence, capturing a structured behavioural decision at every boundary.
- Aggregate into retention, willingness-to-pay, attention-drop, and suspense metrics.
- Support **re-simulation** of edited episodes to produce counterfactual deltas.
- Optionally model word-of-mouth propagation between listeners.

### Out of scope (v1)

- Audio/VO simulation. Text scripts only. (Prosody, voice-actor fit, and sound design are real retention factors and belong in v2.)
- Absolute retention prediction. See §10.
- Real user data integration beyond persona fitting.

### Non-goals

- Replacing the editorial team. This is a triage and prioritisation instrument.
- Producing a "quality score." Quality is not the unit of value; continuation is.

---

## 3. The value model

### 3.1 The four extraction primitives

Captured **per persona, per episode**. Everything else is diagnostic colour.

| # | Primitive | Question asked | Type |
|---|---|---|---|
| 1 | **Continue / drop** | Would you open the next episode? Why? | boolean + reason |
| 2 | **Pay / don't pay** | If the paywall were here, would you spend coins? | boolean + reason |
| 3 | **Attention drop** | At which beat did you check out? | beat ref \| null |
| 4 | **Expectation** | What do you think happens next? | free text |

Critically, **(1) and (2) diverge constantly.** Enjoyment and willingness-to-pay are different functions. A listener can love an episode and refuse to pay; a listener can find an episode mediocre and pay because the cliffhanger is unbearable. Collapsing them into one "satisfaction" number destroys the signal that matters.

### 3.2 Roll-ups and the business decision each one moves

| Roll-up | Built from | Pocket FM decision it moves | Owner |
|---|---|---|---|
| **Simulated retention curve** | #1 across episodes | Kill / greenlight at script stage instead of after 60 episodes of production spend | Content |
| **Paywall placement** | #1 × #2 | Revenue-maximising gate episode — currently heuristic, tuned over weeks of live data | Monetisation |
| **Drop-off surgery** | #3 | Which beats in which episodes to rewrite | Writers' room |
| **Segment–story fit** | #1 sliced by cohort | Pre-launch ad targeting map — lands on the largest cost line | Marketing / UA |
| **Hook ranking** | #1 on ep.1 only | Which of 20 opening variants ships (and becomes the ad creative) | Content + Marketing |

**Why the economics compound.** Pocket FM's model is: paid acquisition → free episodes → paywall → coin spend across 100+ episodes. Every point on the retention curve is multiplied by every subsequent episode's monetisation. A 3-point improvement at episode 10 propagates through the entire tail. This is why script-stage intervention beats post-launch optimisation.

**Why segment–story fit lands on the P&L.** Tier-2 Indian male listeners on revenge / system-progression fantasy behave nothing like US female listeners on billionaire romance. A pre-launch cohort fit map means UA spend is targeted before a rupee is burned on users who churn before they ever pay. Mistargeted CAC is the most expensive form of waste in this business.

### 3.3 Two non-obvious metrics

These are the ones that make the pitch memorable, because no analytics dashboard can produce them — real users never tell you what they expected.

**Prediction entropy.** Ask every persona what happens next. Compute the variance of their predictions.

- Low entropy + high stakes → predictable. Predictable is the death of the next-episode open.
- High entropy + high stakes → a working cliffhanger.

This is a **quantitative suspense metric**. It cannot be derived from behavioural logs.

**Craving delta.** Measure "need to know" at the episode boundary minus mid-episode.

```
craving_delta = craving_at_end − craving_at_midpoint
```

That gap — not enjoyment — predicts the next tap. A satisfying, cleanly-resolved episode is a **churn event** on a serialized platform. This metric catches the episode that is *too well-resolved*, a failure mode completely invisible to satisfaction ratings.

---

## 4. Data model

### 4.1 Persona schema

Adapted from the OASIS profile schema, extended with Pocket FM behavioural attributes. Fields marked ★ should be **fitted from real cohort logs**, not invented — that is the moat (see §9).

```json
{
  "persona_id": "pf_00123",
  "realname": "Rakesh Kumar",
  "age": 27,
  "gender": "male",
  "country": "IN",
  "city_tier": 2,
  "profession": "Delivery partner",
  "persona": "Listens during 2-hour daily commute. Grew up on mythological serials...",
  "interested_topics": ["revenge", "system-progression", "mythology"],

  "genre_affinity":        { "revenge": 0.9, "romance": 0.2, "thriller": 0.6 },
  "avg_daily_minutes":     78,
  "coin_spend_tier":       "medium",
  "historical_completion": 0.34,
  "churn_sensitivity":     0.7,
  "pay_threshold":         0.55
}
```

★ = `genre_affinity`, `avg_daily_minutes`, `coin_spend_tier`, `historical_completion`, `churn_sensitivity`, `pay_threshold`

### 4.2 Reaction schema (schema-enforced output)

Free-text responses are not aggregatable. Every reaction is constrained to this JSON Schema via the Claude API's `output_config.format`, so the model **cannot** return an unparseable response.

```json
{
  "type": "object",
  "properties": {
    "will_continue":     { "type": "boolean" },
    "continue_reason":   { "type": "string" },
    "would_pay":         { "type": "boolean" },
    "pay_reason":        { "type": "string" },
    "drop_beat":         { "type": ["string", "null"] },
    "craving_mid":       { "type": "integer" },
    "craving_end":       { "type": "integer" },
    "next_prediction":   { "type": "string" },
    "emotional_state":   { "type": "string" }
  },
  "required": [
    "will_continue", "continue_reason", "would_pay", "pay_reason",
    "drop_beat", "craving_mid", "craving_end", "next_prediction",
    "emotional_state"
  ],
  "additionalProperties": false
}
```

`craving_mid` / `craving_end` on a 1–10 scale. `drop_beat` is a beat identifier from the episode's beat map, or `null` if the persona stayed engaged throughout.

### 4.3 Persistent state per persona

Carried forward across episodes so the agent is a *listener following a story*, not a fresh reader of episode N.

```json
{
  "persona_id": "pf_00123",
  "episodes_heard": 14,
  "active": true,
  "dropped_at": null,
  "story_summary": "Rolling 400-token summary of what this listener remembers...",
  "character_sentiment": { "Arjun": 0.8, "Meera": -0.3 },
  "unresolved_questions": ["Who killed the father?", "Is Meera the traitor?"],
  "coins_spent": 240
}
```

The rolling `story_summary` is per-persona, not global — different listeners remember different things, and that divergence is part of the signal.

### 4.4 Storage

SQLite for v1 (single file, zero ops, queryable). Three tables:

- `personas` — the population
- `reactions` — one row per (persona_id, episode_no, run_id)
- `runs` — metadata: story version, model, effort, timestamp

`run_id` is what makes counterfactuals work: the original and the rewrite are two runs over the same population, diffed on `episode_no`.

---

## 5. Framework evaluation

### 5.1 The framing that determines the answer

All five candidate repos are **social network simulators** — agents in a shared world, talking to each other, content propagating through a graph.

That is not the shape of this problem.

The required primitive is a **longitudinal panel study**: N independent listeners each consume a fixed sequence, emitting a structured decision at every boundary. Agent-to-agent interaction is *optional* — it only matters for word-of-mouth and virality modelling.

This mismatch is why none of them drop in. The question is which one's machinery is worth keeping.

### 5.2 Scorecard

| Repo | Core primitive | Scale | Persona model | Metric extraction | License | Adapt effort |
|---|---|---|---|---|---|---|
| **camel-ai/OASIS** | Twitter/Reddit feed + recsys | 1M agents (validated) | Rich JSON schema | `INTERVIEW` action → SQLite `trace` | Apache-2.0 | **Medium** |
| **DeepMind/Concordia** | Game Master narrative sim | ~4–20 agents | Deepest (components, assoc. memory) | None — build it | Apache-2.0 | High (scale is the blocker) |
| **AgentSociety** | Urban society + mobility | ~10k agents | Needs / emotion / cognition | **Survey + interview + intervention + metric recorder built in** | Apache-2.0 | Very high (infra tax) |
| **666ghj/MiroFish** | Ingest → persona-gen → OASIS → report | Inherits OASIS | Auto-generated from source docs | Narrative report | **AGPL-3.0** | Medium, licence risk |
| **amadad/mirofish-cli** | English CLI fork of above | Inherits OASIS | Same | `verdict.json` + confidence | **AGPL-3.0** | Low — demos only |

### 5.3 camel-ai/OASIS — the best engine to build on

Three things it provides that are genuinely expensive to rebuild:

**1. The persona schema is already right.** `realname, username, bio, persona, age, gender, mbti, country, profession, interested_topics` maps almost one-to-one onto Pocket FM cohort attributes. Extend with the ★ fields in §4.1 and you have a listener profile.

**2. `ActionType.INTERVIEW` is exactly the extraction primitive.**

```python
ManualAction(action_type=ActionType.INTERVIEW,
             action_args={"prompt": "..."})
```

Prompt and response land in the `trace` table as JSON, keyed by `user_id` and timestamp. That is a queryable per-agent, per-episode instrument with zero plumbing.

**3. Published cost model at scale.** 100 agents × 1 step ≈ 336k input / 17k output tokens; ~¥0.03 on Qwen-plus, ~¥0.72 on Qwen-max. It is the only repo here that publishes real cost figures — necessary because "5,000 agents × 60 episodes" needs a rupee number attached in the deck.

**Required modifications:**

| # | Change | Why |
|---|---|---|
| 1 | **Bypass the recsys** | The interest-based / hot-score recommender decides which agents see which posts. Episode delivery must be *deterministic* — every active agent gets episode N. Push via `ManualAction(CREATE_POST)` from a publisher agent, or patch `recsys.py` to force-deliver. |
| 2 | **Add a `drop` state** | OASIS has no concept of an agent leaving. Needs a flag removing the agent from the active set on churn, so the retention curve is monotonic and cost falls as the cohort thins. |
| 3 | **Force structured output** | Constrain interview responses to the §4.2 schema. Free text is not aggregatable. |
| 4 | **Fix memory horizon** | Agent memory is social-media-scoped, not "I've followed this story for 40 episodes." Add the §4.3 rolling state. |

Realistically 1–2 weeks to a working v1. **Fork it — don't `pip install`** — since `recsys.py` and the agent lifecycle both need patching.

### 5.4 DeepMind/Concordia — right depth, wrong tier

The Game Master architecture is the best available model of *a mind encountering a situation*: situation assessment → identity → contextual action, with associative memory. For answering **why** episode 14 loses people, it produces far better reasoning than a one-shot rating.

But it is built for four friends in a snowed-in pub. Every agent-step is a chain of LLM calls (observe, summarize, retrieve, deliberate, act) — roughly 10–50× the per-agent cost of a single-call harness. Thousands of agents × 60 episodes is not viable. There is also no population generator, no metrics layer, and no DB output.

**Use it as tier 2.** The wide scan tells you *where* the curve breaks; 20 Concordia agents through episodes 12–16 tell you *why*, in language a writer can act on. Two tiers is also a stronger pitch than one — cheap wide scan, expensive deep read.

### 5.5 AgentSociety — steal the methodology, skip the framework

Best research instrumentation of the five: **interviews, surveys, interventions, and metric recording** as first-class utilities, plus AVRO/PostgreSQL storage and ~10k agents at ~500 interactions/day. The `intervention` primitive is precisely the rewrite-and-resimulate counterfactual, already designed.

The cost is infrastructure: Ray, an MQTT broker, PostgreSQL, and a heritage of urban mobility simulation that would be 90% deleted. v2's `SimpleSocialSpace` softens this, but you would still pay a distributed-systems tax on a problem that is embarrassingly parallel over independent agents.

**Copy the survey/metric API design. Do not adopt the runtime.**

### 5.6 666ghj/MiroFish — closest analogue, licence blocker

An application layer on OASIS: seed documents → GraphRAG knowledge graph → entity extraction → auto-generated personas → dual-platform simulation → ReportAgent → chat with the simulated agents. Hit #1 on GitHub trending in early 2026 with 30k+ stars, backed by Shanda Group.

Their showcase demo is **feeding the first 80 chapters of *Dream of the Red Chamber* to predict how the story ends** — this exact use case, minus the business instrumentation.

Two blockers:

- **AGPL-3.0.** If Pocket FM runs this as an internal tool exposed over a network, the AGPL network clause is a legal conversation, not an engineering one. Flag before anyone gets attached.
- **Wrong output.** MiroFish predicts *what happens in the world*. We need to predict *whether the listener taps next episode*. The plumbing is right; the metric is absent.

**Real value:** it proves the pipeline shape works, and gives a credible reference point in the room — *"MiroFish showed a swarm can reason about narrative causality; we're pointing that at retention and coin spend."*

### 5.7 amadad/mirofish-cli — this week's demo

English fork, CLI-first, runs on `claude-cli` / `codex-cli` subscriptions rather than metered API keys, emits a machine-readable `verdict.json` with confidence scores plus SVG timelines and cluster maps.

Same AGPL constraint. The provider restriction that makes it cheap for a demo makes it unusable for a 5,000-agent production run.

**Use it as a probe, not a foundation.** Point it at the first five episodes tonight to get a concrete artifact in the deck by Monday.

---

## 6. Recommended architecture

### 6.1 The honest recommendation

Two components, and the split matters:

```
┌──────────────────────────────────────────────────────────────┐
│  BESPOKE CORE LOOP  (required — ~300 lines)                   │
│  Independent panel study. Fully parallel, schema-enforced.    │
│  Produces: retention, pay curve, drop-beat map, entropy.      │
└──────────────────────────────────────────────────────────────┘
                              +
┌──────────────────────────────────────────────────────────────┐
│  OASIS SOCIAL LAYER  (optional — buy it only if you need WOM) │
│  Word-of-mouth propagation, review dynamics, virality.        │
└──────────────────────────────────────────────────────────────┘
```

The core loop is roughly this:

```python
for persona in personas:
    state = init_state(persona)
    for episode in episodes:
        reaction = await llm(
            model="claude-opus-5",
            system=[{"type": "text",
                     "text": EPISODE_PROMPT(episode),          # cached prefix
                     "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
            messages=[{"role": "user",
                       "content": persona_block(persona, state)}],
            output_config={"format": {"type": "json_schema",
                                      "schema": REACTION_SCHEMA}},
        )
        state = update(state, reaction)
        record(run_id, persona.id, episode.no, reaction)
        if not reaction.will_continue:
            state.active = False
            break
```

A few hundred lines. Fully parallel, schema-enforced, no recsys to fight, no AGPL, full control over every token.

**OASIS earns its place only when you want the social layer.** Word-of-mouth propagation, review dynamics, a hit spreading through a cohort — those are real Pocket FM questions, and they are the reason to start from the fork rather than a blank file. But go in knowing you are buying the social graph and the persona/interview scaffolding, **not** the simulation loop. If you find yourself deleting the feed, the recsys, and the follow graph, stop and write the 300 lines.

### 6.2 Full pipeline

```
  Episode corpus ────┐
  (per-episode text, │
   beat-mapped)      │
                     ▼
  Persona population ──▶  DELIVERY LOOP  ──▶  INSTRUMENT  ──▶  STORE  ──▶  AGGREGATE
  (OASIS schema,          deterministic,        schema-           SQLite       retention curve
   fitted from            recsys bypassed,      constrained                    pay curve
   cohort logs)           attrition-aware       JSON                           drop-beat heatmap
                                                                               prediction entropy
                                                                               craving delta
                                                                               cohort fit map
                              │
                              ├──▶  TIER 2: Concordia deep-dive on worst 3 episodes
                              └──▶  OPTIONAL: OASIS social graph for WOM propagation
```

### 6.3 Model and API decisions

| Decision | Choice | Rationale |
|---|---|---|
| Model | `claude-opus-5` | Default. Best reasoning-per-token for persona simulation. Model tier is the single largest cost lever if you need to trade down — see §8. |
| Thinking | `{"type": "adaptive"}` | On by default on Opus 5. Persona reasoning benefits from it. |
| Effort | `output_config: {"effort": "medium"}` | Sweep `low`/`medium`/`high` on a 200-agent pilot. `low` and `medium` are unusually strong on Opus 5 — this is the second-largest cost lever. |
| Output | `output_config.format` json_schema | Non-negotiable. Guarantees parseable, aggregatable reactions. |
| Caching | Episode text as cached system prefix, 1h TTL | Episode is identical across all N agents. Largest single cost saving. See §8. |
| Batching | Message Batches API | 50% off all token usage. Simulation is not latency-sensitive. |

**Cache placement detail.** Render order is `tools → system → messages`. Put the **episode text + instructions** in `system` with `cache_control` (identical across all agents for a given episode) and the **persona + state** in `messages` (varies per agent). Cache-by-episode beats cache-by-persona because the episode block (~2,400 tokens) is far larger than the persona block (~200).

**Concurrency detail.** A cache entry only becomes readable once the first response begins streaming. Fire **one** request per episode, await first token, then fan out the remaining N−1 — otherwise all N pay full price.

---

## 7. Implementation plan

| Phase | Duration | Deliverable | Exit criterion |
|---|---|---|---|
| **0. Probe** | 2 days | Run `mirofish-cli` on episodes 1–5. Produce a `verdict.json` artifact for the deck. | A concrete artifact exists, not a described capability. |
| **1. Core loop** | 1 week | Bespoke harness: 200 personas × 10 episodes, schema-enforced, SQLite output. | Retention curve renders. Costs are measured, not estimated. |
| **2. Effort + cache sweep** | 2 days | Sweep effort `low`/`medium`/`high`; verify `cache_read_input_tokens` > 0. | Cost per agent-episode is known to ±15%. |
| **3. Persona fitting** | 1 week | Replace invented personas with cohorts fitted from Pocket FM listening logs. | Cohort distribution matches real platform distribution. |
| **4. Backtest** | 1 week | Blind-simulate 20 library shows with known retention. Report rank correlation. | Spearman ρ reported. This is the go/no-go gate. |
| **5. Scale + counterfactual** | 1 week | 5,000 personas × 60 episodes. Rewrite ep. N, re-run, report delta. | Two `run_id`s diffable on `episode_no`. |
| **6. Tier 2 (optional)** | 1 week | Concordia deep-dive on the three worst episodes. | Writer-actionable prose explanation of one drop. |
| **7. Social layer (optional)** | 2 weeks | OASIS fork with WOM propagation on top of the core loop. | Virality coefficient per cohort. |

**Critical path is Phase 4.** Everything before it is speculation; everything after it is instrumentation. Do not scale before backtesting.

---

## 8. Cost model

### 8.1 Token assumptions per agent-episode

| Component | Tokens | Cacheable? |
|---|---:|---|
| Episode text (~1,800 words) | 2,400 | ✅ shared across all agents |
| Instructions + schema | 500 | ✅ shared |
| Persona block | 200 | ❌ per-agent |
| Rolling story state | 400 | ❌ per-agent |
| **Input total** | **3,500** | 2,900 cacheable / 600 not |
| Output (structured JSON) | 250 | — |

### 8.2 Volume

5,000 personas × 60 episodes, with attrition. Assuming average active-cohort fraction of ~0.35 across the run:

```
agent-episodes ≈ 5,000 × 60 × 0.35 ≈ 105,000
```

### 8.3 Cost per full run (Claude Opus 5 — $5 / $25 per MTok)

| Configuration | Input cost | Output cost | **Total** |
|---|---:|---:|---:|
| Naive (no caching, no batch) | $1,838 | $656 | **~$2,490** |
| + prompt caching (episode prefix, 1h TTL) | $469 | $656 | **~$1,125** |
| + Message Batches API (50% off) | $234 | $328 | **~$560** |

Caching maths: uncached input 105,000 × 600 = 63M tok @ $5/M = $315. Cached reads 105,000 × 2,900 = 304.5M tok @ $0.50/M (0.1×) = $152. Cache writes 60 × 2,900 = 174k tok @ $10/M (2× for 1h TTL) = ~$2. Total input ≈ $469.

### 8.4 Model tier comparison (with caching + batch)

| Model | Input / Output per MTok | Full-run cost | Note |
|---|---|---:|---|
| **Claude Opus 5** | $5 / $25 | **~$560** | Recommended default |
| Claude Sonnet 5 | $3 / $15 ($2/$10 intro thru 2026-08-31) | ~$340 (~$225 intro) | Viable for the wide scan if pilot quality holds |
| Claude Haiku 4.5 | $1 / $5 | ~$115 | Too shallow for persona reasoning — not recommended |

**Recommendation:** run Opus 5 by default. Model tier and effort level are the two cost levers available if the budget forces a trade; validate any downgrade against the Phase 4 backtest before adopting it, because the whole instrument's credibility rests on rank correlation surviving.

### 8.5 Cost per decision

At ~$560 per full run, a hook test of 20 episode-1 variants against 5,000 personas costs roughly **$9** (one episode, no attrition, 20 variants). This is the cheapest, highest-frequency use case and the obvious wedge to demo.

Sixty episodes of production — writer, VO, sound design, QA — is a materially larger number than $560. That ratio is the pitch.

---

## 9. Validation — the backtest

**This is the single most important section for the pitch.** It converts the idea from speculation into a measurable instrument.

### 9.1 Protocol

1. Request **20 shows from the existing Pocket FM library** with known, complete retention curves.
2. Withhold all outcome data from the simulation team.
3. Simulate each blind, using cohort-fitted personas.
4. Report **Spearman rank correlation** between simulated and actual retention at episodes 5, 10, 20, 40.

### 9.2 Why rank correlation, not absolute accuracy

LLM personas are systematically miscalibrated in ways that are well documented and will be raised in the room:

- They are agreeable.
- They over-engage.
- They do not get bored.
- They almost never spontaneously say "I'm dropping this."

Pitching *"we predict 41% retention at episode 20"* will get correctly torn apart. Pitching **rankings and deltas** — *"Story A will out-retain Story B," "this rewrite improves episode 14 by X relative to the original"* — survives persona miscalibration, because the bias applies roughly uniformly across comparisons and cancels in the difference.

**Report levels only after calibration against the backtest**, as a fitted transform of the simulated score, never as a raw model output.

### 9.3 The moat argument

Personas should be **fitted from real cohort behaviour logs**, not invented from imagination. This is the defensibility claim:

> Anyone can prompt personas. Only Pocket FM can calibrate them against millions of real listening sessions.

This is also the natural bridge to the story-genome work — the fitted persona population is a reusable asset that gets more accurate with every show released.

---

## 10. Risks and mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| **Persona miscalibration** — agents over-engage, never drop | High | Report rankings and deltas, not levels. Calibrate against the Phase 4 backtest. Explicitly prompt for drop permission and reward honest churn in the schema. |
| **Backtest fails** (low rank correlation) | High | This is the go/no-go gate, deliberately placed before scale spend. If ρ is weak, the failure costs one week, not a quarter. |
| **AGPL contamination** from MiroFish forks | Medium | Use MiroFish/mirofish-cli as reference and demo only. Build production on Apache-2.0 OASIS or bespoke. Get legal sign-off before any AGPL code enters the internal tree. |
| **Text-only ≠ audio** — VO, pacing, sound design drive real retention | Medium | Scope explicitly to script-stage triage in v1. Position audio modelling as v2. Do not claim the simulation captures performance quality. |
| **Cost overrun at scale** | Low | Caching + batch reduces a naive run by ~78%. Effort sweep is a further lever. Verify `cache_read_input_tokens > 0` in Phase 2 — a silent cache invalidator (a timestamp or per-request ID in the cached prefix) is the usual cause of a surprise bill. |
| **Overfitting to the backtest set** | Medium | Hold out 5 of the 20 shows. Report correlation on the held-out set separately. |
| **Organisational rejection** — "AI can't judge stories" | Medium | Do not position as a judge. Position as a triage instrument that tells writers *where* to look. The writer keeps the decision. |

---

## 11. Appendix: sources

| Repo / doc | URL |
|---|---|
| camel-ai/OASIS | https://github.com/camel-ai/oasis |
| OASIS documentation | https://docs.oasis.camel-ai.org/introduction |
| OASIS interview cookbook | https://docs.oasis.camel-ai.org/cookbooks/twitter_interview |
| OASIS paper | https://arxiv.org/abs/2411.11581 |
| google-deepmind/concordia | https://github.com/google-deepmind/concordia |
| tsinghua-fib-lab/AgentSociety | https://github.com/tsinghua-fib-lab/AgentSociety |
| AgentSociety paper | https://arxiv.org/html/2502.08691v1 |
| 666ghj/MiroFish | https://github.com/666ghj/MiroFish |
| amadad/mirofish-cli | https://github.com/amadad/mirofish-cli |
| MiroFish showcase | https://sosamonbot-coder.github.io/mirofish-showcase/ |

**Claude API references** (pricing and features as of 2026-07-25):

- Claude Opus 5 — `claude-opus-5` — $5 / $25 per MTok, 1M context, 128K max output
- Claude Sonnet 5 — `claude-sonnet-5` — $3 / $15 per MTok ($2 / $10 introductory through 2026-08-31)
- Prompt caching — cache reads ~0.1× input price; writes 1.25× (5-min TTL) or 2× (1-hour TTL)
- Message Batches API — 50% discount on all token usage
- Structured outputs — `output_config.format` with `json_schema`
