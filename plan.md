# PocketSim — India/Hindi Audience Simulator

**Build plan · v1 · greenfield**

---

## Context

Pocket FM commits writer, VO, and production spend across 60–100 episodes before it learns whether a story retains. The curve is discovered after the money is spent, and a story ships once — so there is no counterfactual, ever.

`pocketsim` runs a **synthetic listener panel** over a script before production: N personas consume episodes in sequence, each emitting a structured behavioural decision at every boundary, rolling up into a ranked list of which episodes to fix, where to gate, and which cohort the story is actually for.

| Constraint | Consequence |
|---|---|
| **No personas, no listening data.** 1–2 Hindi scripts, 20 eps, `.txt` with `Episode N` headers | Persona synthesis is a first-class subsystem, not a setup step — see §3. No backtest possible; v1 makes **relative claims only** (§8) |
| **OpenAI API key + Codex CLI** | Two providers behind one interface: API for guaranteed-schema production runs, Codex CLI for zero-marginal-cost iteration (§5) |
| **All reasoning and output in English** | Auditable by the whole team. Hindi script fed verbatim; only reasoning is English |
| Market must be a runtime parameter | `--market india-hindi` today; `india-english` by adding one YAML file |

---

## 0. How you actually use it

The mental model is **running a focus-group screening**. Each command is one step of that.

| Command | Plain English | When | Cost |
|---|---|---|---|
| `ingest` | **Prepare the script.** Reads the `.txt`, splits at `Episode N` headers, tags 5–10 named story beats per episode so a persona saying *"I zoned out at the wedding scene"* points at something specific. | Once per script | ~$0.50 |
| `personas` | **Hire the test audience.** Generates 300 synthetic listeners — names, jobs, commutes, spending habits. Saved to a file. | Once, reused forever | Free (Codex) |
| `simulate` | **Hold the screening.** Plays the story to every persona, episode by episode. Each answers: continue or drop, pay or not, where they checked out, what they expect next. ~4,000 raw reaction records. | Per script version | ~$30 |
| `report` | **Write up what happened.** Turns raw reactions into the retention curve, Fix List, paywall recommendation, cohort map, drop-beat heatmap. | As often as you like | Free |
| `compare` | **Diff two screenings.** You rewrote episode 7 — did it work, and by how much? Same personas, both versions. | After a rewrite | Free |
| `history` | Housekeeping — what's been simulated, is this one running, export raw data. | Whenever | Free |

**Why `simulate` and `report` are separate.** Simulating is slow and costs money; reporting is instant and free. You simulate a script once and re-report it fifty times as you add metrics or slice by a different cohort. Merged, every tweak to a chart would cost another $30.

**Why the persona file is saved and reused.** `compare` is the highest-value command, and it only works if both runs used the *same* 300 listeners. Then when numbers move you know the script changed, not the audience. That is the counterfactual — unobtainable from real listeners, because a story ships once.

A full session, end to end:

```bash
pocketsim ingest    --script scripts/naagin.txt --series naagin --market india-hindi
pocketsim personas  build --market india-hindi --count 300 --seed 42 --out populations/ih-300.json
pocketsim simulate  --series naagin --population populations/ih-300.json --run-id naagin-v1
pocketsim report    --run naagin-v1 --format html          # → "episode 7 is your problem"
#   ... writer rewrites episode 7 → scripts/naagin-v2.txt ...
pocketsim ingest    --script scripts/naagin-v2.txt --series naagin-v2 --market india-hindi
pocketsim simulate  --series naagin-v2 --population populations/ih-300.json --run-id naagin-v2
pocketsim compare   --base naagin-v1 --against naagin-v2   # → "ep 7 recovered 9 points"
```

---

## 1. The value model

### The four extraction primitives

Captured **per persona, per episode**. Everything else is diagnostic colour.

| # | Primitive | Question asked | Type |
|---|---|---|---|
| 1 | **Continue / drop** | Would you open the next episode? Why? | boolean + reason |
| 2 | **Pay / don't pay** | If the paywall were here, would you spend coins? | boolean + reason |
| 3 | **Attention drop** | At which beat did you check out? | beat ref \| null |
| 4 | **Expectation** | What do you think happens next? | free text |

