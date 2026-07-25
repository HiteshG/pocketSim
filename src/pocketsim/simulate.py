"""The panel loop — where a script meets an audience.

Iteration is **episode-major**: every active persona reacts to episode 1, then every
survivor reacts to episode 2, and so on. Persona-major would be equivalent in outcome
(each listener's state depends only on their own history) but far worse in practice:
with 300 listeners spread across 20 different episodes at once, the shared episode text
is never a stable prompt prefix and the cache never warms. Episode-major means exactly
one episode block is live at a time, hit by every persona in turn.

Within an episode the first call is fired alone and awaited before the rest fan out.
A prompt-cache entry only becomes readable once the response that created it has begun
returning, so firing all N at once means all N pay full price for the same prefix.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Sequence

from .config import Cohort, Market
from .ingest import BeatMap, Episode, Series
from .llm import LLMProvider, SchemaViolation, Usage
from .schema import REACTION_RESPONSE_FORMAT, ListenerState, Persona, Population, Reaction

MAX_EPISODE_CHARS = 40_000
MEMORY_WINDOW = 6

ProgressFn = Callable[[str], None]


# ─────────────────────────────────────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_TEMPLATE = """You are simulating ONE specific listener of a serialized audio-fiction \
series on Pocket FM, a paid audio platform. You are not an assistant and not a critic. \
You are this person, deciding what to do next with their time.

You have just finished listening to EPISODE {ep_no} of "{series}".

════════ THE EPISODE ════════
{episode_text}
════════ END OF EPISODE ════════

STORY BEATS IN THIS EPISODE (use these ids for drop_beat):
{beat_list}

════════ HOW TO ANSWER ════════

1. CONTINUING IS AN OPPORTUNITY COST, NOT A REVIEW.
   You are not being asked whether the episode was good. You are being asked what you
   actually do next with the minutes you have left. Real listeners abandon perfectly
   competent stories all the time because something else was easier. If you would drift
   away, say so plainly and name what you would switch to. Do not be polite about this.
   Dropping is a completely normal answer.

2. PAYING IS A SEPARATE QUESTION FROM ENJOYING.
   People love stories they will not pay for, and pay for stories they find mediocre
   because they cannot stand not knowing. Answer would_pay from your own wallet and your
   own spending habit, not from how much you liked the episode.

3. CRAVING IS MEASURED TWICE.
   craving_mid  — how badly you needed to know what happens next, MIDWAY through.
   craving_end  — how badly you need to know, now that it has ended.
   If the episode tied everything up neatly, craving_end should be LOW even if you
   enjoyed it. A satisfying ending and a reason to come back tomorrow are not the same
   thing.

   Use the whole scale. It is anchored:
     1-2   you genuinely do not care what happens next
     3-4   mild curiosity — you would not go looking for it
     5-6   interested, but it can wait days without bothering you
     7-8   you want the next episode soon
     9-10  you cannot comfortably stop here
   Most ordinary episodes of most serials land at 3 to 6. An episode that merely
   continues the plot competently is a 4 or a 5, not a 7. Reserve 8 and above for a
   real cliffhanger — something interrupted, threatened or about to be exposed.

4. COMMIT TO A PREDICTION.
   Say specifically what you think happens next. Guess. Do not hedge or list options.

5. drop_beat must be one of the beat ids listed above, or null if your attention held
   all the way through. Only name a beat if you genuinely drifted there.

6. USE THE PERSON'S BASE RATES.
   Mild curiosity is not enough. Most sampled listeners do not finish most stories they
   start, and busy listeners often leave even when an episode is competent. Set
   will_continue true only if this specific episode beat their usual switching habit,
   remaining time, alternatives, fatigue and completion rate. Set would_pay true only
   if the episode clears their own spending trigger, not because the story has a hook.

7. HOW LEAVING ACTUALLY HAPPENS — READ THIS BEFORE ANSWERING will_continue.
   Almost nobody quits a series at a bad episode. They quit at an ordinary one. The
   episode was fine, the moment passed, something else took the slot, and they never
   opened the next one. "It was competent and I still did not come back" is the single
   most common real outcome on this platform.

   So do NOT require the episode to be bad before you leave it. The question is not
   "was that good enough to quit over" — it is "of all the things I could do with the
   next twenty minutes, is this actually the one I pick, again, today."

   A competent episode that gives you no urgent reason to return is a drop for a
   listener whose completion rate is low, whose patience is short, or who is tired.
   Saying yes every time is the one answer that is definitely wrong: a person who
   continues through every episode of every series does not exist on this platform.

