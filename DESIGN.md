# Design

Reference and rationale for Crowd (PocketSim). Read the README first — this is the layer under it.

## Persona synthesis

You have no personas and no logs. Inventing 300 listeners in a prompt produces a population nobody can defend and nobody can debug, so the pipeline runs on one rule:

> **Sample the numbers, generate the prose.**

The model never invents a numeric attribute. Every number a persona carries is drawn from a distribution declared in `markets/*.yaml`; the LLM only writes biography around that skeleton. That makes the population auditable (every number traces to a line a human can argue with), reproducible under a seed, and correctable when real data arrives.

| Layer | Where | What |
|---|---|---|
| 1 · Market definition | `markets/*.yaml` | Genres, money anchors, competitive alternatives, cities |
| 2a · Occasion cohorts | `markets/*.yaml` | 5–8 templates per market, as *distributions* not point values |
| 2b · Need regions | `markets/_ontology.yaml` | 6 regions, drivers and the hook/dealbreaker banks — shared across markets |
| 3 · Numeric sampling | `personas.py` | Seeded draws — reproducible and inspectable |
| 4 · Prose enrichment | `personas.py` | LLM writes biography, batched with name-collision avoidance |
| 5 · Diversity audit | `personas audit` | Fails loudly on mode collapse, on either axis |
| 6 · **Human validity gate** | `personas inspect` | Your content team confirms they recognise these people |

Layer 6 is not a formality. With no listening data there is no backtest, so the check that matters is whether the content team recognises these as real Pocket FM listeners. If they don't, nothing downstream is worth running.

### The two axes

Every persona is described twice, and the split is load-bearing:

| | **Occasion cohort** — `cohort_id` | **Need region** — `region_id` |
|---|---|---|
| Answers | *When and how do they listen?* | *What do they want a story to do for them?* |
| Owns | Session structure, tempo, gap decay, payment tier | Drivers, patience, commitment, register, hooks, dealbreakers |
| Determines | The **shape** of the retention curve | **Which stories** retain them |
| Declared in | Each market file — occasions are local | `markets/_ontology.yaml` — regions are platform-wide |
| Example | `gig-worker-marathon`, `domestic-daytime` | Justice-Payoff Bingers, Slow-Burn Comfort Seekers |

Neither subsumes the other. A gig worker on an eight-hour shift and a homemaker doing chores can both be Justice-Payoff listeners and will drop at the same narrative failure — at different points on the clock. Two people on the same commute can want opposite things from a story. One axis alone predicts the wrong half of the behaviour.

Each cohort declares a `region_mix` — the join. Given that someone listens *this* way, what do they want? That's hand-authored per market, which is why the same six regions come out weighted differently in Hindi (justice 27%, status 20%) and English (comfort 24%, tier-1 22%).

**A variable lives on exactly one axis.** Region never re-declares tempo, and touches willingness-to-pay only through a declared `pay_threshold_shift` on the cohort's base rate — pay *psychology* (which gate converts you) is a taste fact, pay *capacity* is an income fact. Without that rule the two axes grow synonym variables and the population starts double-counting itself.

Regions carry an **evidence tier** — `T-A` public evidence, `T-B` industry prior, `T-C` our own hypothesis — which travels all the way into the report, so a highly-ranked region on `T-C` evidence is visibly a hypothesis rather than a finding. Each region also declares a low-probability **anti-stereotype** slice; without it every member behaves like the region's centroid, and a population of six centroids produces a clean retention curve describing nobody.

Regions and banks live in one shared file that every market imports, so editing a region changes every market, every population and every report with no other edit.

Every cohort ships tagged `provisional: true`. When real behavioural data arrives, layer 2a is replaced by clusters discovered from session-length distributions, time-of-day histograms, inter-episode gaps, genre mix and coin-spend patterns. Layers 3–6 do not change.

## What gets measured

**The four primitives**, captured per persona per episode. Everything else is diagnostic colour.

| Primitive | Question |
|---|---|
| Continue / drop | Would you open the next episode? Why? |
| Pay / don't pay | If the paywall were here, would you spend coins? |
| Attention drop | At which beat did you check out? |
| Expectation | What do you think happens next? |

Continue and pay stay separate on purpose. Enjoyment and willingness-to-pay diverge constantly — people love stories they won't pay for, and pay for mediocre ones because they can't stand not knowing. Collapsing them into one "satisfaction" number destroys the signal that matters.

