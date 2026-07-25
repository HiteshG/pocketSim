# Crowd

*A synthetic audience simulation system.*

Crowd plays a script to a few hundred synthetic listeners, episode by episode, and turns their decisions into a ranked list of which episodes to fix, where to put the paywall, and which cohort the story is actually for.

## Features

Crowd works with personas that are synthesised from hand-authored archetypes, not fitted from listening logs, and no backtest has been run.

- Ranking episodes *within* a script — which ones are weakest relative to the rest
- Paired rewrite deltas — same audience, v1 vs v2
- Cross-script ranking — script A vs script B
- Drop-beat localisation — where inside an episode attention breaks
- Cohort divergence — which archetype engages most (directional)

Reports say *"episode 7 is the weakest in this script; the rewrite recovers X points in paired simulation"* — never *"predicted retention: 34%."* Relative claims survive persona miscalibration because the bias applies roughly uniformly and cancels in the difference. Absolute claims do not, and with no data behind them they'd be indefensible.

The reports go further than a dashboard could. **Craving delta** catches the episode that resolves *too cleanly* — a satisfying finish that quietly loses the listener on a serialized platform, invisible to a satisfaction score. **Prediction disagreement** tells you whether a cliffhanger actually works, or just looks like one. And the **Fix List** ranks every episode by real money at risk — `drop_rate × active_share × episodes_remaining` — so a weak episode before the paywall gets triaged as the emergency it is, instead of the same shrug as a weak episode nobody was going to reach anyway.

## The mental model

It's a focus group. Each command is one step of running one.

| Command | Plain English | 
|---|---|
| `ingest` | Prepare the script — split into episodes, tag story beats | 
| `personas` | Hire the test audience, saved to a file and reused forever | 
| `simulate` | Hold the screening — episode by episode, continue/drop, pay/not | 
| `report` | Write up what happened — fix list, retention curve, paywall call |   
| `compare` | Diff two screenings — did the rewrite work, and by how much? | 


## Quickstart

Runs offline on the bundled sample with `--provider mock` — no API key, no cost.

```bash
# 1. Prepare the script
pocketsim ingest --script scripts/script1.txt --series script1 \
                 --market india-hindi --provider mock

# 2. Hire the audience (once — reused for every run after this)
pocketsim personas build --market india-hindi --count 25 --seed 42 \
                 --out populations/script1-25.json --provider mock

# 3. Read a few of them — this is the validity gate
pocketsim personas inspect --population populations/script1-25.json -n 3

# 4. Hold the screening
pocketsim simulate --series script1 --population populations/script1-25.json \
                 --run-id script1-smoke --provider mock

# 5. Write it up
pocketsim report --run script1-smoke --format html --open
```

Then the loop that earns its keep — a writer rewrites episode 7:

```bash
pocketsim ingest   --script scripts/script1-v2.txt --series script1-v2 --market india-hindi
pocketsim simulate --series script1-v2 --population populations/script1-25.json \
                   --run-id script1-v2 --provider mock
pocketsim compare  --base script1-smoke --against script1-v2
```

For real runs, drop `--provider mock` (defaults to `openai-api`) and start with `--limit-episodes 3` to smoke-test for about a dollar.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env      # add OPENAI_API_KEY
```

Python 3.11+.

---

Everything below the surface — how personas are synthesised, what gets measured and why, provider tradeoffs, markets, verification, and what's deliberately not built yet — is in **[DESIGN.md](DESIGN.md)**.

Simulating is slow and costs money; reporting is instant and free, so you simulate once and re-report as metrics get added. The population file is reused across runs on purpose — `compare` only works if both runs used the *same* listeners, so persona bias cancels in the difference and you know the script moved, not the audience.
