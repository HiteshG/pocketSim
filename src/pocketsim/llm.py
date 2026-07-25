"""Provider abstraction: one interface, three backends.

    openai-api   Production. Strict Structured Outputs guarantee parseable reactions,
                 async fan-out, and automatic prefix caching on the shared episode block.
    codex-cli    Free iteration on a Codex CLI subscription. Best-effort JSON with a
                 repair retry, since an agent CLI gives no schema guarantee.
    mock         Deterministic, offline, zero cost. Exists so the whole pipeline —
                 including the null test — can be exercised without an API key.

Callers pass the *stable* content as ``system`` and the *variable* content as ``user``.
That ordering is load-bearing: OpenAI caches on prefix, so putting the episode text
(identical across every persona) first means its token weight is paid roughly once per
episode instead of once per persona.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shlex
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# USD per 1M tokens: (uncached input, cached input, output).
# Unknown models still report token counts; cost is reported as None rather than guessed.
PRICING: dict[str, tuple[float, float, float]] = {
    "gpt-5.5": (5.00, 0.50, 30.00),
    "gpt-5.4": (2.50, 0.25, 15.00),
    "gpt-5.4-nano": (0.20, 0.02, 1.25),
    "o4-mini": (0.55, 0.055, 2.20),
}

DEFAULT_MODEL = os.getenv("POCKETSIM_MODEL", "gpt-5.4")
DEFAULT_UTILITY_MODEL = os.getenv("POCKETSIM_UTILITY_MODEL", DEFAULT_MODEL)
DEFAULT_CODEX_MODEL = os.getenv("POCKETSIM_CODEX_MODEL", os.getenv("POCKETSIM_MODEL", "gpt-5.5"))


def provider_default_model(provider: str) -> str:
    if provider == "codex-cli":
        return DEFAULT_CODEX_MODEL
    if provider == "mock":
        return "mock"
    return DEFAULT_MODEL


@dataclass
class Usage:
    prompt_tokens: int = 0
    cached_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    cost_usd: float | None = 0.0

    def __add__(self, other: Usage) -> Usage:
        cost: float | None
        if self.cost_usd is None or other.cost_usd is None:
            cost = None
        else:
            cost = self.cost_usd + other.cost_usd
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            calls=self.calls + other.calls,
            cost_usd=cost,
        )

    @property
    def cache_hit_rate(self) -> float:
        return self.cached_tokens / self.prompt_tokens if self.prompt_tokens else 0.0

    def summary(self) -> str:
        cost = f"${self.cost_usd:.2f}" if self.cost_usd is not None else "n/a"
        return (
            f"{self.calls} calls · {self.prompt_tokens:,} in "
            f"({self.cache_hit_rate:.0%} cached) · {self.completion_tokens:,} out · {cost}"
        )


def price(model: str, prompt: int, cached: int, completion: int) -> float | None:
    rates = PRICING.get(model)
    if rates is None:
        return None
    uncached_in, cached_in, out = rates
    fresh = max(prompt - cached, 0)
    return (fresh * uncached_in + cached * cached_in + completion * out) / 1_000_000


@dataclass
class LLMResult:
    data: dict[str, Any]
    usage: Usage
    raw: str = ""


class SchemaViolation(RuntimeError):
    """Raised when a provider could not be made to return schema-valid JSON."""


class LLMProvider(ABC):
    name: str = "base"

    def __init__(self, model: str = DEFAULT_MODEL, concurrency: int = 16) -> None:
        self.model = model
        self._sem = asyncio.Semaphore(concurrency)
        self.total = Usage()

    @abstractmethod
    async def _call(self, system: str, user: str, response_format: dict, model: str) -> LLMResult: ...

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        response_format: dict[str, Any],
        model: str | None = None,
    ) -> LLMResult:
        async with self._sem:
            result = await self._call(system, user, response_format, model or self.model)
        self.total = self.total + result.usage
        return result

    async def aclose(self) -> None:  # pragma: no cover - default no-op
        return None


# ─────────────────────────────────────────────────────────────────────────────
# OpenAI
# ─────────────────────────────────────────────────────────────────────────────


class OpenAIProvider(LLMProvider):
    name = "openai-api"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        concurrency: int = 16,
        max_retries: int = 5,
    ) -> None:
        super().__init__(model, concurrency)
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pip install openai") from exc
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Export it, put it in .env, "
                "or use --provider codex-cli / --provider mock."
            )
        self._client = AsyncOpenAI()
        self.max_retries = max_retries

    async def _call(self, system: str, user: str, response_format: dict, model: str) -> LLMResult:
        from openai import APIStatusError, RateLimitError

        delay = 2.0
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = await self._client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    response_format=response_format,
                )
                break
            except (RateLimitError, APIStatusError) as exc:
                status = getattr(exc, "status_code", None)
                if isinstance(exc, APIStatusError) and status is not None and status < 500 and status != 429:
                    raise
                last = exc
                if attempt == self.max_retries - 1:
                    raise
                await asyncio.sleep(delay)
                delay *= 2
        else:  # pragma: no cover
            raise SchemaViolation(f"exhausted retries: {last}")

        text = resp.choices[0].message.content or ""
        u = resp.usage
        cached = 0
        details = getattr(u, "prompt_tokens_details", None)
        if details is not None:
            cached = getattr(details, "cached_tokens", 0) or 0

        usage = Usage(
            prompt_tokens=u.prompt_tokens,
            cached_tokens=cached,
            completion_tokens=u.completion_tokens,
            calls=1,
            cost_usd=price(model, u.prompt_tokens, cached, u.completion_tokens),
        )
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:  # strict mode should make this unreachable
            raise SchemaViolation(f"strict mode returned unparseable JSON: {text[:400]}") from exc
        return LLMResult(data=data, usage=usage, raw=text)

    async def aclose(self) -> None:
        await self._client.close()


# ─────────────────────────────────────────────────────────────────────────────
# Codex CLI
# ─────────────────────────────────────────────────────────────────────────────

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(text: str) -> dict[str, Any]:
    """Pull the outermost JSON object out of arbitrary CLI chatter.

    An agent CLI wraps answers in prose, banners and fenced blocks, so unlike the API
    path we cannot trust the response to be bare JSON. Tries fenced blocks first, then
    the widest balanced-looking span.
    """
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    for candidate in reversed(fenced):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    match = _JSON_BLOCK.search(text)
    if match:
        blob = match.group(0)
        for end in range(len(blob), 0, -1):
            if blob[end - 1] != "}":
                continue
            try:
                return json.loads(blob[:end])
            except json.JSONDecodeError:
                continue
    raise SchemaViolation(f"no JSON object found in output: {text[:400]}")


class CodexCLIProvider(LLMProvider):
    """Drives the Codex CLI as a subprocess. Zero marginal cost, no schema guarantee.

    Intended for persona synthesis and smoke tests, not for production runs — see the
    provider-parity check in the README before trusting it for anything reported.

    The invocation is configurable because CLI flags move faster than this file:
        POCKETSIM_CODEX_CMD="codex exec --skip-git-repo-check --ephemeral --ignore-rules --sandbox read-only --color never -"
    The prompt is written to stdin.
    """

    name = "codex-cli"

    def __init__(self, model: str = DEFAULT_CODEX_MODEL, concurrency: int = 4) -> None:
        # Deliberately lower default concurrency: these are processes, not sockets.
        super().__init__(model, concurrency)
        self.cmd = os.getenv(
            "POCKETSIM_CODEX_CMD",
            f"{os.getenv('POCKETSIM_CODEX_BIN', 'codex')} exec "
            "-c 'model_reasoning_effort=\"low\"' "
            "--skip-git-repo-check --ephemeral --ignore-rules --sandbox read-only "
            "--color never -",
        )

    def _argv(self, output_path: Path, schema_path: Path, model: str) -> list[str]:
        if "{output}" in self.cmd or "{schema}" in self.cmd:
            argv = shlex.split(self.cmd.format(output=str(output_path), schema=str(schema_path)))
        else:
            argv = shlex.split(self.cmd)

        prompt_arg = len(argv) - 1 if argv and argv[-1] == "-" else len(argv)
        if "--model" not in argv and "-m" not in argv:
            argv[prompt_arg:prompt_arg] = ["--model", model]
            prompt_arg += 2
        if "--output-last-message" not in argv and "-o" not in argv:
            argv[prompt_arg:prompt_arg] = ["--output-last-message", str(output_path)]
            prompt_arg += 2
        if "--output-schema" not in argv:
            argv[prompt_arg:prompt_arg] = ["--output-schema", str(schema_path)]
        return argv

    async def _run(self, prompt: str, schema: dict[str, Any], model: str) -> str:
        with tempfile.TemporaryDirectory(prefix="pocketsim-codex-") as tmp:
            output_path = Path(tmp) / "last-message.json"
            schema_path = Path(tmp) / "schema.json"
            schema_path.write_text(json.dumps(schema), encoding="utf-8")

            proc = await asyncio.create_subprocess_exec(
                *self._argv(output_path, schema_path, model),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await proc.communicate(prompt.encode())
            if proc.returncode != 0:
                detail = (err + out).decode(errors="replace").strip()
                raise SchemaViolation(
                    f"codex exited {proc.returncode}: {detail[:2000]}\n"
                    f"(set POCKETSIM_CODEX_CMD if your CLI's non-interactive flags differ)"
                )
            if output_path.exists() and output_path.stat().st_size:
                return output_path.read_text(encoding="utf-8")
            return out.decode()

    async def _call(self, system: str, user: str, response_format: dict, model: str) -> LLMResult:
        schema = response_format["json_schema"]["schema"]
        instruction = (
            "Respond with ONE JSON object and nothing else — no prose, no code fence, "
            "no commentary. It must conform exactly to this JSON Schema:\n"
            f"{json.dumps(schema)}"
        )
        prompt = f"{system}\n\n{user}\n\n{instruction}"

        text = await self._run(prompt, schema, model)
        try:
            data = extract_json(text)
        except SchemaViolation:
            # One repair attempt: hand the bad output back and ask for JSON only.
            repair = (
                f"{instruction}\n\nYour previous output was not valid JSON. "
                f"Re-emit it as a single valid JSON object only.\n\n---\n{text[:4000]}"
            )
            data = extract_json(await self._run(repair, schema, model))

        missing = [k for k in schema.get("required", []) if k not in data]
        if missing:
            raise SchemaViolation(f"codex output missing required keys {missing}")

        return LLMResult(data=data, usage=Usage(calls=1, cost_usd=0.0), raw=text)


# ─────────────────────────────────────────────────────────────────────────────
# Mock
# ─────────────────────────────────────────────────────────────────────────────


class MockProvider(LLMProvider):
    """Deterministic offline provider. Same input → same output, always.

    This is what makes the null test possible without spending anything: run a script
    against itself and the delta must be exactly zero, because nothing but the prompt
    drives the answer. It produces *structurally* valid, plausibly-shaped data — never
    treat its numbers as findings.
    """

    name = "mock"

    def __init__(self, model: str = "mock", concurrency: int = 64) -> None:
        super().__init__(model, concurrency)

    # A handful of stock values so mock populations survive the diversity audit
    # rather than collapsing to one repeated name — the audit is meant to catch real
    # mode collapse, not to fail on the offline fixture.
    _FIRST = (
        "Aarav Aditi Ajay Akhilesh Alka Amrita Anand Anjali Ankur Anusha Arti Ashwin "
        "Basit Bhavesh Bhavna Chetna Chirag Damini Darshan Deepa Devendra Dhruv Divya "
        "Ekta Eshaan Farhana Gaurav Geeta Gopal Hansa Harish Hemlata Ishita Irfan "
        "Jaya Jitendra Jyoti Kabir Kalpana Kamal Kavita Kiran Komal Lalita Latika "
        "Madhav Mala Manish Meena Mohit Mukesh Nandini Naresh Nasreen Neha Nikhil "
        "Omkar Pallavi Parul Pawan Poonam Prakash Priya Qadir Rachana Rajesh Rakhi "
        "Ramesh Rekha Rohit Rukmini Sadiq Sameer Sangeeta Sanjay Saroj Shalini "
        "Shankar Shreya Sneha Sudhir Sunita Suresh Swati Tanvi Tarun Umesh Urmila "
        "Vandana Varun Vasanti Vikas Vimla Vinod Wasim Yashodha Yogesh Zoya"
    ).split()
    _FIRST_BY_GENDER = {
        "female": (
            "Aditi Alka Amrita Anjali Anusha Arti Bhavna Chetna Damini Deepa Divya "
            "Ekta Farhana Geeta Hansa Hemlata Ishita Jaya Jyoti Kalpana Kavita Kiran "
            "Komal Lalita Latika Mala Meena Nandini Nasreen Neha Pallavi Parul Poonam "
            "Priya Rachana Rakhi Rekha Rukmini Sangeeta Saroj Shalini Shreya Sneha "
            "Sunita Swati Tanvi Urmila Vandana Vasanti Vimla Yashodha Zoya"
        ).split(),
        "male": (
            "Aarav Ajay Akhilesh Anand Ankur Ashwin Basit Bhavesh Chirag Darshan "
            "Devendra Dhruv Eshaan Gaurav Gopal Harish Irfan Jitendra Kabir Kamal "
            "Madhav Manish Mohit Mukesh Naresh Nikhil Omkar Pawan Prakash Qadir "
            "Rajesh Ramesh Rohit Sadiq Sameer Sanjay Shankar Sudhir Suresh Tarun "
            "Umesh Varun Vikas Vinod Wasim Yogesh"
        ).split(),
    }
    _LAST = (
        "Agarwal Ansari Banerjee Bhandari Bhatt Bisht Chauhan Chourasia Das Deshmukh "
        "Dubey Gowda Gupta Hegde Iyer Jadhav Jaiswal Jha Joshi Kadam Kamble Kaur "
        "Khan Kulkarni Kumar Lodha Mahajan Malhotra Mandal Mehta Menon Mishra Nair "
        "Nayak Ojha Pandey Panicker Patel Pathak Pillai Prasad Purohit Rana Rathore "
        "Raut Rawat Reddy Sahu Saini Sarkar Saxena Sengupta Shah Sharma Shetty Shukla "
        "Singh Sinha Solanki Sood Tandon Thakur Tiwari Tripathi Trivedi Varma Verma "
        "Vyas Wagh Yadav Zutshi"
    ).split()
    _JOB = (
        "Delivery rider,Cab driver,Auto driver,Tailor,Bank teller,Nurse,Schoolteacher,"
        "Shop owner,Field surveyor,Beautician,Warehouse picker,Pharmacist,Data entry operator,"
        "LIC agent,Security guard,Line operator,Barista,Lab technician,Salon assistant,"
        "Tuition teacher,Courier rider,Electrician,Plumber,Carpenter,Welder,Painter,"
        "Mobile repair technician,Photocopy shop operator,Kirana store helper,Milk vendor,"
        "Vegetable seller,Cook,Housekeeping staff,Ward boy,Compounder,ASHA worker,"
        "Anganwadi worker,Postal assistant,Railway ticket clerk,Toll booth operator,"
        "Petrol pump attendant,Hotel front-desk staff,Waiter,Baker,Sweet shop assistant,"
        "Garment factory operator,Loom operator,Printing press operator,Bookbinder,"
        "Xerox operator,Cyber cafe attendant,Insurance surveyor,Loan recovery agent,"
        "Real estate broker,Property caretaker,Gym trainer,Yoga instructor,Music tutor,"
        "Dance teacher,Wedding decorator,Event helper,Videographer,Studio assistant,"
        "Graphic designer,Content writer,Customer support executive,Telecaller,"
        "Field sales executive,Medical representative,Chemist shop owner,Optician,"
        "Dental assistant,Physiotherapy assistant,Veterinary assistant,Poultry farm hand,"
        "Dairy supervisor,Tractor mechanic,Farm equipment dealer,Seed shop owner,"
        "Fertiliser dealer,Grain trader,Truck driver,Bus conductor,Ferry operator,"
        "Software support engineer,QA tester,Network technician,CCTV installer,"
        "Solar panel installer,Water tanker operator,Scrap dealer,Junior accountant"
    ).split(",")
    _SWITCH_TO = (
        "Instagram reels",
        "YouTube shorts",
        "film songs",
        "cricket highlights",
        "another Pocket FM revenge story",
        "a family phone call",
        "silence during the ride",
    )
    _PREDICTIONS = (
        "Aryan will reveal that the land deal is tied to an old promise.",
        "Ananya will find a hidden document that changes who owns the village land.",
        "A family elder will turn out to be protecting the real culprit.",
        "The rich buyer will offer help, but it will come with a marriage condition.",
        "The next episode will expose a betrayal inside Ananya's own house.",
        "A missing recording will prove the father's death was not simple.",
        "The rival family will frame Ananya before she can show the evidence.",
        "Aryan and Ananya will be forced to work together against a third person.",
    )
    _EMOTIONS = (
        "curious but wary",
        "hooked",
        "mildly bored",
        "angry",
        "confused",
        "suspicious",
        "impatient",
        "satisfied",
    )

    @staticmethod
    def _rand(seed_text: str, salt: str) -> float:
        digest = hashlib.sha256(f"{seed_text}|{salt}".encode()).digest()
        return int.from_bytes(digest[:8], "big") / 2**64

    @staticmethod
    def _item_block(seed_text: str, pos: int) -> str:
        match = re.search(rf"^#{pos}\n(?P<block>.*?)(?=^#\d+|\Z)", seed_text, re.MULTILINE | re.DOTALL)
        return match.group("block") if match else seed_text

    def _leaf(self, key: str, spec: dict, seed: str, salt: str, pos: int, ctx: dict) -> Any:
        types = spec.get("type")
        types = types if isinstance(types, list) else [types]
        r = self._rand(seed, salt)
        item_block = self._item_block(seed, pos)

        if key == "index":
            return pos
        if key == "will_continue":
            return r < ctx["keep_p"]
        if key == "would_pay":
            return r < 0.34
        if key == "drop_beat":
            beats = ctx.get("beats") or []
            return beats[int(r * len(beats))] if beats and r < 0.30 else None
        if key == "switch_to":
            return None if ctx.get("continued", True) else self._SWITCH_TO[int(r * len(self._SWITCH_TO))]
        if key == "beat_id":
            return f"b{pos + 1}-mock-beat"
        if key == "purpose":
            # Every third beat is filler, so the offline path actually exercises the
            # filler detector instead of producing a beat map where nothing is ever wrong.
            return "none" if pos % 3 == 2 else ("payoff" if pos % 3 == 1 else "escalate")
        if key == "removable":
            return pos % 3 == 2
        if key == "churn_risk":
            return "boredom" if pos % 3 == 2 else "none"
        if key == "dealbreaker_id":
            return None
        if key in {"emotional_intensity", "suspense"}:
            return 1 + int(r * 9)
        if key == "realname":
            gender_match = re.search(r"age\s+\d+,\s*([a-z_ -]+),", item_block, re.IGNORECASE)
            gender = gender_match.group(1).strip().lower() if gender_match else ""
            first_pool = self._FIRST_BY_GENDER.get(gender, self._FIRST)
            f = first_pool[int(self._rand(seed, salt + "f") * len(first_pool))]
            lst = self._LAST[int(self._rand(seed, salt + "l") * len(self._LAST))]
            return f"{f} {lst}"
        if key == "profession":
            jobs_match = re.search(r"typical jobs for this cohort:\s*(.+)", item_block)
            jobs = [j.strip() for j in jobs_match.group(1).split(",")] if jobs_match else []
            jobs = [j for j in jobs if j]
            pool = jobs or self._JOB
            return pool[int(r * len(pool))]
        if key == "persona":
            return (
                "[mock] Synthetic offline persona used to exercise the pipeline without "
                "an API key. Listens during a daily commute on a mid-range Android phone "
                "with a limited data pack, competing with reels and music for the same slot. "
                f"Seed {r:.4f}."
            )
        if key == "continue_reason":
            return (
                "I would continue because the episode still leaves an open thread."
                if ctx.get("continued", True)
                else "I would stop because the next question is not urgent enough for this slot."
            )
        if key == "pay_reason":
            return (
                "I would spend only if the locked episode resolves the immediate cliffhanger."
                if ctx.get("would_pay", False)
                else "I would wait for the free unlock unless the hook became sharper."
            )
        if key == "next_prediction":
            return self._PREDICTIONS[int(r * len(self._PREDICTIONS))]
        if key == "emotional_state":
            return self._EMOTIONS[int(r * len(self._EMOTIONS))]
        if key == "memory_update":
            return "The listener remembers the unresolved land promise and who might benefit from hiding it."

        # An enum must be honoured before the type fallbacks, or the mock returns
        # "[mock] purpose (0.412)" and every strict-schema consumer downstream rejects it.
        choices = spec.get("enum")
        if choices:
            usable = [c for c in choices if c is not None] or choices
            return usable[int(r * len(usable))]

        if "integer" in types:
            return 1 + int(r * 10)
        if "number" in types:
            return round(r, 3)
        if "boolean" in types:
            return r < 0.5
        if "null" in types and r < 0.25:
            return None
        return f"[mock] {key} ({r:.3f})"

    # Keys whose mock value is the whole field rather than one element of it. Checked
    # before the array branch below, which would otherwise call the leaf handler once per
    # item and nest the result one level too deep.
    _WHOLE_FIELD: dict[str, Any] = {"hooks_hit": []}

    def _gen(self, key: str, spec: dict, seed: str, salt: str, pos: int, ctx: dict, n: int) -> Any:
        if key in self._WHOLE_FIELD:
            return self._WHOLE_FIELD[key]
        types = spec.get("type")
        types = types if isinstance(types, list) else [types]
        if "array" in types:
            item = spec.get("items", {"type": "string"})
            length = n if item.get("type") == "object" else 3
            return [self._gen(key, item, seed, f"{salt}[{i}]", i, ctx, n) for i in range(length)]
        if "object" in types:
            return {
                k: self._gen(k, v, seed, f"{salt}.{k}", pos, ctx, n)
                for k, v in spec.get("properties", {}).items()
            }
        return self._leaf(key, spec, seed, salt, pos, ctx)

    async def _call(self, system: str, user: str, response_format: dict, model: str) -> LLMResult:
        schema = response_format["json_schema"]["schema"]
        seed = system + user

        # Episode number nudges a decay so retention curves come out shaped like curves.
        ep_match = re.search(r"EPISODE\s+(\d+)", system + user)
        ep = int(ep_match.group(1)) if ep_match else 1
        ctx: dict[str, Any] = {
            "keep_p": max(0.55, 0.985 - 0.018 * ep),
            "beats": re.findall(r"\[(b\d+[a-z0-9\-]*)\]", system),
        }
        # Batched prompts number their items "#0", "#1", ... — mirror that count so
        # array-of-object responses line up with what the caller asked for.
        n_items = len(re.findall(r"^#\d+$", user, re.MULTILINE)) or 6

        data: dict[str, Any] = {}
        for key, spec in schema.get("properties", {}).items():
            data[key] = self._gen(key, spec, seed, key, 0, ctx, n_items)
            if key == "will_continue":
                ctx["continued"] = data[key]
                data["switch_to"] = None if data[key] else "Instagram reels"
            if key == "would_pay":
                ctx["would_pay"] = data[key]

        for key in schema.get("required", []):
            data.setdefault(key, None)

        return LLMResult(data=data, usage=Usage(calls=1, cost_usd=0.0), raw=json.dumps(data))


PROVIDERS: dict[str, type[LLMProvider]] = {
    "openai-api": OpenAIProvider,
    "codex-cli": CodexCLIProvider,
    "mock": MockProvider,
}


def get_provider(name: str, model: str | None = None, concurrency: int | None = None) -> LLMProvider:
    try:
        cls = PROVIDERS[name]
    except KeyError:
        raise ValueError(f"unknown provider '{name}'. Choose from {sorted(PROVIDERS)}") from None
    kwargs: dict[str, Any] = {}
    kwargs["model"] = model or provider_default_model(name)
    if concurrency:
        kwargs["concurrency"] = concurrency
    return cls(**kwargs)
