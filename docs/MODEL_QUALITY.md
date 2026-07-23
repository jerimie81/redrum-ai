# Model Runtime and Intelligence Quality Plan

## Provider Strategy

`redrum-ai` uses a provider abstraction so Ollama is the default implementation rather than a hard-coded dependency throughout the app.

## Model Profiles

1. Speed profile: small local model for classification and summaries.
2. Quality profile: larger local model for planning and code review.
3. Coding profile: model selected for structured tool-call reliability.

## Capability Checks

Provider health should report:

1. Provider name.
2. Configured model.
3. Availability.
4. Known model list when available.
5. Actionable failure reason.

## Benchmark Prompt Groups

1. Planning: produce valid task lists with acceptance criteria.
2. Tool selection: choose a safe registered tool or ask for escalation.
3. Summarization: compress session history without inventing facts.
4. Review: identify incomplete work and residual risk.

## Structured Output Policy

Structured model outputs must be validated. Invalid JSON should be repaired only within bounded retries and then escalated with the raw response preserved for diagnostics.

## Upgrade and Rollback

1. Record current provider and model before upgrade.
2. Run health checks and prompt benchmarks.
3. Keep previous model configuration available for rollback.