**Why 1 and 2 must stay separate.** Enjoyment and willingness-to-pay diverge constantly. A listener can love an episode and refuse to pay; a listener can find an episode mediocre and pay because the cliffhanger is unbearable. Collapsing them into one "satisfaction" number destroys the signal that matters.

### Roll-ups and the decisions they move

| Roll-up | Built from | Decision it moves | Owner |
|---|---|---|---|
| Simulated retention curve | #1 across episodes | Kill / greenlight at script stage instead of after 60 episodes of production spend | Content |
| Paywall placement | #1 × #2 | Revenue-maximising gate episode — currently heuristic, tuned over weeks of live data | Monetisation |
| Drop-off surgery | #3 | Which beats in which episodes to rewrite | Writers' room |
| Segment–story fit | #1 by cohort | Pre-launch ad targeting map — lands on the largest cost line | Marketing / UA |
| Hook ranking | #1 on ep. 1 only | Which of 20 opening variants ships (and becomes the ad creative) | Content + Marketing |

**Why the economics compound.** Pocket FM's model is paid acquisition → free episodes → paywall → coin spend across 100+ episodes. Every point on the retention curve is multiplied by every subsequent episode's monetisation. A 3-point improvement at episode 10 propagates through the entire tail. This is why script-stage intervention beats post-launch optimisation.

**Why segment–story fit lands on the P&L.** Tier-2 male listeners on revenge / system-progression behave nothing like other segments. A pre-launch cohort fit map means UA spend is targeted before a rupee is burned on users who churn before they ever pay. Mistargeted CAC is the most expensive waste in this business.

### Two non-obvious metrics

No analytics dashboard can produce these — real users never tell you what they expected.

**Prediction entropy.** Ask every persona what happens next, then compute the variance of their predictions. Low entropy plus high stakes means the story is predictable — and predictable is the death of the next-episode open. High entropy plus high stakes is a working cliffhanger. A **quantitative suspense metric**, underivable from behavioural logs.

**Craving delta.** `craving_delta = craving_at_end − craving_at_midpoint`. That gap — not enjoyment — predicts the next tap. A satisfying, cleanly-resolved episode is a **churn event** on a serialized platform. This catches the episode that is *too well-resolved*: a failure mode invisible to satisfaction ratings.

---

## 2. Data model

### Persona schema

Adapted from the OASIS profile schema, extended with Pocket FM behavioural attributes. ★ fields would normally be fitted from real cohort logs; with no logs they are **sampled from declared archetype distributions** (§3) and tagged `provisional`.

```json
{
  "persona_id": "pf_00123",
  "realname": "Rakesh Kumar",
  "age": 27,
  "gender": "male",
  "country": "IN",
  "city": "Indore",
  "city_tier": 2,
  "profession": "Delivery partner",
  "persona": "Listens during 8-hour delivery shifts, one earbud in. Grew up on
              mythological serials on TV...",
  "interested_topics": ["revenge", "system-progression", "mythology"],

  "cohort_id":             "gig-worker-marathon",       // axis 1 — when they listen
  "region_id":             "justice-payoff-bingers",    // axis 2 — what they want
  "drivers":               { "justice_seeking": "high", // ★ frozen §2.2 vocabulary
                             "power_fantasy": "high",
                             "escapism": "med" },
  "narrative_patience":    0.31,                         // ★
  "commitment_tolerance":  500,                          // ★ episodes
  "exploration_propensity":0.42,                         // ★
  "language_register":     "pulp",                       // ★
  "anti_stereotype":       null,                         // declared low-probability slice
  "genre_affinity":        { "badla": 0.9, "romance": 0.2 },   // ★
  "avg_daily_minutes":     78,                                  // ★
  "coin_spend_tier":       "medium",                            // ★
  "historical_completion": 0.34,                                // ★
  "churn_sensitivity":     0.7,                                 // ★
  "pay_threshold":         0.55,                                // ★
  "session_pattern":       "binge",                             // ★
  "gap_hours":             19,                                  // ★
  "tenure_months":         7,                                   // ★
  "playback_speed":        1.5,
  "listening_privacy":     "private_earbud",
  "provisional":           true
}
```

Additions beyond the original schema, each earning its place: `cohort_id` and `region_id` (so every roll-up can be sliced on either axis), `session_pattern` + `gap_hours` (drive the forgetting step, §5), `tenure_months` (trope-fatigue signal), `listening_privacy` (bold content and visible transactions behave differently on a shared phone), and the need-region block (§3 layer 2b) that decides which beats land and which ones lose this listener.