**The headline output is the Fix List:**

```
RevenueAtRisk(ep) = drop_rate(ep) × active_share(ep) × episodes_remaining(ep)
```

This answers the question the writers' room actually has — where do I spend limited rewrite time? A weak episode at 6, pre-paywall with everyone still listening, is a revenue emergency; the identical weakness at 18 is a nuisance. Raw drop rate can't tell them apart.

**Two metrics no analytics dashboard can produce**, because real listeners never tell you what they expected:

- **Prediction disagreement** — mean pairwise distance between what listeners think happens next. High craving with *low* disagreement means they already know what's coming and have no reason to hurry back; high craving with high disagreement is what a working cliffhanger looks like.
- **Craving delta** — `craving_end − craving_mid`. A satisfying, cleanly-resolved episode is a churn event on a serialized platform. This catches the episode that is *too well-resolved*, invisible to satisfaction ratings, needing a different fix from "boring."

**Episode flags** separate failure modes that need different fixes: `OVER_RESOLVED` (closed its own loop — end on the open question), `BORING` (needs stakes, not restructuring), `WORKING_HOOK`, `PREDICTABLE_BUT_WANTED` (fragile), `HIGH_DROP`.

**Trope fatigue** compares drop rates between long-tenure and new listeners. Veterans dropping where new users don't is a cliché signal, not a weak-writing signal — the beat works fine for someone hearing it first time. Different diagnosis, different reviewer.

**Cohort fit** ranks the six need regions for this script — the pre-launch targeting map. Published as a ranking, never a score: if the panel is uniformly miscalibrated the shares all move together and the ordering mostly does not, so the ordering is the part worth acting on. Each row carries the region's evidence tier and, where the beat map found one, the specific dealbreaker the script trips that is live for that region — a dealbreaker excluded for a region is not listed against it, because the same beat that loses one audience can be why another one stays.

**Filler** comes from the beat map: beats tagged as moving nothing and removable, ordered by the drop rate of the episode they sit in. Filler in an episode nobody leaves is a tidiness note; the same beat in a high-drop episode is a candidate for the drop itself.

`verdict.json` is checked before it is written: any field name that would assert a calibrated real-world prediction (`predicted_*`, `expected_retention`, …) fails the write. Panel-relative shares stay — they describe what this simulated panel did, which is a fact about the run.

## Providers

| | `openai-api` (default) | `codex-cli` | `mock` |
|---|---|---|---|
| Schema guarantee | Structured Outputs, `strict: true` | Best-effort + repair retry | Always valid |
| Cost | ~$15–30 per full run | Zero marginal | Zero |
| Speed | Async fan-out | Subprocess pool | Instant |

Use them for different jobs. The design rests on guaranteed-parseable reactions — a 3% failure rate across 4,000 calls is a silently biased curve — so production runs go through the API. Persona synthesis and smoke tests go through Codex CLI for free, which takes day-to-day iteration to roughly zero and leaves spend only on runs that produce a report. `mock` is deterministic and offline; it exists so the whole pipeline including the null test can be exercised with no key.

If your Codex CLI's non-interactive flags differ, override the invocation:

```bash
export POCKETSIM_CODEX_CMD="codex exec -c 'model_reasoning_effort=\"low\"' --skip-git-repo-check --ephemeral --ignore-rules --sandbox read-only --color never -"
```

**Cost control.** The Hindi script is fed verbatim in Devanagari (preserving register) but sits in the cached stable prefix, so its token weight is paid roughly once per episode instead of once per listener. Within each episode the first call is fired alone and awaited before the rest fan out — a cache entry only becomes readable once the response that created it starts returning, so firing all 300 at once means all 300 pay full price for the same prefix.

## Markets

`--market` is a real parameter, not decoration. Adding a market is adding a YAML file.

```bash
pocketsim markets
```

`india-hindi` (8 occasion cohorts) ships alongside `india-english` (5), and they are deliberately not translations of each other — different genre taxonomy, different competitive set, different price sensitivity, disjoint cohorts. Tamil or Telugu is a new file, no code change.

The six need regions are shared: a region is platform identity, not a market's local invention, so the same Justice-Payoff Bingers card describes that appetite everywhere. What each market contributes is the join — which regions its occasions draw from — and the resulting marginals differ sharply:

| Region | india-hindi | india-english |
|---|---:|---:|
| Justice-Payoff Bingers | 27% | 17% |
| Status-Progression Loyalists | 20% | 11% |
| Household-Catharsis Devotees | 16% | 7% |
| Slow-Burn Comfort Seekers | 14% | 24% |
| High-Churn Thrill Chasers | 13% | 20% |
| Tier-1 Aspirational Escapists | 10% | 22% |

A market may narrow a region's register where its language genuinely moves the distribution, and nothing else. Drivers, banks and pay psychology are not overridable — allowing that would fork the ontology by the back door, which is the failure the shared file exists to prevent.

## Verification

Run these before trusting any output.

```bash
# Same seed twice → identical audience (compare the reported fingerprints)
pocketsim personas build --market india-hindi --count 300 --seed 42 --out /tmp/a.json --provider mock

# Diversity audit — catches the default failure mode of LLM persona generation
pocketsim personas audit --population populations/ih-300.json
```

**The null test** — the most important check in the system:

```bash
pocketsim simulate --series naagin --population populations/ih-300.json --run-id nt-a
pocketsim simulate --series naagin --population populations/ih-300.json --run-id nt-b
pocketsim compare  --base nt-a --against nt-b
```

Same script, same audience, run twice — so nothing changed. Whatever this reports is the noise floor of your configuration. With `--provider mock` it is exactly zero. With a real model at non-zero temperature it will not be, and any rewrite delta smaller than that number is unproven. `compare` detects this case automatically and labels it.

Other guards, all enforced rather than documented:

- Comparing runs with different populations refuses to report a number and exits 2
- A population built for one market cannot be used to simulate another
- `personas build` exits 2 if the diversity audit fails
- Schema failures are counted and reported as a percentage — dropped from the dataset, so the curve is biased by exactly that much
- `runs/<run-id>/report/learning.md` records run setup, persona generation, validation checks, outcomes and automatic harness warnings

## Layout

```
markets/          india-hindi.yaml, india-english.yaml   ← occasion cohorts, per market
  _ontology.yaml  drivers · hook/dealbreaker banks · 6 need regions ← shared, imported
scripts/          raw .txt scripts
series/<name>/    episodes.json + beats.json             ← ingest output, reused across runs
populations/      generated audiences, versioned by seed
runs/<run_id>/
  manifest.json   what ran, against what, which population fingerprint
  input/          provenance copies
  reactions.jsonl written during the run — a crash at ep 17 of 20 leaves 17 usable
  report/         verdict.json · report.md · report.html
  logs/run.log
src/pocketsim/    cli · config · ingest · personas · llm · schema · simulate · metrics · report · store
```

`verdict.json` is the machine-readable surface — headline decisions, fix list, paywall curve, per-episode metrics, the occasion map, the ranked need-region cohort fit, and the filler beats.

## Not in v1

Audio-layer modelling (VO, pacing, sound design) is explicitly out of scope. Those are real retention drivers on an audio platform and the simulation cannot see any of them — worth saying out loud before anyone asks. Also deferred: word-of-mouth propagation between listeners, and a deep-dive tier that explains why an episode loses people in writer-actionable prose rather than just locating it.

**Deliberately not merged from the companion ontology docs.** The need regions, driver vocabulary, hook/dealbreaker banks and beat-table fields are in. These are not:

- **Story Genome (Module A)** — 18 scored dimensions, five trajectory curves and an embedding per story, at catalog scale. It's a genuinely separate engine and this repo has one script, not a catalog. Its spec, `story-genome-enrichment.md`, is cited as authoritative by the Story Intelligence doc and is not in this repo — that dependency is still dangling.
- **The full Episode Intelligence pipeline (B1–B8)** — we merged the B4 beat table and the parts of B3 the beat map can carry (bank hits, tripped dealbreakers). Narrative anatomy, the promise ledger, per-episode driver scoring with script citations, and the intervention/trade-off generator are not built.
- **US and Tamil/Telugu markets** — the source ontology weights US romance and Tamil/Telugu at 35% of its modelled population. Both are a new YAML file and no code change, but neither exists yet, and two of its six cards are majority-US.
- **`recommend_to_others` / `return`** — v2 in the source vocabulary too; there is no social layer or re-engagement model here.

Where the two documents disagree on market weights, this repo does not silently reconcile — `markets/india-hindi.yaml` records the deltas against the ontology's implied India marginal and why each one differs.