Answer in ENGLISH, even though the episode is not in English, so the whole team can read
your reasoning. Write in your own plain voice — short, concrete, first person."""


USER_TEMPLATE = """════════ WHO YOU ARE ════════
{realname}, {age}, {gender}. {profession} in {city} (tier-{city_tier} city).

{persona}

How you listen: {occasion}
Typical session about {session_minutes} minutes at {speed}x speed. You listen \
{privacy}. Roughly {daily} minutes a day in total.

Your history on Pocket FM: {tenure_months} months. {spend_note} For reference, \
{money_anchor}. You have unlocked {paid_episodes} episode(s) with coins in this series \
so far.{fatigue_note}

Your behavioural calibration:
- {completion_note}
- Your churn sensitivity is {churn_score}/10. The higher this is, the faster you leave \
when a beat feels familiar, padded, confusing or not worth this exact listening slot.
- You usually spend only when your end-of-episode need-to-know clears about \
{pay_trigger}/10.
- How you decide: {mbti_style}
- {interruption_note}
- {discovery_note}

Stories you gravitate towards: {top_genres}.

════════ WHAT YOU WANT FROM A STORY ════════
{drivers_block}
- You will stay with a story for about {commitment} episodes before the length itself \
starts to feel like a commitment you did not agree to.
- Patience for slow build-up: {patience_score}/10.
- You prefer {register_note}
{exploration_note}{anti_note}
These land for you:
{hooks_block}

These lose you — not "you dislike them", you stop listening:
{dealbreakers_block}

{pay_psychology}

════════ WHERE YOU ARE IN THIS STORY ════════
Episodes heard so far: {episodes_heard}
{memory_block}
{gap_block}
════════ RIGHT NOW ════════
You have about {remaining} minutes left in this listening session.

Episode {next_ep} is right there. Do you play it — or do you switch to something else \
({alternatives})?

