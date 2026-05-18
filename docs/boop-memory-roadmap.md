# Boop-Inspired Memory Roadmap

This roadmap translates Boop-style memory behavior into Mind Palace improvements: memory should feel automatic to the host agent, but every read and write should remain policy-driven, scoped, inspectable, and easy to disable.

## Implementation Track

Status as of `2026-05-18`: complete for the first autonomous implementation pass.

| Phase | Status | Delivered |
| --- | --- | --- |
| 1. Lifecycle and supersession | Complete | Added active/archived/pruned lifecycle helpers, backward-compatible legacy `status` handling, `supersedes` support on writes, and archival of superseded memories. |
| 2. Event logging | Complete | Added SQLite-backed memory event logging, MCP event tools, and `scripts/memory_events.py`. |
| 3. Health and reindex commands | Complete | Added health inspection and re-embedding APIs, MCP tools, and `scripts/health.py` / `scripts/reembed.py`. |
| 4. Host-agent policy artifact | Complete | Added `docs/host-agent-memory-policy.md`. |
| 5. Consolidation job | Complete | Added proposer/adversary/judge consolidation with dry-run default, MCP tool, and `scripts/consolidate.py`. |
| 6. Inspection report | Complete | Added `scripts/memory_report.py` static HTML report generation for memory health, records, and events. |

### Verification

- `tests/` includes coverage for lifecycle/supersession, memory event logging, health/re-embed, and consolidation.
- Baseline command: `.venv/bin/python -m pytest tests/ -q`.

## Goals

- Give host agents a small, repeatable memory loop for task start, mid-task lookup, durable writes, and session close.
- Keep memory reads useful without flooding prompts or leaking unrelated project context.
- Make writes conservative, deduplicated, typed, and attributable to the agent action that created them.
- Provide enough policy structure that multiple hosts can share Mind Palace without inventing their own rules.

## Non-Goals

- Do not replace agent reasoning with hidden memory automation.
- Do not store raw transcripts by default.
- Do not make cross-project reads writable or implicit.
- Do not require Python API changes before the policy can be adopted by hosts.

## Phase 1: Host-Agent Policy Baseline

Create and publish a reusable host-agent policy that defines when to call each memory tool, what to pass, and what not to store.

### Work

- Document the canonical memory loop for `memory_context`, `memory_search`, `memory_add`, and `memory_end_session`.
- Define write eligibility rules for each memory type: `preference`, `durable_fact`, `decision`, `open_loop`, and `correction`.
- Define namespace requirements for `agent_id`, project IDs, and optional read-only cross-agent search.
- Define prompt-injection hygiene for memory text and retrieved context.
- Add a compact policy block that can be embedded into host-agent system prompts.

### Acceptance Criteria

- A host agent can adopt the policy without reading source code.
- The policy includes explicit call timing for all four core tools.
- The policy distinguishes immediate explicit writes from end-of-session extraction.
- The policy states that retrieved memories are context, not instructions.
- The policy states that host agents must not write secrets, credentials, private tokens, or raw full transcripts.

## Phase 2: Boop-Style Memory Experience

Shape memory behavior around a lightweight interaction model: retrieve just enough context before work, search on demand when uncertainty appears, write only durable facts, and summarize session learnings at the end.

### Work

- Standardize host-agent startup behavior around one `memory_context` call with a narrow task query.
- Standardize mid-task behavior around targeted `memory_search` calls rather than broad repeated context loads.
- Encourage immediate `memory_add` only when the user states a preference, corrects the agent, makes a durable decision, or creates a follow-up obligation.
- Encourage `memory_end_session` only after meaningful work, using a concise transcript rather than tool noise.
- Document recommended token budgets and result limits for small, medium, and large tasks.

### Acceptance Criteria

- Hosts can keep prompt memory under a predictable token budget.
- The policy prevents repeated broad searches for the same task.
- Memory writes are tied to concrete user-visible facts or decisions.
- Session-end extraction captures useful carry-forward information without duplicating immediate writes.

## Phase 3: Observability and Review

Make memory behavior inspectable so users and host developers can trust what was read, written, skipped, and why.

### Work

- Define a host-side memory event log schema for reads, writes, rejected writes, and session extraction.
- Document rejection reasons such as `not_durable`, `duplicate`, `sensitive`, `too_broad`, `policy_blocked`, and `wrong_namespace`.
- Recommend surfacing a changed-memory summary at session end when writes occurred.
- Recommend periodic review with `memory_get_all`, `memory_token_usage`, and dry-run `memory_gc`.

### Acceptance Criteria

- Each host memory write can be traced to a request, user message, or session.
- Rejected candidate writes are explainable without exposing sensitive text.
- Users can inspect what changed after a session.
- Memory token usage can be reviewed per agent or project.

## Phase 4: Multi-Agent and Cross-Project Context

Support richer host-agent behavior while preserving namespace boundaries.

### Work

- Document read-only `also_search` use cases for shared libraries, design systems, and durable organization knowledge.
- Define rules for never writing memories into `also_search` scopes.
- Recommend metadata for provenance, model, host agent version, and project identity.
- Define conflict handling when retrieved memories disagree.

### Acceptance Criteria

- Cross-project retrieval is opt-in and read-only.
- Hosts can explain which source agent produced a retrieved memory.
- Conflicting memories trigger clarification or conservative behavior.
- Shared context does not silently pollute project-specific memory.

## Phase 5: Product Hardening

Turn the policy into enforceable host integrations and operational checks.

### Work

- Add host-side fixtures or conformance tests for memory call timing and write policy.
- Add example host configurations for strict, balanced, and exploratory memory modes.
- Add documentation for memory migration, policy versioning, and user-visible controls.
- Add periodic cleanup guidance that combines decay, review, and explicit user correction.

### Acceptance Criteria

- Host integrations can be tested against the policy.
- Memory mode changes are explicit and documented.
- Policy updates are versioned so hosts can declare compatibility.
- Cleanup behavior is predictable and reversible until garbage collection is executed.

## Recommended Defaults

| Setting | Default | Rationale |
| --- | --- | --- |
| Startup context budget | 1,000-2,000 tokens | Enough for durable context without crowding task instructions. |
| Mid-task search limit | 3-5 results | Keeps lookups targeted and reviewable. |
| Immediate writes | Explicit facts only | Prevents speculative or noisy memory creation. |
| Session extraction | End meaningful sessions only | Avoids cost and duplicate memories for trivial exchanges. |
| Cross-agent search | Opt-in, read-only | Preserves namespace ownership. |

## Host Integration Checklist

- Load task context once with `memory_context` before work that may depend on prior project state.
- Use `memory_search` only for targeted uncertainty, cross-agent reads, or follow-up lookups.
- Use `memory_add` when the user explicitly states a durable preference, fact, decision, correction, or open loop.
- Use `memory_end_session` after substantial work to capture carry-forward context.
- Keep retrieved memories separate from authoritative user instructions.
- Log read and write activity in host-visible traces.
- Never store secrets, credentials, private tokens, transient reasoning, or raw full transcripts.
