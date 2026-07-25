"""Ingest: raw script .txt → episodes → named story beats.

Splitting is done with a regex rather than an LLM because the scripts already carry
`Episode N` headers, and a deterministic split is one less thing that can silently
differ between a baseline run and a rewrite run.

Beat-mapping *is* an LLM pass. It exists so `drop_beat` means something: a persona
saying "I checked out at the wedding confrontation" is actionable for a writer, where
"I checked out somewhere in episode 14" is not.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from .config import Ontology
from .llm import LLMProvider
from .schema import Beat, beats_response_format

SERIES_DIR = Path("series")

# Tolerant of "Episode 1", "EPISODE 01:", "Ep. 1 -", "एपिसोड १२" and a trailing title.
EPISODE_HEADER = re.compile(
    r"^[^\S\n]*(?:Episode|EPISODE|Episodes?|Ep\.?|एपिसोड|भाग)"
    r"[^\S\n]*[-–—:.]?[^\S\n]*(\d+|[०-९]+)[^\S\n]*[-–—:.)]?[^\S\n]*(.*)$",
    re.MULTILINE,
)

_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


class Episode(BaseModel):
    number: int
    title: str
    text: str
    word_count: int
    char_count: int
    text_sha: str


class Series(BaseModel):
    series: str
    market: str
    source_file: str
    created_at: str
    episodes: list[Episode]

    @property
    def episode_numbers(self) -> list[int]:
        return [e.number for e in self.episodes]


class BeatMap(BaseModel):
    series: str
    model: str
    created_at: str
    beats: dict[str, list[Beat]]
    """Keyed by episode number as a string, because JSON object keys are strings."""

    def for_episode(self, number: int) -> list[Beat]:
        return self.beats.get(str(number), [])


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def split_episodes(raw: str) -> list[tuple[int, str, str]]:
    """Return ``(number, title, body)`` for each episode found in the script."""
    matches = list(EPISODE_HEADER.finditer(raw))
    if not matches:
        raise ValueError(
            "No episode headers found. Expected lines like 'Episode 1' / 'एपिसोड 1' "
            "at the start of a line. Check the file encoding is UTF-8."
        )

    out: list[tuple[int, str, str]] = []
    for i, m in enumerate(matches):
        number = int(m.group(1).translate(_DEVANAGARI_DIGITS))
        title = m.group(2).strip().strip("-–—:.") or f"Episode {number}"
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        body = raw[start:end].strip()
        if body:
            out.append((number, title, body))
    return out


def ingest_script(script_path: Path, series_name: str, market: str) -> Series:
    raw = script_path.read_text(encoding="utf-8")
    parts = split_episodes(raw)

    episodes = [
        Episode(
            number=n,
            title=t,
            text=body,
            word_count=len(body.split()),
            char_count=len(body),
            text_sha=_sha(body),
        )
        for n, t, body in parts
    ]
    episodes.sort(key=lambda e: e.number)

    counts = Counter(e.number for e in episodes)
    dupes = {number for number, count in counts.items() if count > 1}
    if dupes:
        raise ValueError(f"duplicate episode numbers in script: {sorted(dupes)}")

    return Series(
        series=series_name,
        market=market,
        source_file=str(script_path),
        created_at=datetime.now(UTC).isoformat(),
        episodes=episodes,
    )


BEAT_SYSTEM = """You are a story editor preparing an audio-fiction script for analysis.

Break the episode below into 5-10 sequential story BEATS covering the whole episode in
order. A beat is a unit of dramatic movement — an arrival, a confrontation, a reveal, a
decision, a reversal — not a paragraph or a scene heading.

Rules:
- Cover the episode from start to end. The first beat starts at the opening, the last
  beat ends at the final line.
- beat_id must be a short stable slug prefixed with its position: b1, b2, b3...
  e.g. "b4-wedding-confrontation".
- title and summary must be in ENGLISH even when the script is not, so downstream
  reports are readable by the whole team.
- Describe only what happens. Do not praise or criticise the writing.

Then read each beat structurally. This part IS a judgement, and it has to be an honest
one:
- `purpose` is what the beat does to the story. If a beat moves nothing, its purpose is
  "none" — say so. Every episode has beats that exist to fill time, and a beat map where
  everything has a purpose is useless for finding the one that does not.