### Reaction schema — enforced, not requested

Free-text responses are not aggregatable. Every reaction is constrained via **OpenAI Structured Outputs with `strict: true`**, so the model *cannot* return an unparseable response.

```python
response_format = {
  "type": "json_schema",
  "json_schema": {
    "name": "listener_reaction",
    "strict": True,
    "schema": {
      "type": "object",
      "properties": {
        "will_continue":   { "type": "boolean" },
        "continue_reason": { "type": "string"  },
        "switch_to":       { "type": ["string", "null"] },
        "would_pay":       { "type": "boolean" },
        "pay_reason":      { "type": "string"  },
        "drop_beat":       { "type": ["string", "null"] },
        "craving_mid":     { "type": "integer" },   // 1-10
        "craving_end":     { "type": "integer" },   // 1-10
        "next_prediction": { "type": "string"  },
        "emotional_state": { "type": "string"  }
      },
      "required": ["will_continue","continue_reason","switch_to","would_pay",
                   "pay_reason","drop_beat","craving_mid","craving_end",
                   "next_prediction","emotional_state"],
      "additionalProperties": False
    }
  }
}
```

`strict: true` requires every property listed in `required` and `additionalProperties: false` — a 3% parse-failure rate across ~4,000 reactions would be a silently biased curve.

One addition: **`switch_to`** — what they'd play instead. It exists because the continuation question is framed as opportunity cost rather than evaluation (§5), and the answer is independently useful: it's a map of what Pocket FM is actually losing listeners to.

### Persistent state per persona

Carried across episodes so the agent is a *listener following a story*, not a fresh reader of episode N. The rolling summary is per-persona — different listeners remember different things, and that divergence is part of the signal.

```json
{
  "persona_id": "pf_00123",
  "episodes_heard": 14,
  "active": true,
  "dropped_at": null,
  "story_summary": "Rolling ~400-token summary of what this listener remembers...",
  "character_sentiment": { "Arjun": 0.8, "Meera": -0.3 },
  "unresolved_questions": ["Who killed the father?", "Is Meera the traitor?"],
  "coins_spent": 240
}
```

### Storage

SQLite for v1 — single file, zero ops, queryable — with a mirrored `reactions.jsonl` for streaming writes and crash recovery. Four tables: `personas`, `reactions` (one row per persona × episode × run), `runs` (script version, market, model, seed, timestamp), `episodes` (text hash + beat map).

`run_id` is what makes counterfactuals work: the original and the rewrite are two runs over the **same population**, diffed on `episode_no`.

---

## 3. Persona synthesis — the centerpiece

You have no personas and no logs. Inventing 300 listeners in a prompt produces a population nobody can defend and nobody can debug. The pipeline below makes every number traceable to a declared assumption.

**Governing principle: sample the numbers, generate the prose.** The LLM never invents a numeric attribute — it writes biography around a numeric skeleton drawn from declared distributions. This is what makes the population auditable, reproducible under a seed, and correctable when real data arrives.

### Layer 1 — Market definition (`markets/india-hindi.yaml`, hand-authored)

Genre taxonomy, money anchors (`"a coin pack ≈ two cups of chai"`), city-tier distribution, competitive alternatives, language register.

### Layer 2a — Occasion cohorts (8, hand-authored, distributions not point values)

```yaml
cohorts:
  - id: gig-worker-marathon
    weight: 0.18
    occasion: "delivery rider, 8-10hr shift, one earbud, phone in pocket"
    session_pattern: binge
    session_minutes:  { dist: lognormal,   median: 95, sigma: 0.5 }
    gap_hours:        { dist: normal,      mean: 20,   sd: 6 }
    tenure_months:    { dist: exponential, mean: 7 }
    payment_mix:      { free: 0.55, occasional: 0.32, regular: 0.11, whale: 0.02 }
    genre_priors:     { badla: 0.8, system_progression: 0.6, horror: 0.5, saas_bahu: 0.2 }
    city_tier_mix:    { 1: 0.3, 2: 0.5, 3: 0.2 }
    listening_privacy: private_earbud
    provisional: true
```