Answer as yourself."""

FATIGUE_NOTE = (
    "\nYou have been on this platform a long time and have finished dozens of series. "
    "You recognise a setup you have heard before within a minute or two, and a familiar "
    "beat reads as a repeat rather than a comfort."
)

NEW_USER_NOTE = (
    "\nYou are new to audio fiction, so you have no accumulated fatigue with its tropes — "
    "but you also have no habit yet, and nothing keeps you here except this story."
)

# Spending is stated as a habit rather than a label. "You are a free spender" reads as
# generous when it means the opposite, and the pay question is too load-bearing to let
# an ambiguous phrase skew it.
SPEND_NOTE: dict[str, str] = {
    "free": "You almost never spend coins — you wait for episodes to unlock on their own, "
    "and paying to skip a wait feels like money wasted.",
    "occasional": "You spend coins now and then, only when a story has you badly enough "
    "that waiting is unbearable.",
    "regular": "You spend coins regularly to stay ahead of the free unlock schedule; "
    "it is a normal part of your month.",
    "whale": "You spend freely to unlock episodes. Waiting irritates you far more than "
    "the cost does.",
}


# A driver is what a listener is *for*, so it has to arrive as an appetite rather than a
# label. "You seek catharsis (high)" invites the model to perform a psychology profile;
# "you want to see people get what they deserve" is something a person can act on at an
# episode boundary.
DRIVER_PHRASING: dict[str, str] = {
    "catharsis": "you want the pressure to break — a scene that finally lets the feeling out",
    "justice_seeking": "you want to see people get what they deserve, on screen",
    "escapism": "you want to be somewhere other than where you are",
    "comfort": "you want to feel safe with these people — steadiness, not shocks",
    "belonging": "you want to be inside a family or a group, including its arguments",
    "power_fantasy": "you want to watch someone who was nothing become someone who matters",
    "wish_fulfillment": "you want the life you do not have, described in detail",
    "nostalgia": "you want the texture of a time you remember",
    "identity": "you want to see someone underestimated proved to be who they said they were",
    "hope": "you want a reason to believe it works out for people like these",
}

INTENSITY_PREFIX: dict[str, str] = {
    "high": "More than anything,",
    "high_again": "Just as much,",
    "med": "Also,",
    "low": "A little,",
}

REGISTER_NOTE: dict[str, str] = {
    "pulp": "plain, fast, loud writing. Flowery description reads as padding to you.",
    "mid": "writing that moves but is not crude — some texture, no showing off.",
    "literary": "careful writing. Clumsy dialogue and on-the-nose exposition pull you out.",
}


# How each type reaches a decision, phrased as behaviour rather than as a type label.
# Naming the type itself in the prompt would invite the model to perform a horoscope;
# describing the deliberation gives it something to actually do differently. These
# affect voice and decision style only — no number downstream reads them.
DISCOVERY_NOTE: dict[str, str] = {
    "ad": "You came to this from an ad that promised a specific thing — a confrontation, "
    "a secret, a reveal. You are still measuring the episodes against that promise, and "
    "you will feel cheated rather than merely bored if they never deliver it.",
    "in_app_recommendation": "The app suggested this to you. You have no particular "
    "loyalty to it and there are ten more suggestions behind it.",
    "browsing": "You found this yourself while browsing, so you chose it deliberately and "
    "will give it a little more rope than something pushed at you.",
    "friend": "Someone you know told you to listen to this. You will stay with it longer "
    "than it deserves, and you would feel slightly awkward telling them you gave up.",
}

MBTI_DECISION_STYLE: dict[str, str] = {
    "ISTJ": "You decide by whether this is holding up its end. You notice inconsistencies and broken setups, and once something has let you down twice you are quietly done with it.",
    "ISFJ": "You decide by how much you care what happens to these people. Plot matters less than whether someone you are invested in is left unsafe.",
    "INFJ": "You decide by whether the story seems to know what it is about. Aimlessness loses you faster than slowness does.",
    "INTJ": "You decide by whether the plot is coherent. A contrivance you can see through is worse to you than an episode where little happens.",
    "ISTP": "You decide fast and without agonising. If it stops being interesting you are simply gone, and you will not construct a reason.",
    "ISFP": "You decide on how it felt. Atmosphere and mood carry you further than plot mechanics; tonal ugliness pushes you out.",
    "INFP": "You decide by whether a character deserves your loyalty. You will forgive weak plotting for someone you believe in, and leave a well-built story with nobody in it.",
    "INTP": "You decide by whether the puzzle is worth solving. You enjoy working out the mechanism and lose interest the moment it becomes obvious.",
    "ESTP": "You decide on momentum. You want the next thing to happen now, and you will not sit through a set-up episode politely.",
    "ESFP": "You decide on enjoyment in the moment. If this stopped being fun you move on without regret and without a verdict.",
    "ENFP": "You decide on enthusiasm, which is real but not durable. You get gripped easily and drift just as easily when something newer appears.",
    "ENTP": "You decide by whether it can still surprise you. Once you can predict the shape of the next ten episodes you stop.",
    "ESTJ": "You decide by whether this is worth the time it is asking for. You are impatient with episodes that do not move and blunt about saying so.",
    "ESFJ": "You decide by whether you are still involved with these people. You stay loyal well past the point the writing earns it, then leave all at once.",
    "ENFJ": "You decide by whether the relationships are going somewhere. A story that stalls the people while advancing the plot loses you.",
    "ENTJ": "You decide by whether it respects your time. You have no patience for filler and you cut things loose decisively.",
}


def render_completion_note(persona: Persona, state: ListenerState) -> str:
    """State the listener's own abandonment history as arithmetic, not as a percentage.

    The first live run returned 100% continuation across 400 reactions. The personas were
    reasoning well — about remaining time, alternatives, whether the episode earned the
    slot — and then answering "yes" every time, because at any single boundary continuing
    is the locally rational choice. A bare "you finish 35% of series you start" does not
    bind: it reads as a statistic about someone else.

    Counting in series rather than percent makes the base rate a fact about *this* person
    with a consequence attached, and naming how deep they are gives it somewhere to bite.
    """
    rate = persona.historical_completion
    finished = max(1, round(rate * 10))
    abandoned = 10 - finished
    depth = state.episodes_heard

    note = (
        f"For every 10 series you start, you finish about {finished} and drop the other "
        f"{abandoned}. You almost never decide to quit one — you just stop opening it, "
        f"usually at an episode that was perfectly fine."
    )
    if depth == 0:
        return note + " You have not started this one yet."

    note += (
        f" You are {depth} episode{'s' if depth != 1 else ''} into this one, which is "
        f"exactly where most of those {abandoned} quietly ended."
    )

    # Survivorship correction. The second live run produced every one of its drops in
    # episodes 1-3 and then none at all across 4-8: having continued became its own
    # justification for continuing, so attrition stopped dead once a listener was
    # "invested". Real attrition keeps a hazard at every episode. Naming the streak turns
    # depth from evidence of commitment into the thing that needs justifying.
    if depth >= 3:
        note += (
            f" You have now chosen this series {depth} times in a row. For someone who "
            f"finishes {finished} in 10, that is already a longer run than you usually "
            f"manage — so the question is whether this is genuinely one of the {finished}, "
            f"or whether this is the episode where the run quietly ends. Having come this "
            f"far is not a reason by itself; most of the series you abandoned were ones you "
            f"had also come this far in."
        )
    return note


def render_needs(
    market: Market, persona: Persona
) -> dict[str, str]:
    """Render the need-region half of the persona into prompt blocks.

    Everything here resolves through the shared ontology at call time. Nothing about the
    six regions is written into this module, so a card edited in the YAML changes what
    every simulated listener wants with no code change — which is the property the Story
    Intelligence ontology asks for and the reason regions are not an enum in Python.
    """
    ontology = market.ontology
    region = ontology.region(persona.region_id)
    hooks, dealbreakers = ontology.bank_for(
        region, persona.drivers, persona.language_register, persona.narrative_patience
    )

    driver_lines = []
    seen_high = False
    for name in persona.primary_drivers or list(persona.drivers):
        phrase = DRIVER_PHRASING.get(name)
        if not phrase:
            continue
        level = persona.drivers[name]
        key = "high_again" if level == "high" and seen_high else level
        seen_high = seen_high or level == "high"
        driver_lines.append(f"- {INTENSITY_PREFIX[key]} {phrase}")

    exploration = (
        "- You try new series readily and drop them just as readily.\n"
        if persona.exploration_propensity >= 0.6
        else "- You stay with what already works for you rather than sampling widely.\n"
        if persona.exploration_propensity <= 0.35
        else ""
    )

    anti = ""
    if persona.anti_stereotype and region.anti_stereotype:
        # The declared low-probability variant. It is stated as a fact about this person
        # rather than as an exception to a type, because the listener does not experience
        # themselves as an exception to anything.
        anti = f"- Unusually for someone like you: {region.anti_stereotype.note}\n"

    return {
        "drivers_block": "\n".join(driver_lines) or "- You listen mostly out of habit.",
        "commitment": str(persona.commitment_tolerance),
        "patience_score": str(min(10, max(1, round(persona.narrative_patience * 10)))),
        "register_note": REGISTER_NOTE.get(persona.language_register, "writing that moves."),
        "exploration_note": exploration,
        "anti_note": anti,
        "hooks_block": "\n".join(f"- {h.text}" for h in hooks) or "- Nothing in particular.",
        "dealbreakers_block": "\n".join(f"- {d.text}" for d in dealbreakers)
        or "- Nothing in particular.",
        "pay_psychology": f"When you do spend: {region.pay_voice}" if region.pay_voice else "",
    }


def render_beats(beatmap: BeatMap, ep_no: int) -> str:
    beats = beatmap.for_episode(ep_no)
    if not beats:
        return "(no beat map available — set drop_beat to null)"
    return "\n".join(f"  [{b.beat_id}] {b.title} — {b.summary}" for b in beats)


def build_system(market: Market, series: Series, episode: Episode, beatmap: BeatMap) -> str:
    return SYSTEM_TEMPLATE.format(
        ep_no=episode.number,
        series=series.series,
        episode_text=episode.text[:MAX_EPISODE_CHARS],
        beat_list=render_beats(beatmap, episode.number),
    )


def build_user(
    market: Market,
    cohort: Cohort,
    persona: Persona,
    state: ListenerState,
    next_ep: int,
) -> str:
    if state.story_summary:
        memory_block = f"What you still remember:\n  {state.story_summary}"
        if state.unresolved_questions:
            qs = "\n  ".join(f"- {q}" for q in state.unresolved_questions[-3:])
            memory_block += f"\nQuestions still open in your head:\n  {qs}"
    else:
        memory_block = "This is your first episode of this series. You know nothing about it yet."

    if persona.session_pattern == "drip":
        gap_block = (
            f"\nAbout {int(persona.gap_hours)} hours have passed since the last episode. "
            "You have worked, scrolled, eaten and slept in between. Whatever did not stick "
            "has faded.\n"
            "You are not mid-session — you are deciding whether to pick this back up at "
            "all. That is a different and much harder question than 'shall I play one "
            "more', and it is the question most series quietly fail.\n"
        )
    else:
        gap_block = "\nYou are listening straight through — the last episode ended moments ago.\n"

    fatigue = ""
    if persona.is_veteran:
        fatigue = FATIGUE_NOTE
    elif persona.tenure_months <= 2:
        fatigue = NEW_USER_NOTE

    remaining = max(5, int(persona.session_minutes * 0.6))
    pay_trigger = min(10, max(2, round(1 + persona.pay_threshold * 9)))
    completion_note = render_completion_note(persona, state)

    return USER_TEMPLATE.format(
        realname=persona.realname,
        age=persona.age,
        gender=persona.gender,
        profession=persona.profession,
        city=persona.city,
        city_tier=persona.city_tier,
        persona=persona.persona,
        occasion=" ".join(cohort.occasion.split()),
        session_minutes=int(persona.session_minutes),
        speed=persona.playback_speed,
        privacy=persona.listening_privacy.replace("_", " "),
        daily=persona.avg_daily_minutes,
        tenure_months=persona.tenure_months,
        spend_note=SPEND_NOTE.get(persona.coin_spend_tier, ""),
        money_anchor=market.money_anchor,
        paid_episodes=state.paid_episodes,
        fatigue_note=fatigue,
        completion_note=completion_note,
        mbti_style=MBTI_DECISION_STYLE.get(persona.mbti, MBTI_DECISION_STYLE["ISTJ"]),
        interruption_note=(
            "Your listening gets broken into constantly — someone needs you, something "
            "boils over, a call comes. Episodes often end without you having really heard "
            "the last few minutes."
            if persona.interruption_load >= 0.6
            else "Your listening is mostly uninterrupted once you start."
            if persona.interruption_load <= 0.3
            else "Your listening gets interrupted sometimes, but you usually get through "
            "an episode."
        ),
        discovery_note=DISCOVERY_NOTE.get(
            persona.discovery_channel, DISCOVERY_NOTE["browsing"]
        ),
        churn_score=round(persona.churn_sensitivity * 10),
        pay_trigger=pay_trigger,
        top_genres=", ".join(g.replace("_", " ") for g in persona.top_genres(3)),
        episodes_heard=state.episodes_heard,
        memory_block=memory_block,
        gap_block=gap_block,
        remaining=remaining,
        next_ep=next_ep,
        alternatives=", ".join(market.alternatives[:4]),
        **render_needs(market, persona),
    )


# ─────────────────────────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────────────────────────


def decay_state(state: ListenerState, memories: list[str]) -> list[str]:
    """Drop-off listeners forget. Trims the oldest memory before the next episode.

    This is what makes the drip/binge distinction bite rather than being decoration: it
    asks whether the cliffhanger survived a night's sleep, which is the actual question
    for a listener who returns tomorrow rather than in ninety seconds.
    """
    return memories[1:] if len(memories) > 2 else memories


def apply_reaction(
    state: ListenerState, reaction: Reaction, memories: list[str], episode_no: int
) -> tuple[ListenerState, list[str]]:
    if reaction.memory_update:
        memories = [*memories, reaction.memory_update][-MEMORY_WINDOW:]
    state.episodes_heard = episode_no
    state.story_summary = " ".join(memories)
    if reaction.next_prediction:
        state.unresolved_questions = [*state.unresolved_questions, reaction.next_prediction][-3:]
    if reaction.would_pay:
        state.paid_episodes += 1
    if not reaction.will_continue:
        state.active = False
        state.dropped_at = episode_no
    return state, memories


# ─────────────────────────────────────────────────────────────────────────────
# Loop
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class SimResult:
    rows: list[dict] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    episodes_simulated: int = 0
    schema_failures: int = 0
    invalid_drop_beats: int = 0
    missing_switch_to: int = 0
    final_states: dict[str, ListenerState] = field(default_factory=dict)


async def simulate(
    provider: LLMProvider,
    market: Market,
    series: Series,
    beatmap: BeatMap,
    population: Population,
    run_id: str,
    limit_episodes: int | None = None,
    on_episode: Callable[[int, int, int, Usage], None] | None = None,
    on_rows: Callable[[list[dict]], None] | None = None,
    model: str | None = None,
) -> SimResult:
    cohorts = {c.id: c for c in market.cohorts}
    states = {p.persona_id: ListenerState(persona_id=p.persona_id) for p in population.personas}
    memories: dict[str, list[str]] = {p.persona_id: [] for p in population.personas}
    by_id = {p.persona_id: p for p in population.personas}

    episodes = series.episodes[: limit_episodes or len(series.episodes)]
    result = SimResult()

    for episode in episodes:
        active = [p for p in population.personas if states[p.persona_id].active]
        if not active:
            break

        system = build_system(market, series, episode, beatmap)
        next_ep = episode.number + 1
        valid_drop_beats = {b.beat_id for b in beatmap.for_episode(episode.number)}

        async def react(persona: Persona) -> tuple[str, Reaction | None]:
            st = states[persona.persona_id]
            if persona.session_pattern == "drip":
                memories[persona.persona_id] = decay_state(st, memories[persona.persona_id])
                st.story_summary = " ".join(memories[persona.persona_id])
            user = build_user(market, cohorts[persona.cohort_id], persona, st, next_ep)
            try:
                res = await provider.complete_json(
                    system=system, user=user, response_format=REACTION_RESPONSE_FORMAT, model=model
                )
                reaction = Reaction.model_validate(res.data)
                if reaction.drop_beat and valid_drop_beats and reaction.drop_beat not in valid_drop_beats:
                    result.invalid_drop_beats += 1
                    reaction.drop_beat = None
                if not reaction.will_continue and not reaction.switch_to:
                    result.missing_switch_to += 1
                return persona.persona_id, reaction
            except (SchemaViolation, ValueError):
                return persona.persona_id, None

        # Warm the shared prefix on one call before fanning out, so the other N-1 read
        # the cache instead of each writing their own copy of the same episode.
        first = await react(active[0])
        rest = await asyncio.gather(*(react(p) for p in active[1:])) if len(active) > 1 else []

        rows: list[dict] = []
        for pid, reaction in [first, *rest]:
            if reaction is None:
                result.schema_failures += 1
                continue
            persona = by_id[pid]
            states[pid], memories[pid] = apply_reaction(
                states[pid], reaction, memories[pid], episode.number
            )
            rows.append(
                {
                    "run_id": run_id,
                    "persona_id": pid,
                    "cohort_id": persona.cohort_id,
                    "region_id": persona.region_id,
                    "episode_no": episode.number,
                    "will_continue": int(reaction.will_continue),
                    "would_pay": int(reaction.would_pay),
                    "drop_beat": reaction.drop_beat,
                    "switch_to": reaction.switch_to,
                    "craving_mid": reaction.craving_mid,
                    "craving_end": reaction.craving_end,
                    "next_prediction": reaction.next_prediction,
                    "emotional_state": reaction.emotional_state,
                    "continue_reason": reaction.continue_reason,
                    "pay_reason": reaction.pay_reason,
                    "memory_update": reaction.memory_update,
                    "tenure_months": persona.tenure_months,
                }
            )

        result.rows.extend(rows)
        result.episodes_simulated = episode.number
        if on_rows:
            on_rows(rows)
        if on_episode:
            still_active = sum(1 for s in states.values() if s.active)
            on_episode(episode.number, len(active), still_active, provider.total)

    result.usage = provider.total
    result.final_states = states
    return result
