from __future__ import annotations

from dataclasses import dataclass

from model_router.config import (
    BenchmarksConfig,
    Deployment,
    ModelBenchmark,
    ModelsConfig,
    PolicyConfig,
)
from model_router.feedback import FeedbackAccuracy
from model_router.prompt_cache import SessionAffinity
from model_router.provider_health import ProviderHealthTracker, get_provider_health
from model_router.litellm_backend import provider_credential_available


@dataclass(frozen=True)
class RoutingDecision:
    selected_model: str
    litellm_model: str
    task_type: str
    classification_confidence: float
    min_accuracy: float
    selected_accuracy: float
    estimated_cost_usd: float
    frontier_cost_usd: float
    cost_delta_vs_frontier_usd: float
    reason: str
    eligible_models: list[str]
    considered_models: list[str]
    cache_layer: str = "none"  # none | provider_affinity
    estimated_cached_tokens: int = 0
    sticky_model: str | None = None
    supports_prompt_caching: bool = False


def _estimate_cost(
    bench: ModelBenchmark,
    *,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
) -> float:
    cached = max(0, min(cached_tokens, input_tokens))
    uncached = input_tokens - cached
    return (
        (cached / 1_000_000) * bench.cached_input_rate()
        + (uncached / 1_000_000) * bench.input_cost_per_m
        + (output_tokens / 1_000_000) * bench.output_cost_per_m
    )