Starting eight, chosen so the primary axes are **listening occasion** (determines session structure, therefore the *shape* of the retention curve) and **payment tier** (calibrates `would_pay`, therefore paywall placement). Demographics are descriptive, not defining:

`commute-binger` · `gig-worker-marathon` · `domestic-daytime` · `night-winddown` · `student-breaks` · `veteran-whale` · `new-curious` · `tier1-multitasker`

### Layer 2b — Need regions (6, shared across markets, `markets/_ontology.yaml`)

Merged from Behavioural Population Ontology v1.0. Occasion says *when* someone listens; a need region says *what they want a story to do for them*. Neither subsumes the other — a gig worker and a homemaker can share a need region and drop at the same narrative failure at different points on the clock.

`Justice-Payoff Bingers` · `Status-Progression Loyalists` · `Household-Catharsis Devotees` · `Slow-Burn Comfort Seekers` · `Tier-1 Aspirational Escapists` · `High-Churn Thrill Chasers`

Each region declares 2–3 drivers from the frozen ten-term vocabulary, distributions for `narrative_patience` and `exploration_propensity`, mixes for commitment (20/100/500 episodes) and register (pulp↔literary), a `pay_threshold_shift`, references into the 15+15 hook/dealbreaker banks, an evidence tier, and a low-probability anti-stereotype slice.

Two rules make the second axis pay for itself rather than inflate the schema:

1. **A variable lives on exactly one axis.** The source ontology's `binge_speed` and `listening_context` are not reproduced — the occasion cohort already carries them. Region touches willingness-to-pay only through a declared shift on the cohort's base. Anything else creates synonym variables that double-count.
2. **Regions are imported, never restated.** One shared file, referenced by `ontology: _ontology`. Markets contribute only the join (`region_mix` per cohort) and may narrow a region's register. Editing a card changes every market with no other edit.

Incoherent combinations (a 20-episode commitment inside a 500-episode region; near-zero patience with a literary register) are rejected and resampled. Rare-but-coherent ones are the opposite case and are preserved deliberately.

### Layer 3 — Numeric sampling

Seeded RNG draws each persona's numeric attributes from its archetype's distributions. Reproducible, inspectable, and explainable to anyone who asks where a number came from.

### Layer 4 — LLM biographical enrichment

Given the numeric skeleton, an LLM writes the prose fields: `realname`, specific `profession`, the `persona` narrative, listening context detail. Generated in batches of ~20 with explicit diversity instructions and prior-batch names in context — otherwise you get 300 delivery riders named Rakesh in Indore.

### Layer 5 — Automated diversity audit

`pocketsim personas audit` checks name-collision rate, profession entropy, city spread, gender balance within archetype, and genre-affinity distribution against the declared prior. Fails loudly on mode collapse.

### Layer 6 — Human validity gate

The content team reads a sample and confirms they recognise them as real Pocket FM listeners. **With no data, this is the v1 validity gate** — it substitutes for the backtest. If they don't recognise the personas, nothing downstream is worth running.

### When data arrives

Layer 2 archetypes are replaced by clusters discovered from behavioural feature vectors (session-length distribution, time-of-day histogram, inter-episode gaps, genre mix, completion by depth, coin-spend pattern); layers 3–6 are unchanged and `provisional` flips to `false`. **The architecture does not change** — only the source of the distributions.

---

## 4. Codebase decision — evidence, not assertion

I read the repos' actual usage rather than their READMEs. Two findings decided it.

**Finding 1 — OASIS's own interview path bypasses its social engine.** `SocialAgent.perform_interview(interview_prompt)` does *not* call `env.to_text_prompt()`. It takes the persona system message, truncates at `"# RESPONSE METHOD"`, appends the question, calls `_aget_model_response()`, and writes to the trace table. Feed, recsys, and the 23-action space never execute. That is exactly our panel primitive — and OASIS reaches *around* its own engine to provide it. The coupling lives in `perform_action_by_llm`, which we'd never call. Adopting it means carrying CAMEL + platform + channel + recsys for a loop we never run, a `ChatAgent` memory model that isn't our bounded rolling state, and an unverified structured-output path.

**Finding 2 — mirofish-cli runs for us, and is still the wrong base.** Its config accepts `LLM_PROVIDER` of only `claude-cli` or `codex-cli` — and we have Codex CLI, so it will start. The question is therefore real rather than moot, and the answer is architectural, not a licence or provider block.

