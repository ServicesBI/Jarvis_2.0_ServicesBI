"""Backend operacional principal do JARVIS, executado com FastAPI."""

import asyncio
import ipaddress

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.actions.engine import ActionEngine
from app.actions.app_open import create_app_open_definition
from app.actions.excel import create_excel_definition
from app.actions.file_open import create_file_open_definition
from app.actions.file_resolve import create_file_resolve_definition
from app.actions.powerbi_open import create_powerbi_open_definition
from app.actions.registry import ActionRegistry
from app.actions.word import create_word_definition
from app.agents.execution import AgentExecutionService
from app.agents.orchestration import MorpheusOrchestrationService
from app.agents.registry import AgentRegistry, create_agent_registry
from app.agents.state import AgentRuntimeStateService
from app.api.agents import router as agents_router
from app.api.automation import router as automation_router
from app.api.chat import router as chat_router
from app.api.claude_auth import router as claude_auth_router
from app.api.codex_auth import router as codex_auth_router
from app.api.compatibility import router as compatibility_router
from app.api.diagnostics import router as diagnostics_router
from app.api.executors import router as executors_router
from app.api.health import router as health_router
from app.api.notifications import NotificationBroker, router as notifications_router
from app.api.providers import router as providers_router
from app.api.tasks import router as tasks_router
from app.api.voice import router as voice_router
from app.api.workspace import router as workspace_router
from app.chat.action_dispatcher import ActionDispatcher
from app.chat.claude import CliRunner as ClaudeCliRunner
from app.chat.codex import CliRunner as CodexCliRunner
from app.chat.codex import CodexChatExecutor
from app.chat.executor import AvailabilityObservedExecutor, ChatExecutor
from app.chat.factory import create_managed_chat_service
from app.chat.service import ChatService
from app.core.config import HOST, LOCAL_ORIGINS, PORT, PROJECT_ROOT, PUBLIC_DIR, get_setting
from app.db.engine import create_database_engine, create_session_factory
from app.db.repositories_postgres import PostgresTaskRepository
from app.core.openai_gateway import OpenAIGateway
from app.core.openai_balance import OpenAIBalanceService
from app.core.openai_costs_ledger import OpenAICostsLedgerService
from app.executors.availability import ProviderAvailabilityService
from app.executors.claude_auth import ClaudeAuthService
from app.executors.codex_auth import CodexAuthService
from app.executors.cli import AsyncCliExecutor
from app.executors.service import (
    ExecutorService,
    codex_subprocess_environment,
    executor_service,
)
from app.providers.factory import PROVIDER_DEFINITIONS, create_provider_manager
from app.providers.manager import ProviderManager
from app.providers.adapters.codex import CodexProviderAdapter
from app.tasks import TaskManager


def _is_loopback_host(host: str) -> bool:
    """Aceita apenas clientes conectados pela interface de loopback."""

    if host.lower() == "localhost":
        return True

    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False

    if address.is_loopback:
        return True

    mapped = getattr(address, "ipv4_mapped", None)
    return mapped is not None and mapped.is_loopback


def _openai_balance_refresh_ms() -> int:
    """Lê o intervalo de atualização do saldo OpenAI, com fallback seguro."""

    raw_value = get_setting("OPENAI_BALANCE_REFRESH_MS")
    try:
        value = int(raw_value) if raw_value is not None else 300000
    except ValueError:
        return 300000
    return value if value > 0 else 300000


async def _request_uvicorn_shutdown(server: object) -> None:
    """Solicita o encerramento depois que a resposta HTTP foi enviada."""

    await asyncio.sleep(0.15)
    server.should_exit = True


