# Behavioural Population Ontology v1.0 (locked)
### Canonical behavioural parameter space for the Synthetic Population Layer
### Consumed by: Story Genome · Taste Engine · Audience Simulator · Evaluation Suite
### Owners: growth/creative pair · Status: COMPLETE pending the 60-min evidence pass (Tier-A retagging) and card swap-attack

---

## 0. Platform Contract

**Purpose:** one canonical behavioural representation of listeners, consumed identically across every engine. This ontology models **behaviour, not demographics** — demographic fields exist only where they change sampling weights or cultural constants.

**Interface authority:** field names, the needs vocabulary, and the event schema are governed by **Hackathon PRD §2**. This document conforms to that contract; it does not restate or fork it. Any vocabulary change requires cross-team agreement.

**Division of state:** stable behavioural priors live HERE (generator inputs). Dynamic context — mood, moment, session intent, trends — belongs to the **Taste Engine's World signal** and is never a persona attribute. Per-run listener memory (rolling story summary, character sentiment) belongs to the **Simulator spec**. No duplication.

**Canonical behavioural outcome vocabulary** (the outcome space every engine predicts or measures; extends PRD §2.3 `event_type`):
`start → continue → pay → finish → recommend_to_others → return → abandon`
Hackathon scope simulates start/continue/pay/abandon (+finish); recommend/return are v2 (social layer & re-engagement).

**Decisions this ontology powers** (every output must ladder into one; demo language uses these, never block names):
1. *Which story should this listener see?* → Taste Engine ranking (live profile × genome).
2. *Which listener is likely to churn, and why?* → churn triggers × trajectory position → drop-off rescue.
3. *Which stories deserve localization?* → cohort-fit across markets (needs/trope vectors are language-agnostic).
4. *Which story concepts deserve investment?* → demand-vs-catalog gap per cohort region (editorial view).
5. *Which cliffhanger/paywall strategy fits which audience?* → pay psychology + hook cadence per region (Simulator roadmap).

**Cohort-fit vector (required engine output):** for every Story Genome, a fit score against each cohort region — computed from drivers×narrative-needs alignment, hook/dealbreaker matches against the genome's tropes and curves, and style×pacing compatibility. Powers "best cohort" per recommendation, the editorial gap analysis, and a pre-launch UA targeting map. Presented as **rankings** per PRD §7, never calibrated percentages.

---

## 1. Evidence Policy (mandatory labels)

- **[T-A]** Public evidence — PocketFM charts, Play/App Store reviews, Meta Ad Library creatives, YouTube/community comments, public interviews, genre trends.
- **[T-B] ASSUMPTION (Industry Prior)** — e.g., "serialized daily-drama habits transfer to audio fiction."
- **[T-C] ASSUMPTION (Creative)** — team hypothesis, explicitly owned.

Never present an assumption as PocketFM fact. Internal-telemetry-sounding claims (ARPU, IAP, day-N churn, completion rates) are **banned** unless publicly sourced — retag or rewrite all such lines from the previous draft during the evidence pass.

**Canonical answer when asked "how do you know?":** *"We don't — and that's by design. Every assumption is explicitly tagged by evidence tier, and the platform is built to replace assumptions with real telemetry as it arrives."* This is the only approved response; never improvise certainty.

---

## 2. Market Model (Block A)

Coverage target **≥85% per market**, residual explicitly acknowledged.

| Market segment | Weight | Confidence | Evidence |
|---|---|---|---|
| India · Hindi · Tier 2/3 | 0.40 | Med | [T-A] revenge/system-progression dominance in Hindi top charts; UA creative volume — VERIFY in pass |
| India · Hindi/English · Tier 1 urban | 0.20 | Low | [T-B] urban audiences over-index on modern slice-of-life & relationship drama, per adjacent-platform patterns |
| India · Tamil/Telugu | 0.15 | Med | [T-A] regional-IP chart presence; narrator-fandom comment signals — VERIFY |
| US · romance audio | 0.20 | Med | [T-A] werewolf/billionaire/mafia UA creative density; store reviews demanding update speed — VERIFY |
| Other intl. | 0.05 | Low | [T-C] opportunistic UA reach; universal underdog tropes travel |