Its pipeline is *ingest → knowledge graph + persona generation → social simulation over rounds → report*. Two of those four stages are wrong for us **in kind, not degree**:

- Its personas are generated from **entities in the source document** — the story's characters. We need an *audience* model, which is the opposite direction: personas that exist independently of the script and are reused unchanged across scripts, or paired comparison is impossible.
- Its simulation is agents posting and replying across Twitter/Reddit over N rounds. We need a sequential panel carrying per-listener state across 20 episodes with attrition. There is no round structure and no social graph in our loop.

Adopting it means keeping ingest and the CLI shell — roughly 20% — and rewriting the core inside someone else's architecture, while inheriting a knowledge-graph stage we never use. **We copy its CLI surface and run-artifact layout, which are genuinely the best pattern available, and skip the engine.**

### Decision: bespoke core (~900 LOC) built on their patterns

| Repo | Taken | Left |
|---|---|---|
| **OASIS** | Persona→system-message wiring; interview-as-primitive; flat JSON persona schema; SQLite trace | CAMEL chain, platform/channel/recsys, `env.step()`, ChatAgent memory |
| **mirofish-cli** | `run` / `runs list\|status\|export`; per-run artifact dir; `verdict.json` + `report.md`; `--json` stdout; the codex-cli subprocess adapter pattern | Knowledge-graph stage, document-entity persona generation, round-based social engine |
| **Concordia** | Deferred — tier-2 deep-dive post-v1 | Everything for now |
| **AgentSociety** | Intervention API *shape* for rewrite-and-compare | Ray, MQTT, Postgres |

Forking OASIS is ~8 days and leaves us owning a large fork forever. Bespoke is ~7 days and we own 900 lines.

---

## 5. Architecture

```
pocketfm-sim/
  markets/india-hindi.yaml, india-english.yaml
  scripts/naagin.txt
  populations/ih-300.json
  runs/<run_id>/
    manifest.json
    input/     episodes.json, beats.json, population.json, config.json
    reactions.jsonl
    report/    verdict.json, report.md, report.html, learning.md
    logs/run.log
  src/pocketsim/
    cli.py  config.py  ingest.py  personas.py  llm.py
    schema.py  simulate.py  metrics.py  report.py  store.py
```

### CLI

```bash
pocketsim ingest    --script scripts/naagin.txt --series naagin --market india-hindi
pocketsim personas  build   --market india-hindi --count 300 --seed 42 --out populations/ih-300.json
pocketsim personas  audit   --population populations/ih-300.json
pocketsim personas  inspect --population populations/ih-300.json --cohort gig-worker-marathon -n 5
pocketsim simulate  --series naagin --population populations/ih-300.json --run-id naagin-base
pocketsim report    --run naagin-base --format html
pocketsim compare   --base naagin-base --against naagin-rewrite
pocketsim history   list | status <id> | export <id>
```

Named `simulate` / `history` rather than mirofish-cli's `run` / `runs` — two commands differing by one letter while doing unrelated things is a readability trap.

Common options live on the commands that need them today: `--market`, `--model`,
`--provider`, `--concurrency`, `--limit-episodes`, `--seed`. `--batch`,
`--dry-run` and `--json` are follow-up CLI polish, not implemented v1 flags.

### Core loop

```python
for persona in population:
    state = init_state(persona)
    for ep in episodes:
        if persona.session_pattern == "drip":
            state = decay(state, persona.gap_hours)      # 24h of forgetting
        reaction = llm.react(
            stable_prefix = EPISODE_BLOCK(ep) + BEATS(ep) + INSTRUCTIONS,  # cached
            variable      = persona_block(persona) + state_block(state),
            response_format = STRICT_REACTION_SCHEMA,
        )
        state = update(state, reaction)
        append_jsonl(run_id, persona.id, ep.no, reaction)
        if not reaction.will_continue:
            state.active = False; break
```

**Three prompt-design decisions:**

