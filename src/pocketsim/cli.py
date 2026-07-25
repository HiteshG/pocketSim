"""pocketsim — run a focus-group screening for a script that hasn't been produced yet.

    ingest     prepare the script      → split into episodes, tag story beats
    personas   hire the test audience  → synthesise listeners, once, then reuse
    simulate   hold the screening      → play the story to everyone, episode by episode
    report     write up what happened  → Fix List, retention, paywall, cohort fit
    compare    diff two screenings     → did the rewrite actually work?
    history    housekeeping            → what's been run, export raw data
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import list_markets, load_market
from .ingest import ingest_script, list_series, load_series, map_beats, save_series
from .llm import get_provider, provider_default_model
from .metrics import compare as compare_metrics
from .metrics import compute
from .personas import (
    audit_population,
    build_population,
    load_population,
    save_population,
    write_population_report,
)
from .report import render_comparison_markdown, render_markdown, write_report
from .simulate import simulate as run_simulation
from .store import RunMeta, RunStore, delete_run, get_run, list_runs, load_reactions, run_dir

load_dotenv()
console = Console()

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=__doc__,
    rich_markup_mode="rich",
)
personas_app = typer.Typer(no_args_is_help=True, help="Build, audit and inspect the test audience.")
history_app = typer.Typer(no_args_is_help=True, help="Past runs.")
app.add_typer(personas_app, name="personas")
app.add_typer(history_app, name="history")

PROVIDER_HELP = "openai-api (production) · codex-cli (free iteration) · mock (offline, deterministic)"


def _fail(msg: str) -> None:
    console.print(f"[bold red]✗[/] {msg}")
    raise typer.Exit(1)


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="Show version and exit."),
) -> None:
    if version:
        console.print(f"pocketsim {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


# ─────────────────────────────────────────────────────────────────────────────


@app.command()
def markets() -> None:
    """List available markets. Adding a market is adding a YAML file, not a code change."""
    t = Table(
        "market", "language", "occasions", "regions", "genres", "status",
        box=None, pad_edge=False,
    )
    for name in list_markets():
        m = load_market(name)
        t.add_row(
            m.market,
            m.language,
            str(len(m.cohorts)),
            str(len(m.ontology.regions)),
            str(len(m.genres)),
            "[yellow]provisional[/]" if m.is_provisional else "[green]fitted[/]",
        )
    console.print(t)
    console.print(
        "\n[dim]occasions = when they listen (per market) · regions = what they want from a "
        "story (shared across markets, markets/_ontology.yaml)[/]"
    )


@app.command()
def ingest(
    script: Path = typer.Option(..., "--script", exists=True, help="Script .txt with `Episode N` headers."),
    series: str = typer.Option(..., "--series", help="Short name for this script version."),
    market: str = typer.Option("india-hindi", "--market"),
    provider: str = typer.Option("openai-api", "--provider", help=PROVIDER_HELP),
    model: Optional[str] = typer.Option(None, "--model"),
    no_beats: bool = typer.Option(False, "--no-beats", help="Skip beat mapping (no LLM calls)."),
) -> None:
    """Prepare a script: split into episodes and tag 5-10 named story beats in each.

    Beats are what make `drop_beat` actionable — "they left at the wedding confrontation"
    is something a writer can fix; "they left somewhere in episode 14" is not.
    """
    mkt = load_market(market)
    try:
        s = ingest_script(script, series, market)
    except ValueError as e:
        _fail(str(e))

    console.print(f"Split [bold]{script.name}[/] into [bold]{len(s.episodes)}[/] episodes "
                  f"({min(s.episode_numbers)}–{max(s.episode_numbers)})")

    async def go():
        if no_beats:
            from .ingest import BeatMap
            return BeatMap(series=series, model="none", created_at="", beats={})
        p = get_provider(provider, model)
        with console.status("Mapping story beats…"):
            bm = await map_beats(p, s, mkt.ontology, model)
        await p.aclose()
        console.print(f"Beat-mapped with [dim]{p.name}[/] · {p.total.summary()}")
        return bm

    bm = asyncio.run(go())
    d = save_series(s, bm)

    t = Table("ep", "title", "words", "beats", box=None, pad_edge=False)
    for e in s.episodes:
        t.add_row(str(e.number), e.title[:44], str(e.word_count), str(len(bm.for_episode(e.number))))
    console.print(t)
    console.print(f"[green]✓[/] saved to [bold]{d}[/]")


# ─────────────────────────────────────────────────────────────────────────────


@personas_app.command("build")
def personas_build(
    market: str = typer.Option("india-hindi", "--market"),
    count: int = typer.Option(300, "--count", min=1, help="Population size."),
    seed: int = typer.Option(42, "--seed", help="Same seed → same audience, byte for byte."),
    out: Path = typer.Option(..., "--out", help="Where to save, e.g. populations/ih-300.json"),
    provider: str = typer.Option("codex-cli", "--provider", help=PROVIDER_HELP),
    model: Optional[str] = typer.Option(None, "--model"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Ignore the prose cache."),
) -> None:
    """Synthesise the test audience.

    Numbers are sampled from distributions declared in the market YAML; only the prose is
    written by a model. That split is what makes an invented population auditable — every
    number traces to a line a human can argue with — and reproducible under a seed.
    """
    m = load_market(market)

    async def go():
        p = get_provider(provider, model)
        with console.status(f"Synthesising {count} listeners for {market}…"):
            pop = await build_population(m, count, seed, p, model, use_cache=not no_cache)
        await p.aclose()
        console.print(f"Generated with [dim]{p.name}[/] · {p.total.summary()}")
        return pop

    pop = asyncio.run(go())
    save_population(pop, out)

    t = Table("cohort", "n", "share", box=None, pad_edge=False)
    grouped = pop.by_cohort()
    for c in m.cohorts:
        n = len(grouped.get(c.id, []))
        t.add_row(c.id, str(n), f"{n / pop.count:.1%}")
    console.print(t)
    console.print(f"[green]✓[/] {pop.count} personas → [bold]{out}[/]")
    console.print(f"  fingerprint [bold]{pop.fingerprint}[/]  (runs must share this to be comparable)")

    rep = audit_population(pop, m, str(out))
    audit_paths = write_population_report(pop, m, rep, out)
    _print_audit(rep)
    console.print(
        f"  [dim]audit saved[/] {audit_paths['audit_markdown']} · {audit_paths['audit_json']}"
    )
    if not rep.ok:
        console.print("[yellow]![/] Audit failed — review before simulating.")
        raise typer.Exit(2)


def _print_audit(rep) -> None:
    console.print()
    console.print(f"[bold]Diversity audit[/] · {rep.count} personas")
    for c in rep.checks:
        mark = "[green]✓[/]" if c.passed else "[red]✗[/]"
        console.print(f"  {mark} {c.name:<28} [dim]{c.detail}[/]")


@personas_app.command("audit")
def personas_audit(
    population: Path = typer.Option(..., "--population", exists=True),
    market: Optional[str] = typer.Option(None, "--market"),
) -> None:
    """Check a population for mode collapse.

    The default failure of LLM persona generation is 300 delivery riders called Rakesh in
    Indore. A collapsed population still produces a clean-looking retention curve — it
    just describes one imaginary person, repeated.
    """
    pop = load_population(population)
    rep = audit_population(pop, load_market(market or pop.market), str(population))
    _print_audit(rep)
    raise typer.Exit(0 if rep.ok else 2)


@personas_app.command("inspect")
def personas_inspect(
    population: Path = typer.Option(..., "--population", exists=True),
    cohort: Optional[str] = typer.Option(None, "--cohort", help="Filter by listening occasion."),
    region: Optional[str] = typer.Option(None, "--region", help="Filter by need region."),
    n: int = typer.Option(5, "-n", help="How many to print."),
) -> None:
    """Read a sample of the audience.

    This is the v1 validity gate. With no listening data there is no backtest, so the
    check that matters is whether your content team recognises these as real listeners.
    If they don't, nothing downstream is worth running.

    Both axes are printed, because both have to survive that read: a plausible commuter
    who wants an implausible thing from a story is still a persona nobody should trust.
    """
    pop = load_population(population)
    people = [
        p
        for p in pop.personas
        if (not cohort or p.cohort_id == cohort) and (not region or p.region_id == region)
    ][:n]
    if not people:
        _fail(f"no personas matching cohort={cohort!r} region={region!r}")

    labels: dict[str, str] = {}
    try:
        labels = {r.id: r.label for r in load_market(pop.market).ontology.regions}
    except Exception:
        pass

    for p in people:
        console.print()
        console.rule(
            f"[bold]{p.realname}[/] · {p.persona_id} · [dim]{p.cohort_id}[/] · "
            f"[cyan]{labels.get(p.region_id, p.region_id)}[/]"
        )
        console.print(f"{p.age}, {p.gender}, {p.profession}, {p.city} (tier {p.city_tier})")
        console.print(f"[dim]{p.persona}[/]")
        console.print(
            f"{p.avg_daily_minutes} min/day · {int(p.session_minutes)} min sessions @ {p.playback_speed}x · "
            f"{p.session_pattern} · {p.listening_privacy.replace('_',' ')}"
        )
        console.print(
            f"tenure {p.tenure_months}mo · spend [bold]{p.coin_spend_tier}[/] · "
            f"pay threshold {p.pay_threshold:.2f} · churn sensitivity {p.churn_sensitivity:.2f}"
        )
        console.print(f"top genres: [italic]{', '.join(p.top_genres(3))}[/]")
        drivers = ", ".join(f"{d.replace('_',' ')} [dim]{lvl}[/]" for d, lvl in p.drivers.items())
        console.print(
            f"wants: {drivers} · patience {p.narrative_patience:.2f} · "
            f"commits to ~{p.commitment_tolerance} eps · {p.language_register} register · "
            f"[yellow]{p.mbti}[/]"
        )
        if p.anti_stereotype:
            console.print(f"[magenta]unusual for this region:[/] {p.anti_stereotype}")


# ─────────────────────────────────────────────────────────────────────────────


@app.command()
def simulate(
    series: str = typer.Option(..., "--series", help="An ingested series name."),
    population: Path = typer.Option(..., "--population", exists=True),
    run_id: str = typer.Option(..., "--run-id", help="Name for this screening."),
    market: Optional[str] = typer.Option(None, "--market", help="Defaults to the series' market."),
    provider: str = typer.Option("openai-api", "--provider", help=PROVIDER_HELP),
    model: Optional[str] = typer.Option(None, "--model"),
    concurrency: int = typer.Option(16, "--concurrency"),
    limit_episodes: Optional[int] = typer.Option(None, "--limit-episodes", help="Smoke-test switch."),
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    """Hold the screening: play the story to every persona, episode by episode.

    Each listener answers four things at every boundary — continue or drop, pay or not,
    where they checked out, and what they think happens next. This is the expensive step;
    `report` is free and can be re-run as often as you like.
    """
    try:
        s, bm = load_series(series)
    except FileNotFoundError as e:
        _fail(str(e))
    m = load_market(market or s.market)
    pop = load_population(population)

    if pop.market != m.market:
        _fail(f"population was built for market '{pop.market}' but you asked for '{m.market}'")

    try:
        get_run(run_id)
        if not overwrite:
            _fail(f"run '{run_id}' already exists. Use --overwrite or pick another --run-id.")
        delete_run(run_id)
    except KeyError:
        pass

    n_eps = min(limit_episodes or len(s.episodes), len(s.episodes))
    console.print(
        f"[bold]{series}[/] · {n_eps} episodes · {pop.count} listeners · "
        f"market {m.market} · provider [dim]{provider}[/]"
    )
    if m.is_provisional:
        console.print("[yellow]![/] Market cohorts are provisional (not fitted from logs) — "
                      "results are relative only.")

    meta = RunMeta(
        run_id=run_id,
        series=series,
        market=m.market,
        population_path=str(population),
        population_fingerprint=pop.fingerprint,
        population_size=pop.count,
        provider=provider,
        model=model or provider_default_model(provider),
        episodes_planned=n_eps,
    )

    async def go(store: RunStore):
        p = get_provider(provider, model, concurrency)
        started_at = time.perf_counter()
        last_episode_at = started_at

        def on_episode(ep, listened, alive, usage):
            nonlocal last_episode_at
            now = time.perf_counter()
            episode_seconds = now - last_episode_at
            elapsed_seconds = now - started_at
            last_episode_at = now
            bar = "█" * int(28 * alive / pop.count)
            console.print(
                f"  ep {ep:>3}  {listened:>4} heard → [bold]{alive:>4}[/] active "
                f"[dim]{bar:<28}[/] {alive / pop.count:>5.1%}   "
                f"[dim]{episode_seconds:.1f}s · {usage.summary()}[/]"
            )
            store.log(
                f"episode={ep} listened={listened} active={alive} "
                f"episode_seconds={episode_seconds:.2f} elapsed_seconds={elapsed_seconds:.2f} "
                f"calls={usage.calls}"
            )

        res = await run_simulation(
            p, m, s, bm, pop, run_id,
            limit_episodes=limit_episodes,
            on_episode=on_episode,
            on_rows=store.record,
            model=model,
        )
        await p.aclose()
        return res

    with RunStore(meta) as store:
        store.save_input("episodes.json", s.model_dump(mode="json"))
        store.save_input("beats.json", bm.model_dump(mode="json"))
        store.save_input("population.json", pop.model_dump(mode="json"))
        store.save_input(
            "config.json",
            {
                "run_id": run_id,
                "series": series,
                "market": m.market,
                "population": str(population),
                "provider": provider,
                "model": model or provider_default_model(provider),
                "concurrency": concurrency,
                "limit_episodes": limit_episodes,
                "episodes_planned": n_eps,
                "source_file": s.source_file,
            },
        )
        wall_start = time.perf_counter()
        res = asyncio.run(go(store))
        wall_seconds = time.perf_counter() - wall_start
        store.finish(
            status="completed",
            usage={
                **res.usage.__dict__,
                "schema_failures": res.schema_failures,
                "invalid_drop_beats": res.invalid_drop_beats,
                "missing_switch_to": res.missing_switch_to,
                "wall_seconds": round(wall_seconds, 2),
            },
            episodes=res.episodes_simulated,
        )

    console.print()
    console.print(f"[green]✓[/] {len(res.rows)} reactions across {res.episodes_simulated} episodes "
                  f"→ [bold]{run_dir(run_id)}[/]")
    if res.schema_failures:
        pct = res.schema_failures / (len(res.rows) + res.schema_failures)
        style = "red" if pct > 0.01 else "yellow"
        console.print(f"[{style}]![/] {res.schema_failures} schema failures ({pct:.2%}) — "
                      f"dropped from the dataset, so the curve is biased by exactly that much.")
    console.print(f"  Next: [bold]pocketsim report --run {run_id}[/]")


# ─────────────────────────────────────────────────────────────────────────────


def _metrics_for(run_id: str):
    meta = get_run(run_id)
    rows = load_reactions(run_id)

    # The market and the run's own beat map make the need-axis roll-ups possible. Both are
    # optional: a run recorded before the need axis existed still reports everything it
    # always did, minus the sections it has no data for.
    market = beats = None
    try:
        market = load_market(meta["market"])
    except Exception as e:
        console.print(f"[yellow]![/] Region roll-up unavailable — could not load market: {e}")
    try:
        _, beatmap = load_series(meta["series"])
        beats = beatmap.beats
    except Exception:
        pass

    return meta, compute(
        rows,
        run_id=run_id,
        series=meta["series"],
        market_name=meta["market"],
        population_size=meta["population_size"],
        total_episodes=meta["episodes_planned"],
        market=market,
        beats=beats,
    )


@app.command()
def report(
    run: str = typer.Option(..., "--run"),
    fmt: str = typer.Option("markdown", "--format", help="markdown · html · json · all"),
    open_html: bool = typer.Option(False, "--open", help="Open the HTML report in a browser."),
) -> None:
    """Turn raw reactions into the Fix List, retention curve, paywall call and cohort map.

    Free and instant — re-run it as often as you like without re-simulating.
    """
    try:
        meta, m = _metrics_for(run)
    except (KeyError, ValueError) as e:
        _fail(str(e))

    pop = None
    audit = None
    try:
        run_population = run_dir(run) / "input" / "population.json"
        pop = load_population(run_population)
        audit = audit_population(pop, load_market(meta["market"]), str(run_population))
    except Exception as e:
        console.print(f"[yellow]![/] Could not rebuild persona audit for learning report: {e}")

    paths = write_report(m, run_dir(run) / "report", meta=meta, population=pop, audit=audit)

    if fmt in ("markdown", "all"):
        from rich.markdown import Markdown
        console.print(Markdown(render_markdown(m)))
    if fmt == "json":
        console.print_json(paths["verdict"].read_text(encoding="utf-8"))

    console.print()
    for k, p in paths.items():
        console.print(f"  [dim]{k:<9}[/] {p}")

    if open_html:
        import webbrowser
        webbrowser.open(paths["html"].resolve().as_uri())


@app.command()
def compare(
    base: str = typer.Option(..., "--base", help="The original run."),
    against: str = typer.Option(..., "--against", help="The rewrite run."),
) -> None:
    """Diff two screenings — did the rewrite actually work, and by how much?

    Only valid on the same population: persona bias cancels in the difference, which is
    why relative claims survive miscalibration where absolute ones do not. If the two runs
    used different audiences this refuses to report a number.
    """
    try:
        base_meta, base_m = _metrics_for(base)
        new_meta, new_m = _metrics_for(against)
    except (KeyError, ValueError) as e:
        _fail(str(e))

    same = base_meta["population_fingerprint"] == new_meta["population_fingerprint"]
    # Same script AND same audience means nothing changed — so whatever this reports is
    # the noise floor, and it is the number that decides whether a real rewrite delta
    # means anything at all.
    is_null = same and base_meta["series"] == new_meta["series"]
    c = compare_metrics(base_m, new_m, same, is_null_test=is_null)

    from rich.markdown import Markdown
    console.print(Markdown(render_comparison_markdown(c)))

    out = run_dir(against) / "report" / f"compare_vs_{base}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(c.model_dump_json(indent=2), encoding="utf-8")
    console.print(f"\n  [dim]saved[/] {out}")

    if not same:
        raise typer.Exit(2)


# ─────────────────────────────────────────────────────────────────────────────


@history_app.command("list")
def history_list(limit: int = typer.Option(20, "--limit")) -> None:
    """What has been simulated."""
    runs = list_runs(limit)
    if not runs:
        console.print("[dim]no runs yet[/]")
        return
    t = Table("run", "series", "market", "eps", "listeners", "status", "population", box=None, pad_edge=False)
    for r in runs:
        status = {"completed": "[green]completed[/]", "failed": "[red]failed[/]"}.get(
            r["status"], f"[yellow]{r['status']}[/]"
        )
        t.add_row(
            r["run_id"], r["series"], r["market"],
            f"{r['episodes_simulated']}/{r['episodes_planned']}",
            str(r["population_size"]), status, r["population_fingerprint"],
        )
    console.print(t)


@history_app.command("status")
def history_status(run_id: str = typer.Argument(...)) -> None:
    """Details of one run."""
    try:
        console.print_json(json.dumps(get_run(run_id), indent=2))
    except KeyError as e:
        _fail(str(e))


@history_app.command("export")
def history_export(
    run_id: str = typer.Argument(...),
    out: Optional[Path] = typer.Option(None, "--out"),
) -> None:
    """Export a run's raw reactions as JSON."""
    try:
        rows = load_reactions(run_id)
    except (KeyError, ValueError) as e:
        _fail(str(e))
    blob = json.dumps(rows, indent=2, ensure_ascii=False)
    if out:
        out.write_text(blob, encoding="utf-8")
        console.print(f"[green]✓[/] {len(rows)} reactions → {out}")
    else:
        typer.echo(blob)


@app.command()
def calibrate(
    run: str = typer.Option(..., "--run"),
    actuals: Path = typer.Option(..., "--actuals", help="CSV: episode_no,actual_retention"),
) -> None:
    """[NOT YET ACTIVE] Fit simulated output against real retention curves.

    This is the stub that unlocks absolute claims. Today the reports say "episode 7 is the
    weakest in this script"; with 20-30 real Hindi retention curves to fit against, they
    can say "68th percentile of the catalogue at episode 20" instead.

    Deliberately inert rather than approximated — a calibration fitted on one series would
    look like validation while providing none.
    """
    console.print("[yellow]![/] calibrate is a documented stub, not an implementation.")
    console.print(
        "\nTo activate it you need [bold]20-30 completed series[/] with known retention curves, "
        "stratified by outcome — hits, mid-performers [italic]and[/] flops. A set of hits alone "
        "measures correlation but not discrimination, and discrimination is the whole product."
    )
    console.print(f"\n  run:     {run}\n  actuals: {actuals}")
    raise typer.Exit(3)


if __name__ == "__main__":  # pragma: no cover
    app()
