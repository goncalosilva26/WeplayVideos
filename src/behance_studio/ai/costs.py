"""Cost estimates, usage metering and spending limits for AI providers.

What this module guarantees:

* **Disclosure before spending.** Every AI step can be estimated before it
  runs (tokens and, when the model's price is known, money). The desktop
  app shows the estimate and asks for confirmation before paid work starts.
* **Real usage, not guesses, for accounting.** After each request the token
  counts reported by the provider (``usage`` in the response) are recorded;
  the estimate is only used when a provider reports nothing.
* **Spending limits.** A per-generation limit and an optional monthly limit
  stop *new* requests once reached. A request is authorised only when the
  amount already spent plus that request's expected cost fits the limit, so
  the limit can only be exceeded by the requests already in flight (at most
  three small asset-recognition requests run in parallel) answering longer
  than expected.
* **No invented prices.** Built-in prices exist only for models whose list
  price is documented here (Anthropic, USD per million tokens, October
  2026). For any other cloud model the user enters the price in Settings;
  until then costs are shown as unknown and — if a spending limit is set —
  paid requests are not made at all, because the limit could not be
  enforced.

Local providers (Ollama, LM Studio, … on this computer or network) are free.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from behance_studio.core.errors import ProviderError
from behance_studio.core.fsutil import atomic_write_json, read_json
from behance_studio.core.logging_setup import get_logger

log = get_logger(__name__)

# USD per million tokens (input, output). Source: Anthropic model list,
# October 2026. Prices change: users can override them in Settings.
KNOWN_PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5": (5.0, 25.0),
}
PRICES_AS_OF = "October 2026"

# Rough sizes used for estimates only (actual usage comes from the provider).
CHARS_PER_TOKEN = 3.5
IMAGE_TOKENS_PER_PIXEL = 1 / 750  # ≈ one token per 28×28 patch, rounded up
# Expected reasoning tokens by effort for models that always think.
THINKING_EXPECTED = {"low": 400, "medium": 1600, "high": 4000}
THINKING_HEADROOM = {"low": 2000, "medium": 6000, "high": 12000}


class BudgetExceeded(ProviderError):
    """A request was not sent because it would exceed a spending limit."""


class PriceUnknown(ProviderError):
    """A paid request was not sent because its cost cannot be bounded."""


@dataclass(frozen=True)
class Prices:
    input_per_mtok: float
    output_per_mtok: float
    source: str  # "built-in" | "settings" | "free"

    def cost(self, input_tokens: float, output_tokens: float) -> float:
        return (input_tokens * self.input_per_mtok + output_tokens * self.output_per_mtok) / 1_000_000


def resolve_prices(kind: str, model: str, is_local: bool, ai_settings=None) -> Prices | None:
    """Prices for this provider/model, or None when unknown."""
    if kind == "local" and is_local:
        return Prices(0.0, 0.0, "free")
    if ai_settings is not None:
        pin = float(getattr(ai_settings, "price_input_per_mtok", 0.0) or 0.0)
        pout = float(getattr(ai_settings, "price_output_per_mtok", 0.0) or 0.0)
        if pin > 0 or pout > 0:
            return Prices(pin, pout, "settings")
    if kind == "anthropic":
        base = (model or "").strip().lower()
        for name, (pin, pout) in KNOWN_PRICES.items():
            if base == name or base.startswith(name + "-"):  # dated snapshots of the same model
                return Prices(pin, pout, "built-in")
    if kind == "local":  # a "local" server on a remote address: unknown, treat as paid
        return None
    return None


def text_tokens(*texts: str) -> int:
    return int(math.ceil(sum(len(t or "") for t in texts) / CHARS_PER_TOKEN))


def image_tokens(width: int, height: int, kind: str = "anthropic") -> int:
    if kind in ("openai", "local"):
        return 85  # previews are sent with detail "low": a fixed small cost
    return int(math.ceil(max(1, width) * max(1, height) * IMAGE_TOKENS_PER_PIXEL))


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    reported: bool = False  # True when the provider reported these numbers

    @classmethod
    def from_response(cls, data: dict[str, Any]) -> "Usage":
        u = data.get("usage") if isinstance(data, dict) else None
        if not isinstance(u, dict):
            return cls()

        def num(key: str) -> int:
            try:
                return max(0, int(u.get(key) or 0))
            except (TypeError, ValueError):
                return 0

        if "input_tokens" in u or "output_tokens" in u:  # Anthropic Messages API
            return cls(num("input_tokens"), num("output_tokens"), num("cache_creation_input_tokens"), num("cache_read_input_tokens"), True)
        if "prompt_tokens" in u or "completion_tokens" in u:  # OpenAI-compatible
            return cls(num("prompt_tokens"), num("completion_tokens"), 0, 0, True)
        return cls()

    def cost(self, prices: Prices | None) -> float | None:
        if prices is None:
            return None
        # Cache writes bill at 1.25× input, cache reads at ≤0.1× input.
        effective_in = self.input_tokens + 1.25 * self.cache_write_tokens + 0.1 * self.cache_read_tokens
        return prices.cost(effective_in, self.output_tokens)


@dataclass
class RequestEstimate:
    purpose: str
    input_tokens: int
    output_tokens: int  # expected (answer + typical reasoning)
    max_output_tokens: int  # upper bound the request allows
    images: int = 0

    def cost(self, prices: Prices | None) -> float | None:
        return None if prices is None else prices.cost(self.input_tokens, self.output_tokens)

    def max_cost(self, prices: Prices | None) -> float | None:
        return None if prices is None else prices.cost(self.input_tokens, self.max_output_tokens)


@dataclass
class CostEstimate:
    """What an AI-assisted generation is expected to send and cost."""

    provider: str
    model: str
    prices: Prices | None
    may_bill: bool
    items: list[tuple[str, int, RequestEstimate]] = field(default_factory=list)  # (label, count, per-request)
    run_limit: float = 0.0
    monthly_limit: float = 0.0
    month_spent: float = 0.0
    notes: list[str] = field(default_factory=list)

    def add(self, label: str, count: int, est: RequestEstimate) -> None:
        if count > 0:
            self.items.append((label, count, est))

    @property
    def requests(self) -> int:
        return sum(n for _, n, _ in self.items)

    @property
    def images(self) -> int:
        return sum(n * e.images for _, n, e in self.items)

    @property
    def input_tokens(self) -> int:
        return sum(n * e.input_tokens for _, n, e in self.items)

    @property
    def output_tokens(self) -> int:
        return sum(n * e.output_tokens for _, n, e in self.items)

    @property
    def expected_cost(self) -> float | None:
        if self.prices is None:
            return None
        return sum(n * (e.cost(self.prices) or 0.0) for _, n, e in self.items)

    @property
    def max_cost(self) -> float | None:
        if self.prices is None:
            return None
        return sum(n * (e.max_cost(self.prices) or 0.0) for _, n, e in self.items)

    @property
    def needs_confirmation(self) -> bool:
        return self.may_bill and self.requests > 0

    @property
    def blocked_reason(self) -> str:
        """Why paid requests would not be made at all (empty when allowed)."""
        if not self.may_bill or self.requests == 0:
            return ""
        if self.prices is None and (self.run_limit > 0 or self.monthly_limit > 0):
            return (f"The price of “{self.model}” is unknown, so the spending limit cannot be enforced. Enter the "
                    "provider's price per million tokens in Settings → AI assistance (or remove the limit).")
        if self.monthly_limit > 0 and self.month_spent >= self.monthly_limit:
            return f"This month's AI spending limit (${self.monthly_limit:.2f}) has been reached."
        return ""

    def summary(self) -> str:
        lines = [f"{self.requests} request(s) to {self.provider} · {self.model}"]
        for label, n, e in self.items:
            img = f", {n * e.images} image(s)" if e.images else ""
            c = e.cost(self.prices)
            money = f" ≈ ${n * c:.3f}" if c is not None else ""
            lines.append(f"• {label}: {n} request(s){img}{money}")
        lines.append(f"≈ {self.input_tokens:,} input + {self.output_tokens:,} output tokens")
        if self.expected_cost is not None:
            if self.prices and self.prices.source == "free":
                lines.append("Runs on your own computer/network: no charge.")
            else:
                lines.append(f"Expected cost ≈ ${self.expected_cost:.2f} (at most ≈ ${self.max_cost:.2f}); "
                             f"prices: {'your settings' if self.prices.source == 'settings' else 'list price, ' + PRICES_AS_OF}.")
        else:
            lines.append("Cost unknown: enter this model's price in Settings → AI assistance to see it.")
        if self.run_limit > 0:
            lines.append(f"Limit per generation: ${self.run_limit:.2f} — AI steps stop when it is reached.")
            if self.expected_cost is not None and self.expected_cost > self.run_limit:
                lines.append("The estimate is above this limit: later AI steps (critique first) will probably be skipped "
                             "and done offline instead.")
        if self.monthly_limit > 0:
            lines.append(f"Monthly limit: ${self.monthly_limit:.2f} (spent this month: ${self.month_spent:.2f}).")
        lines.extend(self.notes)
        return "\n".join(lines)


class UsageLedger:
    """Month-by-month record of AI usage, stored in the user data folder.

    Holds only counts and amounts — never prompts, answers, images or keys.
    """

    _lock = threading.Lock()

    def __init__(self, path=None) -> None:
        if path is None:
            from behance_studio.core.paths import user_data_dir

            path = user_data_dir() / "ai_usage.json"
        self.path = path

    @staticmethod
    def month_key(ts: float | None = None) -> str:
        return time.strftime("%Y-%m", time.localtime(ts or time.time()))

    def _read(self) -> dict[str, Any]:
        try:
            data = read_json(self.path, default={})
        except (OSError, ValueError):
            data = {}
        return data if isinstance(data, dict) else {}

    def month(self, key: str | None = None) -> dict[str, Any]:
        months = self._read().get("months", {})
        entry = months.get(key or self.month_key(), {}) if isinstance(months, dict) else {}
        return entry if isinstance(entry, dict) else {}

    def month_spent(self) -> float:
        try:
            return float(self.month().get("cost", 0.0))
        except (TypeError, ValueError):
            return 0.0

    def add(self, provider: str, model: str, usage: Usage, cost: float | None) -> None:
        with self._lock:
            data = self._read()
            months = data.setdefault("months", {})
            entry = months.setdefault(self.month_key(), {})
            entry["requests"] = int(entry.get("requests", 0)) + 1
            entry["input_tokens"] = int(entry.get("input_tokens", 0)) + usage.input_tokens + usage.cache_write_tokens + usage.cache_read_tokens
            entry["output_tokens"] = int(entry.get("output_tokens", 0)) + usage.output_tokens
            if cost is not None:
                entry["cost"] = round(float(entry.get("cost", 0.0)) + cost, 6)
            else:
                entry["unpriced_requests"] = int(entry.get("unpriced_requests", 0)) + 1
            models = entry.setdefault("models", {})
            models[f"{provider}:{model}"] = int(models.get(f"{provider}:{model}", 0)) + 1
            try:
                atomic_write_json(self.path, data)
            except OSError as exc:  # accounting must never break generation
                log.warning("Could not record AI usage: %s", exc)


class SpendMeter:
    """Per-run accounting and limit enforcement shared by all AI requests."""

    def __init__(self, provider: str, model: str, prices: Prices | None, may_bill: bool,
                 run_limit: float = 0.0, monthly_limit: float = 0.0, ledger: UsageLedger | None = None) -> None:
        self.provider = provider
        self.model = model
        self.prices = prices
        self.may_bill = may_bill
        self.run_limit = max(0.0, float(run_limit or 0.0))
        self.monthly_limit = max(0.0, float(monthly_limit or 0.0))
        self.ledger = ledger
        self.spent = 0.0
        self.input_tokens = 0
        self.output_tokens = 0
        self.requests = 0
        self.unreported = 0
        self._lock = threading.Lock()

    def authorize(self, est: RequestEstimate) -> None:
        """Raise when this request must not be sent."""
        if not self.may_bill:
            return
        if self.prices is None:
            if self.run_limit > 0 or self.monthly_limit > 0:
                raise PriceUnknown(
                    f"AI request not sent: the price of “{self.model}” is unknown, so the spending limit cannot be enforced.",
                    "Enter the provider's price per million tokens in Settings → AI assistance, or remove the limit.",
                )
            return
        expected = est.cost(self.prices) or 0.0
        with self._lock:
            if self.run_limit > 0 and self.spent + expected > self.run_limit:
                raise BudgetExceeded(
                    f"AI step skipped: the limit of ${self.run_limit:.2f} per generation would be exceeded "
                    f"(spent ${self.spent:.3f}, next request ≈ ${expected:.3f})."
                )
            if self.monthly_limit > 0 and self.ledger is not None:
                month = self.ledger.month_spent()
                if month + expected > self.monthly_limit:
                    raise BudgetExceeded(
                        f"AI step skipped: this month's limit of ${self.monthly_limit:.2f} would be exceeded "
                        f"(spent ${month:.2f})."
                    )

    def record(self, usage: Usage, est: RequestEstimate | None = None) -> float | None:
        if not usage.reported and est is not None:
            # The provider did not report usage: account for the estimate so
            # the limit still holds (upper bound for the answer).
            usage = Usage(est.input_tokens, est.max_output_tokens)
            self.unreported += 1
        cost = usage.cost(self.prices) if self.may_bill else 0.0
        with self._lock:
            self.requests += 1
            self.input_tokens += usage.input_tokens + usage.cache_write_tokens + usage.cache_read_tokens
            self.output_tokens += usage.output_tokens
            if cost is not None:
                self.spent += cost
        if self.ledger is not None and self.may_bill:
            self.ledger.add(self.provider, self.model, usage, cost)
        return cost

    def summary(self) -> str:
        if not self.requests:
            return ""
        tokens = f"{self.input_tokens:,} input + {self.output_tokens:,} output tokens"
        if not self.may_bill:
            return f"AI usage: {self.requests} request(s), {tokens} (local, no charge)."
        money = f", ≈ ${self.spent:.3f}" if self.prices is not None else ", cost unknown (no price set)"
        return f"AI usage: {self.requests} request(s), {tokens}{money}."
