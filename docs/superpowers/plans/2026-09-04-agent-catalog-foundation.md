# Agent Catalog Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and execute this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a static, read-only runtime catalog for the eight canonical Jarvis agents and expose it at `GET /api/agents`.

**Architecture:** Immutable agent contracts live in `app/agents/models.py`; the only ordered runtime catalog and its registry live in `app/agents/registry.py`. A read-only FastAPI router obtains the injected registry from application state and serializes definitions without touching any operational subsystem.

**Tech Stack:** Python 3, dataclasses, Enum, FastAPI, unittest/pytest.

**Spec:** User-approved Fase 3A request and canonical personas under `obsidian-template/Agentes/`.

## Global Constraints

- Exactly eight lowercase IDs in the approved order, all initially `idle`.
- No aliases, execution, persistence, Markdown parsing, providers, tasks, chat, actions, frontend, or ZEUS integration.
- No commit or push.

---

### Task 1: Define failing registry contract tests

**Files:**
- Create: `tests/test_agent_registry.py`
- Create: `tests/test_fastapi_agents.py`

**Interfaces:**
- Consumes: wished-for `AgentDefinition`, `AgentStatus`, `AgentRegistry`, and `create_agent_registry()`.
- Produces: executable contracts for catalog, validation, lookup, API payload, methods, and side-effect isolation.

- [x] Write literal expectations for the eight definitions and exclusion set.
- [x] Run both tests and record RED caused by missing `app.agents`.

### Task 2: Implement immutable models and canonical registry

**Files:**
- Create: `app/agents/__init__.py`
- Create: `app/agents/models.py`
- Create: `app/agents/registry.py`

**Interfaces:**
- Produces: `AgentStatus`, `AgentDefinition.to_dict()`, `DuplicateAgentError`, `UnknownAgentError`, `AgentRegistry.list_agents()`, `AgentRegistry.get()`, and `create_agent_registry()`.

- [x] Implement normalized validation and stable JSON serialization.
- [x] Define the single ordered `CANONICAL_AGENT_DEFINITIONS` tuple.
- [x] Run registry tests to GREEN.

### Task 3: Expose the read-only API

**Files:**
- Create: `app/api/agents.py`
- Modify: `app/main.py`
- Test: `tests/test_fastapi_agents.py`

**Interfaces:**
- Consumes: injected `AgentRegistry` from `application.state.agent_registry`.
- Produces: `GET /api/agents` returning `{agents, count}` and no mutation endpoints.

- [x] Add optional registry injection, state binding, and router registration.
- [x] Run API tests to GREEN.
- [x] Run bounded FastAPI boot/API regressions and syntax/import checks.
- [x] Validate a real HTTP request through `TestClient`, then run `git diff --check` and `git status --short`.
