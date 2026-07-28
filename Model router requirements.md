# Model router

# Model - Router

## Problem

high Inference users are running into runaway token cost, although they are are turning to Open Models to reduce cost, They are struggling to find the best models per task and hence to minimize inference token cost, without sacrificing task accuracy and intelligence.

- [High cost] $\rightarrow$ Sacrificing task accuracy and intelligence.
    - $\hookrightarrow$ Without sacrificing E2E or turn latency.

## Target Customers

Broadly anyone with high & un-optimized model inference consumption for a **variety** of tasks.

- $\hookrightarrow$ Specifically, harness owners like (Warp, open-code, Robusta etc.) that sell Agent subscriptions.

## Customer Benefit

Reduce $ / task completion!

Solution: Key Reqd.

Build a Intelligence aware **cache-aware** model router that picks the right open source model for the task based on benchmarks to minimize cost without sacrificing intelligence and task accuracy — including prompt-cache savings across turns/sessions.

1. Low latency / throughput overhead.
2. Benchmarks based model selection.
3. Session calssifier to identity task type.
4. Integrates with OSS harnesses (Hermes, open-code, Plandata).
5. Prompt caching layer $\rightarrow$ cache-aware routing (local + provider prompt cache).

---

# Full Reqd. List

1. Low latency / throughput overhead.
2. Task classifier $\rightarrow$ To identity task type.
3. Benchmarks by task type (seeded from **DeepSWE**, **SWE-bench Verified**, **Terminal-Bench**, **Artificial Analysis**, **Arena AI**):
    - (cost) $\rightarrow$ Model $ per token (including **cached** input token rates).
    - (intelligence) $\rightarrow$ Model task completion accuracy derived from those leaderboards.
4. Pluggability $\rightarrow$ Integrate with common open-source harness.
    - $\hookrightarrow$ Consider building on top of LiteLLM.
5. Telemetry $\rightarrow$:
    - (a) Per session total time.
    - (b) Per session token consumption.
    - (c) Per session Cost $.
    - (d) Accuracy? Ticks?
    - (e) Classification.
    - $\Delta$ Cost against frontier models.
    - Key LiteLLM metrics.
    - Cache hits / miss, cache layer, estimated cache savings.
6. Run locally and as a cloud based scalable model Gateway / Router.
7. Build a benchmark with every user interaction $\rightarrow$ Anonymized.
8. Support the native inference APIs( use LiteLLM as reference) with openAI, and Anthropic API compatibility
9. **Prompt caching layer (cache-aware model router)**:
    - Local exact / prefix response cache where safe.
    - Session affinity so multi-turn agents keep the same model and preserve provider prompt caches.
    - Selection policy prices **effective** cost with cached vs uncached tokens (do not flip models in a way that burns cache savings).
    - Prefer / weight models that support provider prompt caching when prefix reuse is likely (agents, long system prompts, tools).