def estimate_input_tokens(text: str) -> int:
    # Rough heuristic: ~4 chars/token. Good enough for pre-call ranking.
    return max(1, len(text) // 4)


class SelectionPolicy:
    def __init__(
        self,
        *,
        policy: PolicyConfig,
        benchmarks: BenchmarksConfig,
        models: ModelsConfig,
        require_credentials: bool = False,
    ) -> None:
        self.policy = policy
        self.benchmarks = benchmarks
        self.models = models
        self._enabled = {d.id: d for d in models.deployments if d.enabled}
        self._auto = {
            d.id: d for d in models.deployments if d.enabled and d.auto_select
        }
        self.require_credentials = require_credentials

    def enabled_deployment(self, model_id: str) -> Deployment | None:
        return self._enabled.get(model_id)

    def viable_auto_deployments(self) -> dict[str, Deployment]:
        if not self.require_credentials:
            return dict(self._auto)
        return {
            mid: deployment
            for mid, deployment in self._auto.items()
            if provider_credential_available(deployment.litellm_model)
        }

    def _deployment_viable(self, model_id: str) -> bool:
        deployment = self._enabled.get(model_id)
        if deployment is None:
            return False
        return (
            not self.require_credentials
            or provider_credential_available(deployment.litellm_model)
        )

    def select(
        self,
        *,
        task_type: str,
        classification_confidence: float,
        prompt_text: str,
        estimated_output_tokens: int | None = None,
        session_affinity: SessionAffinity | None = None,
        likely_prefix_reuse: bool = False,
        observed_sticky_ratio: float | None = None,
        provider_health: ProviderHealthTracker | None = None,
        difficulty: str = "easy",
        feedback_accuracy: FeedbackAccuracy | None = None,
    ) -> RoutingDecision:
        out_tokens = estimated_output_tokens or self.policy.default_estimated_output_tokens
        in_tokens = estimate_input_tokens(prompt_text)
        min_acc = self.policy.min_accuracy(task_type, difficulty=difficulty)
        sticky_id = session_affinity.model_id if session_affinity else None
        health = provider_health or get_provider_health()

        if classification_confidence < self.policy.min_classification_confidence:
            if not self._deployment_viable(self.policy.safe_fallback_model):
                raise RuntimeError(
                    "safe fallback provider credential unavailable: "
                    f"{self.policy.safe_fallback_model}"
                )
            return self._decision_for_forced(
                model_id=self.policy.safe_fallback_model,
                task_type=task_type,
                classification_confidence=classification_confidence,
                min_acc=min_acc,
                in_tokens=in_tokens,
                out_tokens=out_tokens,
                cached_tokens=0,
                reason="low_classification_confidence",
                eligible=[],
                considered=list(self.viable_auto_deployments()),
                sticky_model=sticky_id,
            )

        considered: list[str] = []
        eligible: list[tuple[str, float, float, int, ModelBenchmark]] = []

        for model_id, deployment in self.viable_auto_deployments().items():
            bench = self.benchmarks.models.get(model_id)
            if bench is None:
                continue
            considered.append(model_id)
            if in_tokens > bench.context_window:
                continue
            acc = bench.accuracy.get(task_type)
            if acc is None:
                continue
            if acc < min_acc:
                continue

            cached_tokens = 0
            if (
                session_affinity
                and model_id == session_affinity.model_id
                and bench.supports_prompt_caching
            ):
                # Sticky model can reuse provider prompt cache for stable prefix.
                # Cap by prefix estimate (not growing in_tokens * ratio) so we
                # do not over-credit cache as prompts grow beyond the prefix.
                ratio = self.policy.default_cache_hit_ratio
                reusable = min(in_tokens, session_affinity.prefix_tokens_estimate)
                cached_tokens = int(reusable * ratio)

            cost = _estimate_cost(
                bench,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                cached_tokens=cached_tokens,
            )
            cost = self._effective_cost(
                cost,
                bench=bench,
                litellm_model=deployment.litellm_model,
                health=health,
            )
            # Soft task×model pass-rate nudge — does not change public floors.
            if feedback_accuracy is not None:
                cost *= feedback_accuracy.cost_multiplier(task_type, model_id)
            eligible.append((model_id, acc, cost, cached_tokens, bench))

        if not eligible:
            if not considered:
                raise RuntimeError(
                    "no viable auto deployments: configure a provider credential "
                    "for an enabled auto_select deployment"
                )
            best_id = None
            best_acc = -1.0
            for model_id in considered:
                bench = self.benchmarks.models[model_id]
                acc = bench.accuracy.get(task_type, 0.0)
                if acc > best_acc:
                    best_acc = acc
                    best_id = model_id
            forced = best_id or self.policy.safe_fallback_model
            if not self._deployment_viable(forced):
                raise RuntimeError(f"no credential available for fallback model {forced}")
            return self._decision_for_forced(
                model_id=forced,
                task_type=task_type,
                classification_confidence=classification_confidence,
                min_acc=min_acc,
                in_tokens=in_tokens,
                out_tokens=out_tokens,
                cached_tokens=0,
                reason="no_eligible_below_floor_use_best_available",
                eligible=[],
                considered=considered,
                sticky_model=sticky_id,
            )

        # Prefer session stickiness when still eligible and not dominated on effective cost.
        sticky_row = next((row for row in eligible if row[0] == sticky_id), None)
        if sticky_row is not None:
            cold_best = min(
                (row for row in eligible if row[0] != sticky_id),
                key=lambda row: row[2],
                default=None,
            )
            sticky_cost = sticky_row[2]
            margin = self._affinity_margin(observed_sticky_ratio)
            if cold_best is None or sticky_cost <= cold_best[2] * (1.0 + margin):
                return self._build_decision(
                    sticky_row,
                    task_type=task_type,
                    classification_confidence=classification_confidence,
                    min_acc=min_acc,
                    in_tokens=in_tokens,
                    out_tokens=out_tokens,
                    reason="session_affinity_preserve_prompt_cache",
                    eligible=[row[0] for row in eligible],
                    considered=considered,
                    cache_layer="provider_affinity",
                    sticky_model=sticky_id,
                )

        # Cold ranking: min effective cost; break ties toward caching-capable when prefix reuse likely.
        def sort_key(row: tuple[str, float, float, int, ModelBenchmark]) -> tuple:
            model_id, acc, cost, _cached, bench = row
            prefer_cache = 0
            if (
                likely_prefix_reuse
                and in_tokens >= self.policy.prefer_caching_models_above_prefix_tokens
                and bench.supports_prompt_caching
            ):
                prefer_cache = -1
            return (cost, prefer_cache, -acc)

        eligible.sort(key=sort_key)
        best = eligible[0]
        reason = "min_effective_cost_above_intelligence_floor"
        cache_layer = "provider_affinity" if best[3] > 0 else "none"
        return self._build_decision(
            best,
            task_type=task_type,
            classification_confidence=classification_confidence,
            min_acc=min_acc,
            in_tokens=in_tokens,
            out_tokens=out_tokens,
            reason=reason,
            eligible=[row[0] for row in eligible],
            considered=considered,
            cache_layer=cache_layer,
            sticky_model=sticky_id,
        )

    def _affinity_margin(self, observed_sticky_ratio: float | None) -> float:
        margin = self.policy.cache_switch_savings_margin
        if (
            observed_sticky_ratio is not None
            and self.policy.observed_sticky_margin_boost > 0
            and observed_sticky_ratio > 0
        ):
            margin *= 1.0 + self.policy.observed_sticky_margin_boost * min(
                1.0, observed_sticky_ratio
            )
        return margin

    def _effective_cost(
        self,
        base_cost: float,
        *,
        bench: ModelBenchmark,
        litellm_model: str,
        health: ProviderHealthTracker,
    ) -> float:
        cost = base_cost
        if self.policy.provider_health_enabled:
            err = health.error_rate(litellm_model)
            cost *= 1.0 + self.policy.provider_health_penalty * err
        lat_ms = bench.p50_latency_ms
        if lat_ms is not None and self.policy.latency_penalty_usd_per_ms > 0:
            cost += self.policy.latency_penalty_usd_per_ms * float(lat_ms)
        return cost

    def _frontier_cost(self, in_tokens: int, out_tokens: int) -> float:
        bench = self.benchmarks.models.get(self.policy.frontier_model)
        if bench is None:
            return 0.0
        return _estimate_cost(bench, input_tokens=in_tokens, output_tokens=out_tokens)

    def _build_decision(
        self,
        row: tuple[str, float, float, int, ModelBenchmark],
        *,
        task_type: str,
        classification_confidence: float,
        min_acc: float,
        in_tokens: int,
        out_tokens: int,
        reason: str,
        eligible: list[str],
        considered: list[str],
        cache_layer: str,
        sticky_model: str | None,
    ) -> RoutingDecision:
        model_id, acc, cost, cached_tokens, bench = row
        deployment = self._enabled[model_id]
        frontier_cost = self._frontier_cost(in_tokens, out_tokens)
        return RoutingDecision(
            selected_model=model_id,
            litellm_model=deployment.litellm_model,
            task_type=task_type,
            classification_confidence=classification_confidence,
            min_accuracy=min_acc,
            selected_accuracy=acc,
            estimated_cost_usd=cost,
            frontier_cost_usd=frontier_cost,
            cost_delta_vs_frontier_usd=cost - frontier_cost,
            reason=reason,
            eligible_models=eligible,
            considered_models=considered,
            cache_layer=cache_layer,
            estimated_cached_tokens=cached_tokens,
            sticky_model=sticky_model,
            supports_prompt_caching=bench.supports_prompt_caching,
        )

    def _decision_for_forced(
        self,
        *,
        model_id: str,
        task_type: str,
        classification_confidence: float,
        min_acc: float,
        in_tokens: int,
        out_tokens: int,
        cached_tokens: int,
        reason: str,
        eligible: list[str],
        considered: list[str],
        sticky_model: str | None,
    ) -> RoutingDecision:
        bench = self.benchmarks.models.get(model_id)
        deployment = self._enabled.get(model_id)
        litellm_model = deployment.litellm_model if deployment else model_id
        acc = bench.accuracy.get(task_type, 0.0) if bench else 0.0
        cost = (
            _estimate_cost(
                bench,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                cached_tokens=cached_tokens,
            )
            if bench
            else 0.0
        )
        frontier_cost = self._frontier_cost(in_tokens, out_tokens)
        return RoutingDecision(
            selected_model=model_id,
            litellm_model=litellm_model,
            task_type=task_type,
            classification_confidence=classification_confidence,
            min_accuracy=min_acc,
            selected_accuracy=acc,
            estimated_cost_usd=cost,
            frontier_cost_usd=frontier_cost,
            cost_delta_vs_frontier_usd=cost - frontier_cost,
            reason=reason,
            eligible_models=eligible,
            considered_models=considered,
            cache_layer="provider_affinity" if cached_tokens > 0 else "none",
            estimated_cached_tokens=cached_tokens,
            sticky_model=sticky_model,
            supports_prompt_caching=bool(bench.supports_prompt_caching) if bench else False,
        )
