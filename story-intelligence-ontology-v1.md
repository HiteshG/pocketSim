# Story Intelligence Ontology v1.0 (locked)
### Canonical specification for machine-readable stories — the companion to Behavioural Population Ontology v1.0
### Consumed by: Taste Engine · Audience Simulator · Evaluation Suite · Creator View · Editorial Gap Analysis
### Plug-and-play rule: this doc + behavioural-population-ontology-v1.md + story-genome-enrichment.md are the complete inputs; nothing is hardcoded elsewhere.

---

## 0. Platform Contract

**Purpose:** every story on the platform becomes machine-readable at two resolutions. Story Intelligence does not judge literary quality; it extracts behavioural metadata that predicts and explains listener decisions.

**Two modules, one vocabulary:**

| | **Module A — Story Genome** | **Module B — Episode Intelligence** |
|---|---|---|
| Input | public synopsis + metadata | full episode script + series state |
| Resolution | whole story | scene/beat |
| Scale | entire catalog (100–300) | selected scripts (demo: 1–2) |
| Primary consumers | Taste Engine retrieval, cohort-fit, Simulator story context | Creator View, Simulator beat-mapped ingestion, editorial interventions |
| Spec | `story-genome-enrichment.md` (authoritative; summarized in §2) | §3 of this document |

**Hackathon honesty:** Module A runs at catalog scale this weekend. Module B is the creator-side module (P5: Cliffhanger Optimizer / script triage) demoed on sample scripts — it is NOT a replacement for the genome and is never wired in as the Taste Engine's story representation.

**Decisions this ontology powers:** which story a listener sees (A) · why listeners churn and where (A curves + B beats) · which cohort a story/episode serves (A+B cohort-fit) · localization candidates (A, language-agnostic vectors) · script-stage editorial fixes (B interventions) · paywall/cliffhanger strategy (B, Simulator roadmap).

**Interface authority:** PRD §2 governs all shared fields. Needs vocabulary, event vocabulary, and cohort regions are IMPORTED from the Behavioural Population Ontology at runtime — never restated, never hardcoded. If the cards change after the evidence pass, this engine inherits the change with zero edits.

---

## 1. Global rules (apply to both modules)

1. **Vocabulary lock:** psychological drivers = PRD §2.2 ten-term vocabulary only. Hooks/dealbreakers referenced by Block D bank IDs only. Outcomes = canonical vocabulary (start/continue/pay/finish/abandon; recommend/return v2).
2. **Rankings, not levels:** absolute retention/completion/click percentages are BANNED as outputs. All predictions are ordinal (cohort rankings, severity tiers, relative comparisons, directional deltas). The only numbers permitted are internal scores explicitly framed as relative (genome dims, beat intensities, craving points).
3. **Anti-confabulation:** never invent plot events, characters, or episode numbers absent from the input. Module A phrases drop-off risk as structural inference. Module B cites the script verbatim-adjacent for every claim; promise histories come only from the supplied series state, never from memory.
4. **Confidence handling:** thin/ambiguous input → `confidence: low` + `confidence_note`, conservative free text. Never fabricate certainty. Canonical uncertainty answer per the Behavioural Ontology §1.
5. **Structured outputs:** every call schema-enforced via `output_config.format`. Prose-only responses are a build error.
6. **Assumption labeling:** any rubric weight or heuristic not derived from evidence carries `[T-C]`.

---

## 2. Module A — Story Genome (summary; authoritative spec in story-genome-enrichment.md)

Per story: 18 anchored scored dimensions (relative to all serialized fiction; variance gate ≥1.5) · 5 trajectory curves (10-pt arrays: emotional intensity, suspense, romance, power progression, pacing) · narrative_needs_served (2–4, §2.2 vocab) · trope tags · free text (relationship_dynamics, notable_arcs, listener_fit, drop_off_risk) · confidence · context-fit flags. One embedding per story.

**A-outputs added by this ontology (v1.1 of the genome pipeline):**

**A1 — Story-level Cohort-Fit Vector (required).** For every genome, a ranked fit against every cohort region imported from the Behavioural Ontology §4. Computed by LLM reasoning over: drivers × cohort primary drivers · trope tags × cohort hook/dealbreaker affinities (Block D tags) · pacing/curve shape × cohort patience & commitment · register × cohort register. Output: ranking 1..N with one-line reasoning each + per-cohort risk flag (which dealbreaker bank ID threatens this pairing). Presented everywhere as ranking, never percentage. Powers: best-cohort display, editorial gap analysis, UA targeting map, localization shortlist.

