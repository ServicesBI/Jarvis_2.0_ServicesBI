"""Projeção HTTP do catálogo canônico de agentes e execução explícita."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.agents.execution import AgentExecutionService
from app.agents.orchestration import MorpheusOrchestrationService
from app.agents.registry import AgentRegistry, UnknownAgentError
from app.agents.runtime import AgentOperatingProfileNotFoundError
from app.agents.state import AgentRuntimeStateService


router = APIRouter(prefix="/api/agents", tags=["agents"])


def _registry(request: Request) -> AgentRegistry:
    return request.app.state.agent_registry


def _state(request: Request) -> AgentRuntimeStateService:
    return request.app.state.agent_state_service


@router.get("")
async def list_agents(request: Request) -> dict[str, Any]:
    state = _state(request)
    agents = []
    for agent in _registry(request).list_agents():
        payload = agent.to_dict()
        payload["status"] = state.get_status(agent.id).value
        agents.append(payload)
    return {"agents": agents, "count": len(agents)}


@router.post("/{agent_id}/run")
async def run_agent(agent_id: str, request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except (ValueError, UnicodeError):
        payload = None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload invalido.")
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        raise HTTPException(status_code=400, detail="Message required")

    service: AgentExecutionService = request.app.state.agent_execution_service
    try:
        return await service.run(agent_id, message)
    except (UnknownAgentError, AgentOperatingProfileNotFoundError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/morpheus/plan")
async def morpheus_plan(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except (ValueError, UnicodeError):
        payload = None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload invalido.")
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        raise HTTPException(status_code=400, detail="Message required")

    service: MorpheusOrchestrationService = (
        request.app.state.morpheus_orchestration_service
    )
    return await service.plan(message)
