## Context
This change establishes the first implementation slice for a DuckDB-based historical candle backfill module. It combines scope freeze (Milestone 0) and storage foundation (Milestone 1) so reviewers can validate boundaries, data model assumptions, and event-loop-safe storage behavior before higher-level orchestration is introduced.

The host environment is an asyncio application and may include GUI rendering on the same loop. Therefore, blocking DuckDB calls cannot run directly on the event-loop thread.

## Goals / Non-Goals
- Goals:
  - Define explicit v1 scope boundaries and exclusions.
  - Establish durable local DuckDB schema for candles, jobs, and tasks.
  - Require idempotent candle storage and task enqueue primitives.
  - Require async facade behavior that offloads blocking DuckDB operations.
- Non-Goals:
  - Provider orchestration and retry engine semantics.
  - Multi-process or distributed task claiming.
  - GUI integration and status rendering.

## Decisions
- Decision: Use a local DuckDB file as the durable v1 backend.
  - Rationale: portability, inspectable SQL state, and no external server dependency.
- Decision: Keep queue ownership in one Python process for v1.
  - Rationale: avoids DB row-lock semantics unavailable in this architecture.
- Decision: Require async storage facade over synchronous DuckDB work.
  - Rationale: preserve host event-loop responsiveness.

## Risks / Trade-offs
- Risk: Direct synchronous DB calls inside async code can freeze GUI/host loop.
  - Mitigation: require thread offload or single dedicated DB worker thread.
- Risk: Scope drift into orchestration concerns during foundation work.
  - Mitigation: explicit in-scope/out-of-scope requirement and checklist.
- Risk: Data model churn after later milestones.
  - Mitigation: review schema and task primitives before moving to dispatch/retries.

## Migration Plan
1. Approve this change proposal and deltas.
2. Implement schema and primitive helpers.
3. Add focused storage and event-loop tests.
4. Use this foundation as prerequisite for subsequent provider and dispatch changes.

## Open Questions
- Should raw payload storage default to JSON or TEXT for widest local compatibility?
- Should attempts table be deferred to a later change or added behind an optional requirement?