**A2 — Listener-region assignment (Taste Engine side).** Live taste profiles map to cohort regions SOFTLY — nearest regions by driver-space distance, a listener can sit between regions — never hard bucketing. One line here for contract clarity; implementation belongs to the Taste Engine.

---

## 3. Module B — Episode Intelligence Engine

### 3.1 Inputs (all injected per call; nothing hardcoded)
```json
{
  "episode_script": "…full text…",
  "episode_no": 14,
  "series_state": {
    "story_id": "…",
    "prior_summary": "rolling ≤400-token summary of prior episodes",
    "promise_ledger": [ {"promise_id":"p003","text":"who killed the father","introduced_ep":2,"status":"open"} ]
  },
  "ontology_pack": {
    "drivers_vocabulary": ["…§2.2, imported…"],
    "hook_bank": [ {"id":"H1","text":"…","tags":"…"} ],
    "dealbreaker_bank": [ {"id":"D1","text":"…","tags":"…"} ],
    "cohort_cards": [ "…imported from Behavioural Ontology §4…" ]
  },
  "story_genome": { "…Module A output for this story, if it exists…" }
}
```
Caching: `ontology_pack` + instructions are the cached system prefix (identical across scripts); script + state are per-call messages.

### 3.2 Pipeline (single schema-enforced call; split into two calls only if quality demands)

**B1 — Narrative anatomy.** Core conflict · protagonist agency (drives vs reacts, with cited moment) · status-quo delta (exact difference start→end) · cognitive-load inventory (new characters/locations/terms/timelines this episode).

**B2 — Driver scoring.** Each §2.2 driver: Low/Med/High for THIS episode + mandatory one-sentence script citation for every Med/High. No citation → score invalid (groundedness eval enforces).