- `removable` means the episode would lose nothing if you cut this beat. A beat that is
  both "none" and removable is filler, and naming it is the single most useful thing this
  pass produces.
- `emotional_intensity` and `suspense` are relative to the other beats in THIS episode,
  not to all fiction. Use the range; if every beat scores 7 the numbers say nothing.
- `hooks_hit` and `dealbreaker_id` may cite ONLY the listed IDs below, and only where the
  script actually contains that thing. An empty array is the correct and common answer.
  Never stretch a beat to fit a bank entry — a false citation is worse than no citation,
  because it will be read as evidence.

{bank_block}"""


def render_bank_block(ontology: Ontology) -> str:
    hooks = "\n".join(f"  [{e.id}] {e.text}" for e in ontology.hook_bank)
    dealbreakers = "\n".join(f"  [{e.id}] {e.text}" for e in ontology.dealbreaker_bank)
    return (
        "HOOKS you may cite in hooks_hit:\n"
        f"{hooks}\n\n"
        "DEALBREAKERS you may cite in dealbreaker_id:\n"
        f"{dealbreakers}"
    )


async def map_beats(
    provider: LLMProvider,
    series: Series,
    ontology: Ontology,
    model: str | None = None,
    max_chars: int = 24000,
) -> BeatMap:
    """Beat-map every episode concurrently.

    The hook and dealbreaker banks are injected from the shared ontology rather than
    written into the prompt, so the same edit that changes what listeners want changes
    what the beat map looks for. The enums in the response schema are built from the same
    lists, which means a citation to a nonexistent ID is a schema error rather than a
    plausible-looking fabrication.
    """
    model = model or provider.model
    system = BEAT_SYSTEM.format(bank_block=render_bank_block(ontology))
    response_format = beats_response_format(
        [e.id for e in ontology.hook_bank], [e.id for e in ontology.dealbreaker_bank]
    )

    async def one(ep: Episode) -> tuple[str, list[Beat]]:
        body = ep.text[:max_chars]
        user = f"EPISODE {ep.number}: {ep.title}\n\n{body}"
        res = await provider.complete_json(
            system=system,
            user=user,
            response_format=response_format,
            model=model,
        )
        beats = [Beat.model_validate(b) for b in res.data.get("beats", [])]
        return str(ep.number), beats

    pairs = await asyncio.gather(*(one(ep) for ep in series.episodes))
    return BeatMap(
        series=series.series,
        model=model,
        created_at=datetime.now(UTC).isoformat(),
        beats=dict(pairs),
    )


def series_dir(series_name: str) -> Path:
    return SERIES_DIR / series_name


def save_series(series: Series, beatmap: BeatMap) -> Path:
    d = series_dir(series.series)
    d.mkdir(parents=True, exist_ok=True)
    (d / "episodes.json").write_text(series.model_dump_json(indent=2), encoding="utf-8")
    (d / "beats.json").write_text(beatmap.model_dump_json(indent=2), encoding="utf-8")
    return d


def load_series(series_name: str) -> tuple[Series, BeatMap]:
    d = series_dir(series_name)
    ep_file, beat_file = d / "episodes.json", d / "beats.json"
    if not ep_file.exists():
        available = sorted(p.name for p in SERIES_DIR.glob("*")) if SERIES_DIR.exists() else []
        raise FileNotFoundError(
            f"series '{series_name}' not ingested. Run `pocketsim ingest` first. "
            f"Available: {available or '(none)'}"
        )
    series = Series.model_validate_json(ep_file.read_text(encoding="utf-8"))
    beatmap = (
        BeatMap.model_validate_json(beat_file.read_text(encoding="utf-8"))
        if beat_file.exists()
        else BeatMap(series=series_name, model="none", created_at="", beats={})
    )
    return series, beatmap


def list_series() -> list[dict]:
    if not SERIES_DIR.exists():
        return []
    out = []
    for d in sorted(SERIES_DIR.iterdir()):
        f = d / "episodes.json"
        if f.exists():
            meta = json.loads(f.read_text(encoding="utf-8"))
            out.append(
                {
                    "series": meta["series"],
                    "market": meta["market"],
                    "episodes": len(meta["episodes"]),
                    "created_at": meta["created_at"],
                }
            )
    return out