1. **Opportunity-cost framing.** Not *"would you continue?"* (invites politeness) but *"You have 40 minutes of commute left — play the next episode, or switch to something else?"* This is how the decision actually happens, and it materially reduces the agreeableness bias that makes LLM personas refuse to churn. `switch_to` captures the answer.
2. **Local-relative money anchor.** An LLM reasoning about "₹49" abstractly misjudges; given *"about what you'd spend on two cups of chai"* it reasons sensibly.
3. **Session-gap decay.** A binge listener's episode boundary is barely a decision point; a drip listener has 24 hours of forgetting first. Decaying the rolling state tests whether the cliffhanger survives a night's sleep.

### Providers — two backends, one interface

`llm.py` exposes `react()` and `generate()`. Both providers implement it; `--provider` selects.

| | `openai-api` (default) | `codex-cli` |
|---|---|---|
| Schema guarantee | **`strict: true` Structured Outputs — cannot return unparseable JSON** | Best-effort parse + repair-retry |
| Cost | ~$30/run (below) | **Zero marginal** (subscription) |
| Throughput | Async fan-out + Batch API | Subprocess pool, process spawn per call |
| Caching | Automatic prefix cache, 90% off | Not controllable |

**Use both, for different jobs.** The whole design rests on guaranteed-parseable reactions — a 3% failure rate across 4,000 calls is a silently biased curve — so **production simulation runs go through the API**. But persona synthesis (§3 layer 4) is a one-off ~300 prose-generation calls where schema strictness matters far less, and smoke tests are cheap and frequent. **Both go through Codex CLI for free.** That takes the day-to-day iteration cost to roughly zero and leaves spend only on runs that produce a report.

The `codex-cli` adapter is the one piece of mirofish-cli worth studying directly — it already solves non-interactive subprocess driving of exactly this CLI.

### Cost

The Hindi script is fed **verbatim in Devanagari** (preserves register) but sits in the **cached stable prefix**, so its token weight is paid roughly once per episode instead of 300 times — full fidelity, near-zero marginal cost.

300 personas × 20 episodes ≈ 3,600 agent-episodes, via `openai-api`:

| Model | Rate in/out per 1M | Est. run | With Batch (−50%) |
|---|---|---:|---:|
| GPT-5.5 | $5.00 / $30.00 (cached in $0.50) | ~$60 | ~$30 |
| GPT-5.4 | $2.50 / $15.00 (cached in $0.25) | ~$30 | ~$15 |

Persona generation via `codex-cli`: **$0**. Caveat to measure not assume: OpenAI's cache has a ~30-min minimum life and Batch runs async over hours, so the two discounts may not fully stack — log `usage.cached_tokens` from stage 4 and let the numbers decide.

---

## 6. Metrics and combined insights

### Headline — the Fix List

```
RevenueAtRisk(ep) = drop_rate(ep) × active_share(ep) × monetisable_episodes_remaining(ep)
```

Episodes ranked by this answers the question the writers' room actually has: **where do I spend limited rewrite time?** A weak episode at 6 (pre-gate, full cohort live) is a revenue emergency; the identical weakness at 18 is a nuisance. Raw drop rate can't tell them apart.

### Combined insights

- **Cliffhanger Quadrant** (entropy × `craving_end`): high/high = working hook; low entropy + high craving = they know what's coming and want it anyway (fine, fragile); low/low = dead episode.
- **Over-Resolution Flag** (`craving_delta` ≪ 0 + elevated drop): you closed the loop too cleanly. Invisible to satisfaction ratings, and a completely different fix from "boring."
- **Boring vs Resolved** (`craving_mid` × drop): low throughout = add stakes; high mid, collapsed at end = end on the open loop.
- **Trope Fatigue** (tenure × drop): veterans dropping where new users don't means cliché, not weak writing. Different fix, different reviewer.
- **Beat × Cohort**: a beat weak for one segment only is a targeting decision, not a rewrite.
- **Switch-To Map** (`switch_to` aggregated): what you're actually losing listeners to.

---

## 7. Build stages