def create_app(
    chat_service: ChatService | None = None,
    *,
    executor_manager: ExecutorService | None = None,
    codex_runner: CodexCliRunner | None = None,
    claude_runner: ClaudeCliRunner | None = None,
    codex_auth_service: CodexAuthService | None = None,
    claude_auth_service: ClaudeAuthService | None = None,
    availability_service: ProviderAvailabilityService | None = None,
    openai_executor: ChatExecutor | None = None,
    provider_manager: ProviderManager | None = None,
    task_manager: TaskManager | None = None,
    openai_balance_service: OpenAIBalanceService | None = None,
    openai_costs_ledger_service: OpenAICostsLedgerService | None = None,
    agent_registry: AgentRegistry | None = None,
) -> FastAPI:
    application = FastAPI(
        title="JARVIS Python Backend",
        version="0H",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(LOCAL_ORIGINS),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Accept", "Content-Type"],
    )

    manager = executor_manager or executor_service
    application.state.executor_manager = manager
    codex_command = manager.get_command("codex")
    codex_cli_runner = codex_runner or AsyncCliExecutor(
        codex_command,
        default_timeout=90.0,
        environment=codex_subprocess_environment(),
    )
    codex_auth = codex_auth_service or CodexAuthService(
        codex_command,
        runner=codex_cli_runner,
    )
    claude_auth = (
        claude_auth_service
        or ClaudeAuthService(manager.get_command("claude"))
    )
    application.state.codex_auth_service = codex_auth
    application.state.claude_auth_service = claude_auth
    agent_registry_instance = agent_registry
    if agent_registry_instance is None and task_manager is not None:
        agent_registry_instance = task_manager.agent_registry
    if agent_registry_instance is None:
        agent_registry_instance = create_agent_registry()

    owns_task_manager = task_manager is None
    operational_database_url = get_setting("JARVIS_DATABASE_URL") if owns_task_manager else None
    if task_manager is not None:
        task_manager_instance = task_manager
    elif operational_database_url:
        # TaskRepository/PostgreSQL só vira o backend do TaskManager quando
        # JARVIS_DATABASE_URL aponta para um banco operacional do Jarvis —
        # nunca por padrão. A reconciliação real (query no banco) NÃO roda
        # aqui: é adiada para o startup event abaixo, para que apenas
        # construir a app (ex.: `app = create_app()` na importação deste
        # módulo) nunca dispare I/O de banco por si só.
        db_engine = create_database_engine(operational_database_url)
        task_repository_instance = PostgresTaskRepository(
            session_factory=create_session_factory(db_engine)
        )
        task_manager_instance = TaskManager(
            task_repository=task_repository_instance,
            agent_registry=agent_registry_instance,
        )
    else:
        task_manager_instance = TaskManager(
            PROJECT_ROOT / "system" / "task-state.json",
            agent_registry=agent_registry_instance,
        )
    task_manager_instance.bind_agent_registry(agent_registry_instance)

    availability = availability_service or ProviderAvailabilityService()
    use_live_status_probes = (
        availability_service is None
        and codex_runner is None
        and claude_runner is None
        and openai_executor is None
    )
    codex_probe_enabled = use_live_status_probes or codex_auth_service is not None
    claude_probe_enabled = use_live_status_probes or claude_auth_service is not None
    if codex_probe_enabled:
        availability.register_status_probe(
            "codex",
            codex_auth.status,
            authentication_implies_operational=True,
        )
    if claude_probe_enabled:
        availability.register_status_probe(
            "claude",
            claude_auth.status,
            authentication_implies_operational=False,
        )
    application.state.provider_availability = availability
    codex_provider_executor = AvailabilityObservedExecutor(
        "codex",
        CodexChatExecutor(codex_cli_runner, cwd=PROJECT_ROOT, timeout=90.0),
        availability,
        task_manager=task_manager_instance,
    )
    codex_provider_adapter = CodexProviderAdapter(
        definition=next(
            definition
            for definition in PROVIDER_DEFINITIONS
            if definition.id == "codex"
        ),
        auth_service=codex_auth,
        executor=codex_provider_executor,
        availability=availability,
    )
    owns_provider_manager = provider_manager is None
    application.state.provider_manager = (
        create_provider_manager(codex_adapter=codex_provider_adapter)
        if owns_provider_manager
        else provider_manager
    )
    application.state.codex_provider_adapter = codex_provider_adapter
    application.state.chat_service = chat_service or create_managed_chat_service(
        manager,
        codex_cli_runner,
        claude_runner,
        availability,
        openai_executor,
        application.state.provider_manager,
        task_manager_instance,
    )
    application.state.agent_state_service = AgentRuntimeStateService()
    application.state.agent_execution_service = AgentExecutionService(
        application.state.chat_service,
        agent_registry_instance,
        application.state.agent_state_service,
    )
    application.state.morpheus_orchestration_service = MorpheusOrchestrationService(
        application.state.agent_execution_service,
        application.state.agent_state_service,
    )
    application.state.openai_gateway = OpenAIGateway()
    # Caminho legado (scraping headless + bridge de extensão Chrome): mantido
    # apenas para as rotas de ingest/heartbeat/bridge-status, sem collector
    # (nunca inicia Puppeteer sozinho) e fora do caminho operacional padrão.
    application.state.openai_balance_service = openai_balance_service or OpenAIBalanceService()
    # Caminho operacional padrão: baseline local + OpenAI Organization Costs
    # API oficial. Nunca abre navegador, nunca depende de aba/DOM.
    application.state.openai_costs_ledger_service = (
        openai_costs_ledger_service
        or OpenAICostsLedgerService(refresh_ms=_openai_balance_refresh_ms())
    )
    application.state.notification_broker = NotificationBroker()
    application.state.cowork_active = False
    application.state.attachments = {}
    application.state.pet_process = None
    action_registry = ActionRegistry()
    action_registry.register(create_app_open_definition())
    action_registry.register(create_file_open_definition())
    action_registry.register(create_file_resolve_definition())
    action_registry.register(create_excel_definition())
    action_registry.register(create_word_definition())
    action_registry.register(create_powerbi_open_definition())
    action_engine = ActionEngine(action_registry, task_manager_instance)
    application.state.task_manager = task_manager_instance
    application.state.action_registry = action_registry
    application.state.action_engine = action_engine
    application.state.action_dispatcher = ActionDispatcher()
    application.state.agent_registry = agent_registry_instance

    if owns_provider_manager and codex_probe_enabled:
        async def refresh_codex_provider() -> None:
            await availability.refresh_provider("codex")

        application.router.add_event_handler("startup", refresh_codex_provider)
    async def reconcile_task_manager() -> None:
        task_manager_instance.reconcile()

    application.router.add_event_handler("startup", reconcile_task_manager)
    application.include_router(health_router)
    application.include_router(diagnostics_router)
    application.include_router(executors_router)
    application.include_router(codex_auth_router)
    application.include_router(claude_auth_router)
    application.include_router(chat_router)
    application.include_router(notifications_router)
    application.include_router(voice_router)
    application.include_router(workspace_router)
    application.include_router(providers_router)
    application.include_router(compatibility_router)
    application.include_router(tasks_router)
    application.include_router(automation_router)
    application.include_router(agents_router)

    @application.on_event("shutdown")
    async def interrupt_active_tasks() -> None:
        await task_manager_instance.shutdown()

    @application.post("/api/jarvis/shutdown", status_code=202)
    async def shutdown_jarvis(
        request: Request,
        background_tasks: BackgroundTasks,
    ) -> dict[str, str]:
        client_host = request.client.host if request.client else ""
        if not _is_loopback_host(client_host):
            raise HTTPException(
                status_code=403,
                detail="Shutdown permitido somente pela interface local.",
            )

        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") not in LOCAL_ORIGINS:
            raise HTTPException(
                status_code=403,
                detail="Origem nao autorizada para desligar o Jarvis.",
            )

        server = getattr(request.app.state, "uvicorn_server", None)
        if server is None:
            raise HTTPException(
                status_code=503,
                detail="Controle de shutdown indisponivel nesta execucao.",
            )

        if getattr(request.app.state, "jarvis_shutdown_requested", False):
            return {"status": "shutting_down"}

        request.app.state.jarvis_shutdown_requested = True
        background_tasks.add_task(_request_uvicorn_shutdown, server)
        return {"status": "shutting_down"}

    application.mount(
        "/",
        StaticFiles(directory=PUBLIC_DIR, html=True, check_dir=True),
        name="public",
    )
    return application


app = create_app()