**Cultural constants per market** (retained from filled kit; each line inherits the market's evidence tier):
- **Hindi Tier 2/3:** family-centricity (actions reflect on household), justice/honor framing, clear moral binaries, conservative romance norms.
- **Hindi/English Tier 1:** individualism-vs-family-duty tension, career-ambition framing, modern romance norms, Hinglish register tolerance.
- **Tamil/Telugu:** deep family-centricity, high emotional register, elders/tradition as conflict source, multi-generational justice arcs.
- **US romance:** individualism, explicit romance norms, tolerance for morally gray leads, fast-hook expectations.

---

## 3. Behavioural Parameter Space

### Block B — Psychological drivers (PRD §2.2 vocabulary — FROZEN)
catharsis · justice_seeking · escapism · comfort · belonging · power_fantasy · wish_fulfillment · nostalgia · identity · hope
2–3 primary drivers per persona, intensity low/med/high. **Rejected additions (recorded):** Romance, Mystery (genres, not needs), Status (= power_fantasy), Adventure (≈ escapism), Self-Improvement (unconsumed downstream).

### Block C — Consumption style (numeric axes; generator jitters)
binge_speed (eps/day 1–15) · narrative_patience (0–1) · commitment_tolerance (20/100/500 eps) · churn_sensitivity (0–1) · pay_threshold (0–1, cliffhanger pressure required before coins) · listening_context (commute/chores/bedtime/dedicated) · language_register (pulp↔literary) · exploration_propensity (0–1).
**Rejected additions (recorded):** creator loyalty, series loyalty, attention span, re-watch behaviour, social influence, trend-following — fail decision-usefulness or duplicate existing axes. Behaviour policy remains ONE axis (exploration_propensity), not a block: the simulating LLM conditioned on the persona *is* the policy.

### Block C½ — Sampling order & compatibility rules
Sample conditionally: market → drivers|market → style|drivers → banks|both. Plus:
**Hard-invalid (reject & resample):** commitment 20 + 300-ep-epic top affinity · patience <0.2 + slow-philosophical top affinity · pay_threshold 0 + churn_sensitivity 1.
**Low-probability (≤5–10% — these ARE the anti-stereotype variants):** power_fantasy HIGH + literary register · comfort HIGH + high-darkness affinity · (add one per cohort anti-stereotype below).
**Engineer note:** sensitivity sweep per axis; unchanged behaviour ⇒ delete axis. If two variables are indistinguishable in simulation, merge or delete one — no synonym variables survive.

### Block D — Human-authored banks, WITH compatibility tags
Tags: `[aff: …]` boosts sampling for those drivers/cohorts; `[excl: …]` never sampled for them; `[univ]` = everyone.

**Dealbreakers**
1. Love triangle after ep. 5 → drop within 3 eps `[aff: romance-centric]`
2. Female lead turns passive post-marriage → drop `[univ; strongest: identity, justice]`
3. Recap/filler >~20% of episode → drop-risk spike `[univ; strongest: low-patience]`
4. Miscommunication as sole conflict engine 5+ eps → drop `[aff: romance, family]`
5. Humiliation with no payback in sight 10+ eps → drop `[aff: justice, power only]`
6. Paywall on resolved, non-cliffhanger episode → refuse + churn risk `[excl: comfort-HIGH — see Comfort card P3]`
7. Sudden tonal swerve comedy→tragedy → drop `[aff: comfort]`
8. Villain wins repeatedly, no counterplay → drop `[aff: power, justice]`
9. Protagonist abandons core competency for romantic interest → drop-risk `[aff: power, identity]`
10. Unwarned season-ending cliffhanger, no continuation live → churn + bad review `[univ]`
11. Narrator voice change / audio quality drop → immediate drop `[univ]`
12. Idiot plot (smart characters act dumb to create conflict) → drop `[univ; weight↑ literary register]`
13. Dense world-building dumps in first 3 eps → drop `[aff: low-patience; excl: literary high-patience]`
14. Romance leads fully apart 20+ eps in tagged romance → drop `[aff: romance only]`
15. Defeated minor antagonist returns power-buffed → churn risk `[aff: power_fantasy]`

**Hooks**
1. Revenge milestone completed on-screen → binge burst `[aff: justice, power]`
2. Hidden identity revealed to one character only → strong continue `[univ]`
3. Courtroom / public confrontation → continue + pay-tolerance↑ `[aff: justice, catharsis]`
4. Mentor betrayal foreshadowed → continue `[univ]`
5. Underdog's first real power/status jump → binge burst `[aff: power]`
6. Romantic almost-moment interrupted → continue `[aff: romance-centric, comfort]`
7. Family secret implicating the household → continue `[aff: belonging, family-drama]`
8. Protagonist bluffs vastly superior enemy → binge burst `[aff: power]`
9. Forced proximity (one bed / one shelter) → strong continue `[aff: romance-centric]`
10. OP rule-breaking artifact/ability early → binge burst `[aff: power; thrill]`
11. "Unwanted" character proves worth to those who exiled them → strong continue `[aff: identity, belonging]`
12. Unconnected B-plot crashes into A-plot → binge burst `[univ]`
13. Explicit verbal teardown of arrogant antagonist → continue + pay-tolerance↑ `[aff: justice, catharsis]`
14. Modern knowledge in historical/fantasy setting solves mundane problem → continue `[aff: power, escapism]`
15. Adorable loyal companion/pet introduced → strong continue `[aff: comfort; univ-lite]`

---

## 4. Cohort Cards — high-density behavioural regions (reporting buckets, not fixed personas)

All predictions are **RELATIVE** (ordering/direction/comparison). Absolute retention %s are banned per PRD §7.

---

**CARD 1 — Justice-Payoff Bingers**
Market/weight: Hindi Tier 2/3 (≈35%)
Evidence: [T-A — VERIFY] revenge titles dominate Hindi charts; UA creatives lead humiliation→comeback; reviews praise villain-comeuppance, complain about prolonged hero suffering.
Drivers: justice_seeking HIGH · power_fantasy HIGH · escapism MED
Style: binge 8/day · patience 0.3 · commitment 500 · churn_sens 0.6 · pay_thr 0.5 · commute+night · pulp
Acquisition: open on public humiliation of the lead. Retention: comeback staircase, payoff every 3–5 eps. Monetization: paywall on eve of confrontation. Churn triggers: 10+ eps suffering with no counterplay · consequences evaporate for the villain · justice indefinitely deferred.
Dealbreakers: #5, #6, hero forgives villain unearned. Hooks: #1, #5, rival's public downfall.
Anti-stereotype (~20%): quietly follows the romance B-plot; drops if love interest is written out. `[low-prob rule: justice-HIGH + romance-B-plot-sensitive]`
**Behaviour policy summary:** enjoys → needs payoff ≤5 eps → pays only for unresolved confrontations → leaves when suffering exceeds payoff.
PREDICTIONS (relative): P1 drops on slow literary sagas *earlier and harder than Comfort or Status cohorts*. P2 out-retains all cohorts on fast revenge arcs with early payoff. P3 pays at cliffhanger gates; refuses resolved-episode gates *more than any cohort*.

---

**CARD 2 — Slow-Burn Comfort Seekers**
Market/weight: US romance (≈40%) + Hindi Tier 1 (≈20%)
Evidence: [T-A — VERIFY] "cozy/safe/relaxing" language recurs in store reviews; domestic-tension UA creatives visible in ad library. [T-B] long-running low-conflict serials retain in adjacent formats. *(Previous "high completion rates / IAP metrics" lines DELETED — unverifiable telemetry.)*
Drivers: comfort HIGH · escapism MED · belonging MED
Style: binge 2/day · patience 0.8 · commitment 100 · churn_sens 0.8 · pay_thr 0.3 · bedtime/chores · literary
Acquisition: aesthetic low-stakes cozy opening. Retention: reliable relationship progression, micro-conflicts resolved in 1–2 eps. Monetization: paywall before confession/reunion. Churn triggers: tonal shift to danger/tragedy · sustained emotional volatility · central relationship turns toxic.
Dealbreakers: #7, #13, graphic violence / high-anxiety cliffhangers at bedtime. Hooks: #6, #9, found-family building.
Anti-stereotype (~15%): drops "cozy" if protagonist has zero ambition/hobby outside the relationship. `[low-prob rule: comfort-HIGH + ambition-required]`
**Behaviour policy summary:** enjoys → continues on steadiness, not twists → pays for emotional payoff incl. resolved epilogues (bank #6 excluded) → leaves when safety breaks.
PREDICTIONS: P1 drops on early-violence mafia romance *faster than any cohort except Thrill Chasers drop on slow-burn*. P2 out-retains all cohorts on low-external-conflict romance. P3 uniquely pays for resolved epilogue episodes — *inverts* the platform-default cliffhanger-pay pattern.

---

**CARD 3 — Status-Progression Loyalists**
Market/weight: Tamil/Telugu (≈50%) + Hindi Tier 2/3 (≈20%)
Evidence: [T-A — VERIFY] 300+ episode epics cluster in regional charts; comment sections debate power levels & hierarchy; rags-to-riches / exiled-heir UA creatives present in ad library. *(Prior "convert efficiently" claim retagged: [T-B].)*
Drivers: power_fantasy HIGH · identity HIGH · wish_fulfillment MED
Style: binge 5/day · patience 0.5 · commitment 500 · churn_sens 0.2 · pay_thr 0.7 · dedicated/commute · pulp
Acquisition: protagonist at absolute bottom of a strict hierarchy. Retention: quantifiable milestones of respect/wealth/power. Monetization: paywall blocking the true-status reveal → pays heavily. Churn triggers: hard-won status lost with no path back · progression stalls for 15+ eps · protagonist defers to incompetent authority out of unearned respect.
Dealbreakers: #2, #9, #15. Hooks: #2, #5, #11, antagonists forced to submit.
Anti-stereotype (~10%): a slice prefers the *villain's* chapters and stays for antagonist depth even when the hero's rise stalls. `[low-prob rule: power-HIGH + villain-perspective-loyal]` *(replaces prior narrator-change trait — that's universal dealbreaker #11, not an anti-stereotype).*
**Behaviour policy summary:** enjoys → continues on milestone cadence → pays heaviest at reveal walls, ignores routine cliffhangers → leaves when progression reverses without a path.
PREDICTIONS: P1 churns on luck-driven (effortless) protagonists *while Justice cohort stays if payback still lands*. P2 produces the largest binge bursts of any cohort at underestimated-lead reveal markers. P3 highest pay-selectivity: skips standard cliffhanger gates that Justice cohort pays, spends heavily on reveal/revenge gates.

---

**CARD 4 — High-Churn Thrill Chasers**
Market/weight: US romance (≈40%) + Other intl. (≈70%)
Evidence: [T-B] shock-value UA creatives (cheating, sudden death, betrayal) are a persistent high-volume pattern in the ad library → implies a fast-hit audience worth modeling. *(Prior "massive day-0/day-1 churner volume" DELETED — internal telemetry we don't have.)*
Drivers: catharsis HIGH · escapism HIGH · justice_seeking MED
Style: binge 12/day · patience 0.05 · commitment 20 · churn_sens 0.9 · pay_thr 0.8 · commute/gym · pulp
Acquisition: in-media-res high-adrenaline betrayal/confrontation. Retention: twist cadence, cliffhanger every episode. Monetization: only under extreme life-or-death cliffhanger pressure, grudgingly. Churn triggers: any pure-downtime episode · pacing stabilizes · exposition >5 min without a twist.
Dealbreakers: #3, #13, >5 min exposition without a twist. Hooks: #1, #10, #12, immediate violent retribution for slights.
Anti-stereotype (~10%): a slice will violate their 20-ep tolerance and stay 100+ eps for ONE specific trope done right (e.g., serial betrayal-revenge chains) — commitment is trope-conditional, not absent. `[low-prob rule: commitment-20 + single-trope-extended-stay]` *(replaces "tolerates plot holes" — that deepened the stereotype rather than breaking it.)*
**Behaviour policy summary:** starts on shock → continues only while twist cadence holds → pays rarely and only at maximum pressure → abandons the moment pacing stabilizes.
PREDICTIONS: P1 fastest drop of ALL cohorts on slow-burn literary content — majority gone within the first episodes. P2 binges hardest of all cohorts through twist-dense openings, then churns at stabilization *earlier than every other cohort*. P3 lowest pay-conversion of all cohorts; churns instantly at non-crisis paywalls.

---

**CARD 5 — Household-Catharsis Devotees** *(STRAWMAN — attack in evidence pass)*
Market/weight: Hindi Tier 2/3 (≈30%) + Tamil/Telugu (≈35%)
Evidence: [T-B] daily family-serial consumption is a dominant adjacent-format habit for this demographic; [T-C] we hypothesize it transfers to audio family drama; [T-A — TO COLLECT] family-drama/saas-bahu-adjacent titles in charts, reviews invoking "just like watching serials with my mother."
Drivers: belonging HIGH · catharsis HIGH · hope MED
Style: binge 4/day · patience 0.7 · commitment 500 · churn_sens 0.4 · pay_thr 0.4 · chores/evening-household · pulp-emotional
Acquisition: a wronged woman/daughter-in-law underestimated by the household. Retention: cyclical vindication — schemes exposed, dignity restored, every 5–8 eps. Monetization: paywall before a public vindication scene. Churn triggers: the wronged lead stays a doormat with no vindication cycle · sympathetic family member permanently destroyed · household dissolves with no reunion hope.
Dealbreakers: #4 (long-run), #11; cohort-specific: elder-disrespect played for laughs. Hooks: #7, #11; cohort-specific: hidden virtue witnessed by the one person who matters.
Anti-stereotype (~15%): a slice actively wants the "villainess" POV and drops sanitized, conflict-free family stories. `[low-prob rule: belonging-HIGH + villainess-POV-preference]`
**Behaviour policy summary:** continues on vindication cycles → pays at public-vindication gates → leaves when injustice compounds without catharsis.
PREDICTIONS: P1 out-retains all cohorts on multi-generational household drama. P2 tolerates slower pacing than every cohort except Comfort Seekers, IF the vindication cycle holds. P3 consumes hook #7 (family secret) more strongly than any other cohort — *this card is why that hook exists.*

---

**CARD 6 — Tier-1 Aspirational Escapists** *(STRAWMAN — attack in evidence pass)*
Market/weight: Hindi/English Tier 1 urban (≈65%)
Evidence: [T-B] urban listeners over-index on career/modern-relationship narratives and Hinglish register in adjacent media; [T-C] we hypothesize office-politics + upward-mobility romance is the Tier-1 core; [T-A — TO COLLECT] Hinglish title presence in charts, urban-targeted UA creatives.
Drivers: identity HIGH · wish_fulfillment HIGH · escapism MED
Style: binge 3/day · patience 0.6 · commitment 100 · churn_sens 0.7 · pay_thr 0.5 · commute/gym · Hinglish, pulp-literary mid
Acquisition: relatable ambitious lead humiliated in a modern setting (office, startup, wedding market). Retention: dual progression — career wins AND relationship wins alternating. Monetization: paywall at public professional vindication or relationship-status reveal. Churn triggers: lead's ambition evaporates into pure romance · setting turns regressive/traditional without irony · stakes shrink to household-only.
Dealbreakers: #2, #9; cohort-specific: lead's success attributed to family connections rather than competence. Hooks: #11, #13; cohort-specific: underestimated candidate outperforms the privileged rival.
Anti-stereotype (~15%): a slice unwinds with full-fantasy power epics — modern-setting loyalty is context-dependent (weeknight vs weekend). `[low-prob rule: identity-HIGH + weekend-epic-switcher]`
**Behaviour policy summary:** continues on alternating competence/romance wins → pays at vindication reveals → leaves when ambition or modernity collapses.
PREDICTIONS: P1 highest exploration_propensity — samples more distinct titles per week than any cohort. P2 drops regressive-traditional framing *faster than every cohort except US Comfort on violence*. P3 mid pay-selectivity: pays vindication gates like Status cohort but at lower intensity, ignores pure-romance gates.

---

**Coverage math (checklist #1):** Hindi Tier 2/3: 35+20+30 = 85% ✓ · Tier 1: 20+65 = 85% ✓ · Tamil/Telugu: 50+35 = 85% ✓ · US romance: 40+40 = 80% + residual acknowledged: *steady mainstream fast-burn romance payers (~20%) — candidate Card 7 if time allows, else explicitly unmodeled* · Other intl.: 70% + residual acknowledged.

---

## 5. Freeze Checklist (all must pass before handoff)

1. **Coverage** — ≥85% per market or residual explicitly acknowledged. *(Currently passes with two acknowledged residuals.)*
2. **Exclusivity / Identifiability** — any two cards produce articulable divergent behaviour, AND every card names ≥1 behaviour no other card can generate (each card's P3 serves this). A card whose removal changes nothing gets merged or cut.
3. **Predictiveness / decision-usefulness** — every axis changes a simulated decision AND a PocketFM decision. Sensitivity sweep automates.
4. **Stability sort** — weekly-changing attributes are Taste Engine context, not persona fields.
5. **Actionability** — every field consumable by Story Intelligence; vocabulary = PRD §2.2, unforked.
6. **Anti-stereotype / variance** — every card has one, each mapped to a low-probability rule; goal is preventing behavioural collapse, not correctness.
7. **UA-planner smell test** — a media buyer would recognize and target each region.
8. **Prediction cards** — ≥3 relative predictions per card, pre-registered before ANY simulation; diffed after first runs (divergence = harness bug or insight; log either).

---

## 6. Design Principles

**Behavioural naming rule (hard convention):** cohort regions are referred to by behavioural names in ALL outputs, UI, demo, and deck — "Household-Catharsis Devotees," never "Tier-2 women"; "Justice-Payoff Bingers," never "young male listeners." Demographics appear only inside sampling weights and cultural constants, never as labels.

Behaviour over demographics · regions over fixed personas · parameters over documents · one ontology, unforked, across all engines · dynamic context belongs to the Taste Engine · this layer models stable behaviour only · every parameter must change a business decision or be removed · every claim is relative or explicitly calibrated · assumptions are labeled, never laundered as facts · simulation supports experiments, it does not replace users · the ontology is versioned and evolves only through evidence or simulation findings.

---

## 7. Non-Goals (incl. decisions REJECTED and closed)

Does NOT: reproduce PocketFM's internal user distribution · predict exact production metrics (retention %, ARPU, IAP) · replace real A/B testing once telemetry exists · model every possible listener.
REJECTED (do not reopen): driver-vocabulary additions Romance/Mystery/Status/Adventure/Self-Improvement · Behaviour Policy as a block (one axis: exploration_propensity) · affinity-score matrices (ternary tags suffice; scores are v2) · outcome-distribution predictions (violates rankings-not-levels) · taste elasticity (Taste Engine owns drift) · restating the PRD §2 interface here · splitting Tamil/Telugu/Bengali rows without evidence to ground them · environment-model abstraction (Simulator spec owns it) · >8 cards · **absolute counterfactual deltas in any surface ("+8% retention if cliffhanger moved") — banned until a real simulator run with a null-run noise floor exists; directional counterfactual claims only, and only from actual runs**.

---

## 8. Handoff

On freeze: this document → simulator engineer (generator input: weights, distributions, rules, tagged banks, low-prob rules). Prediction cards → retained by the growth/creative pair as the pre-registered validation baseline, diffed against first simulation runs. Remaining human work before freeze: **(1)** 60-min evidence pass — resolve every `[T-A — VERIFY / TO COLLECT]`, attack both strawman cards; **(2)** swap-and-attack review of all six cards against the checklist. Then the pair switches to demo narrative + UI copy.