**B3 — Bank audit + promise ledger.** Hooks detected (bank IDs + execution strength Low/Med/High + cited moment) · dealbreakers tripped (bank IDs + severity + cited moment + which cohorts' tags they hit) · promise operations against the supplied ledger: `introduced | advanced | resolved | delayed | broken`, each with citation. Output the UPDATED ledger (this is the series-state for the next call — the engine is stateful by construction).

**B4 — Beat table (machine-readable; the Simulator ingestion contract).** Per scene/beat:
```json
{ "beat_id":"s014_b03", "purpose":"reveal|escalate|reverse|complicate|payoff|none",
  "emotional_intensity":7, "suspense":6, "info_revealed":"…",
  "churn_risk":"none|boredom|confusion|dealbreaker:D3",
  "removable":false, "note":"…" }
```
`purpose: none` + `removable: true` = the filler detector. Beat intensities accumulate into episode-level curve points → refresh the genome's trajectory curves as episodes are processed (the A↔B wiring).

**B5 — Craving + cliffhanger.** `craving_mid` and `craving_end` (1–10, matching the Simulator reaction schema field-for-field; craving_delta computed downstream). Ending classified against the defined taxonomy (§5) + strength/novelty (relative: "strongest of episodes evaluated this run") + paywall verdict enum: `crisis_cliffhanger | status_reveal | emotional_confession | resolved_no_gate` — mapped to which cohorts' pay psychology it triggers (from cards).

**B6 — Episode Cohort-Fit ranking (primary output).** Rank ALL imported cohort regions 1..N for this episode, reasoning from B2 drivers + B3 bank hits vs each card's drivers/hooks/dealbreakers/patience. Include: fastest-binge cohort, most-likely-abandon cohort + the beat_id where they abandon. Never percentages.

**B7 — Interventions with trade-offs.** Smallest changes, largest directional retention gain. Each: `{problem, evidence(beat_id), change, targeted_cohort, expected_direction, tradeoff_risk(cohort harmed + why)}`. Ranked by expected leverage. The trade-off field is mandatory — single-cohort thinking is a schema violation.

**B8 — Acquisition note.** The one moment that would make the strongest UA creative, and for which cohort (feeds the UA targeting map).

### 3.3 What was deliberately CUT from the draft prompt (recorded; do not reopen)
Absolute predictive metrics (completion %, ep-2 click %, 5/10-episode retention) — banned per §1.2 · the 0–100 eight-category weighted scorecard (weights were arbitrary `[T-C]`; its useful content is redistributed: curiosity→B3, progress→B1, pacing/removability→B4, cognitive load→B1, payoff trust→B3 ledger; originality survives only as one optional free-text line) · generic single-mind "audience psychology timeline" (replaced by cohort-conditioned B6 — the platform's cohorts ARE the audience model) · duplicate cliffhanger scoring · monolithic 9-step essay format.

---

## 4. Cross-module & cross-engine wiring

- **B4 beat_ids** fulfill the Simulator spec's "beat-mapped ingestion" and the reserved `beat_id` fields in PRD §2.1. `drop_beat` in persona reactions points at these.
- **B5 craving fields** are name-identical to the Simulator reaction schema — evaluator and personas speak one language; disagreement between them is itself a diagnostic.
- **B4 intensities → A trajectory curves**: episode-level analysis refreshes story-level curves where scripts exist; synopsis-inferred curves remain (lower confidence) where they don't. Curve provenance field: `inferred_from: synopsis | episodes`.
- **A1/B6 cohort-fit** → Taste Engine best-cohort display, editorial gap mock, UA map.
- **B3 dealbreaker hits + B6 abandon-beat** → Taste Engine drop-off rescue gains episode-level precision where Module B has run ("the pacing collapse is at beat s047_b02"), synopsis-level inference elsewhere.

---

## 5. Cliffhanger taxonomy (defined — private vocabulary eliminated)

`interrupted_action` — cut mid-event before outcome · `imminent_confrontation` — collision announced, not shown · `dramatic_irony` — audience knows what a character doesn't; episode ends before discovery · `withheld_sight` — a character sees/reads something the audience isn't shown · `flash_forward_fragment` — glimpse of a future moment without context · `exposure_threat` — a secret is one step from revelation · `alliance_inversion` — ally/enemy status flips in the final beat · `status_reveal_tease` — the true-identity/power reveal is staged but deferred · `resolved_no_hook` — episode closes with tension discharged · `multi_hook` — ≥2 of the above simultaneously.
Anything outside this list → `other` + free-text description (candidates for taxonomy v1.1).

---

## 6. Engineering standards

Structured outputs on every call (schemas above) · ontology_pack as cached prefix, warm cache before fan-out, verify `cache_read_input_tokens > 0` · run_id on every output; script-version diffs are two runs diffed on beat_id (the counterfactual mechanic) · Module A batch API at catalog scale; Module B interactive-or-batch as needed · model tiering per PRD §11; verify current model strings/pricing against hackathon credit docs · cost logged per genome and per episode analysis from call one.

---

## 7. Evaluation hooks (extends PRD §8)

- **Stability:** same script twice → driver scores identical, beat intensities ±1, cohort-fit ranking's top and bottom unchanged.
- **Groundedness:** judge verifies every citation exists in the script and supports its claim; every Med/High without valid citation = fail.
- **Cohort-fit sanity self-test:** a hook-H7-dense family-secret episode MUST rank Household-Catharsis Devotees top; a twist-dense stabilizing-free opener MUST rank Thrill Chasers top. Fixed mini-suite of constructed test scripts; run after every prompt change.
- **Ledger integrity:** promise operations reference only promises in the supplied ledger or introduced in this script; phantom promises = confabulation fail.
- **Levels lint:** automated check that no output field contains an absolute retention/completion percentage.

---

## 8. Non-goals & rejected (closed)

Does NOT: judge artistic merit · replace writers (triage instrument; the writer keeps the decision) · model VO/audio performance (v2, per Simulator spec) · claim calibrated predictions before the Simulator's backtest exists.
REJECTED: absolute predictive percentages · arbitrary-weight composite scores · hardcoded cohort lists (import or die) · generic-audience psychology modeling · undefined taxonomy terms · prose-only outputs · using Module B as the Taste Engine's story representation.

---

## 9. Handoff & demo slice

To tech team: this doc + Behavioural Ontology + genome spec = the full context pack. Build order: Module A catalog run (already gated by the six-check validation) → A1 cohort-fit over the enriched catalog → Module B on 1–2 sample scripts for the Creator View demo beat. Demo slice for Module B: one script analyzed live or pre-run — beat table with a flagged filler beat, one tripped dealbreaker with the cohort it threatens, the cohort-fit ranking, and ONE intervention with its trade-off. Sixty seconds, inside the Creator View reserve.