| # | Stage | Exit criterion | Est. |
|---|---|---|---|
| 0 | Scaffold — pyproject, typer skeleton, market YAML w/ 8 archetypes | `pocketsim --help` runs; YAML validates | 0.5d |
| 1 | Ingest — `.txt` → episodes (regex on `Episode N`) → LLM beat-map | `episodes.json` + `beats.json` for the real script; 5–10 named beats each | 0.5d |
| 2 | **Persona synthesis** — layers 1–5, generated via `codex-cli` (free) | 300 personas; audit passes; `--seed 42` twice is byte-identical; population audit artifacts written beside the JSON | **1.5d** |
| 3 | **Human gate** — content team reviews a sample | Team confirms they recognise them as real listeners | 0.5d |
| 4 | LLM layer — both adapters + strict schema + smoke (10 personas × 3 eps) | Zero schema violations on `openai-api`; `codex-cli` parses with repair-retry; OpenAI usage shows `cached_tokens > 0` by ep 2 | 1.5d |
| 5 | Full loop — state carry, gap decay, attrition, JSONL + SQLite | 300 × 20 completes; cost measured not estimated | 1d |
| 6 | Metrics + report — Fix List, all roll-ups, md + html + verdict.json + learning.md | Report opens; Fix List reproducible by hand for the top episode; run learning notes record persona generation, validation, outcomes and harness warnings | 1.5d |
| 7 | Compare — paired base vs rewrite | Per-episode delta with paired variance reduction | 0.5d |
| 8 | Calibration stub — `pocketsim calibrate` reads a retention CSV | Runs on synthetic input; documented for when data lands | 0.5d |

**~7 days.** Stage 3 is a genuine gate, not a formality.

---

## 8. What v1 can and cannot claim

Load-bearing. With no data there is no calibration and no backtest; overstating this is the fastest way to get the project dismissed.

**Supported:** within-story episode ranking · paired rewrite deltas · cross-script ranking · drop-beat localisation · cohort divergence (directional).

**Not supported:** absolute retention percentages · validated paywall episodes · any claim of predictive accuracy.

Reports therefore read *"episode 7 is the weakest in this script; the rewrite recovers X points in paired simulation"* — never *"predicted retention: 34%."* Once a benchmark library exists it becomes percentile framing against the catalogue. Both survive persona miscalibration; the absolute number would not.

---

## 9. Verification

```bash
pocketsim ingest   --script scripts/script1.txt --series script1 --market india-hindi
pocketsim personas build --market india-hindi --count 25 --seed 42 \
                   --provider mock --out populations/script1-25.json
pocketsim personas audit --population populations/script1-25.json
pocketsim personas inspect --population populations/script1-25.json -n 5
pocketsim simulate --series script1 --population populations/script1-25.json \
                   --run-id script1-smoke --provider mock
pocketsim report   --run script1-smoke --format html
```

- **Ingest** — episode count matches headers; every episode has 5–10 named beats.
- **Personas** — cohort weights match YAML within tolerance; same seed twice is byte-identical; audit passes; `populations/*.audit.md` explains generation and validation.
- **Smoke** — zero schema violations across the smoke reactions; for `openai-api`, `cached_tokens > 0` by episode 2.
- **Full run** — retention monotonic; no persona reacts after `will_continue: false`.
- **Report** — Fix List ordering reproducible from `reactions.jsonl` by hand for the top episode; `runs/<id>/report/learning.md` logs run setup, persona validation, outcomes and harness warnings.
- **Null test** — compare a script against *itself* as the "rewrite"; the delta must be indistinguishable from zero. **If a script differs from itself, the simulation is noise and nothing else in the output is trustworthy.**
- **Market parameter** — `--market india-english` loads the other YAML and produces different cohorts, proving the parameter is real rather than decorative.
- **Provider parity** — the same 10-persona × 3-episode smoke run under `--provider codex-cli` and `--provider openai-api` produces reactions in the same schema, and aggregate drop rates within noise of each other. If they diverge materially, the free path can't be trusted for iteration and everything moves to the API.

---

## 10. Follow-ups (not v1)

`pocketsim calibrate` against 20–30 real retention curves → unlocks absolute claims and percentile framing · Concordia tier-2 deep-dive on the three worst episodes → *why*, in writer-actionable prose · OASIS social layer for word-of-mouth → virality coefficient per cohort · Tamil/Telugu markets (new YAML, no code change) · audio-layer modelling (VO, pacing, sound design), explicitly out of v1 and worth saying out loud before anyone asks.

**Note on prior docs:** `AUDIENCE-SIMULATOR.md` and `audience-simulator.html` assume Anthropic models and a data-rich cohort-fitting path. On approval I'll update both for OpenAI, the revised cost model, and the no-data posture, so the repo doesn't carry two contradicting specs.
