"""Static provider catalog and dependency factory for the central manager."""

from app.providers.contracts import ProviderAdapter
from app.providers.manager import ProviderManager
from app.providers.models import (
    AdapterKind,
    AuthMethod,
    Capability,
    ProviderAction,
    ProviderCategory,
    ProviderDefinition,
)


PROVIDER_DEFINITIONS = (
    ProviderDefinition(
        id="codex",
        name="Codex / ChatGPT",
        category=ProviderCategory.AI,
        description="Codex and ChatGPT coding provider contract.",
        capabilities=(Capability.CHAT, Capability.CODE),
        auth_methods=(AuthMethod.CLI_OAUTH,),
        supports_multiple_accounts=False,
        adapter_kind=AdapterKind.CLI,
        actions=(
            ProviderAction.STATUS,
            ProviderAction.CONNECT,
            ProviderAction.DISCONNECT,
            ProviderAction.EXECUTE,
        ),
    ),
    ProviderDefinition(
        id="openai",
        name="OpenAI API",
        category=ProviderCategory.AI,
        description="OpenAI API provider contract.",
        capabilities=(
            Capability.CHAT,
            Capability.STT,
            Capability.TTS,
            Capability.REALTIME,
            Capability.VISION,
        ),
        auth_methods=(AuthMethod.API_KEY,),
        supports_multiple_accounts=True,
        adapter_kind=AdapterKind.PYTHON,
        actions=(ProviderAction.STATUS, ProviderAction.TEST, ProviderAction.EXECUTE),
    ),
    ProviderDefinition(
        id="claude",
        name="Claude",
        category=ProviderCategory.AI,
        description="Claude coding provider contract.",
        capabilities=(Capability.CHAT, Capability.CODE),
        auth_methods=(AuthMethod.CLI_OAUTH,),
        supports_multiple_accounts=False,
        adapter_kind=AdapterKind.CLI,
        actions=(
            ProviderAction.STATUS,
            ProviderAction.CONNECT,
            ProviderAction.DISCONNECT,
            ProviderAction.EXECUTE,
        ),
    ),
    ProviderDefinition(
        id="gemini",
        name="Gemini",
        category=ProviderCategory.AI,
        description="Google Gemini provider contract.",
        capabilities=(Capability.CHAT, Capability.VISION),
        auth_methods=(AuthMethod.API_KEY, AuthMethod.OAUTH2),
        supports_multiple_accounts=True,
        adapter_kind=AdapterKind.EXTERNAL,
        actions=(
            ProviderAction.STATUS,
            ProviderAction.CONNECT,
            ProviderAction.DISCONNECT,
            ProviderAction.TEST,
            ProviderAction.EXECUTE,
        ),
    ),
    ProviderDefinition(
        id="google-account",
        name="Google Account",
        category=ProviderCategory.CLOUD,
        description="Google Workspace account provider contract.",
        capabilities=(
            Capability.DRIVE,
            Capability.EMAIL,
            Capability.CALENDAR,
            Capability.SHEETS,
            Capability.FILES,
        ),
        auth_methods=(AuthMethod.OAUTH2,),
        supports_multiple_accounts=True,
        adapter_kind=AdapterKind.EXTERNAL,
        actions=(
            ProviderAction.STATUS,
            ProviderAction.CONNECT,
            ProviderAction.DISCONNECT,
            ProviderAction.REFRESH,
            ProviderAction.TEST,
        ),
    ),
    ProviderDefinition(
        id="microsoft-account",
        name="Microsoft Account",
        category=ProviderCategory.MICROSOFT,
        description="Microsoft account provider contract.",
        capabilities=(Capability.FILES, Capability.EMAIL, Capability.CALENDAR),
        auth_methods=(AuthMethod.OAUTH2,),
        supports_multiple_accounts=True,
        adapter_kind=AdapterKind.EXTERNAL,
        actions=(
            ProviderAction.STATUS,
            ProviderAction.CONNECT,
            ProviderAction.DISCONNECT,
            ProviderAction.REFRESH,
            ProviderAction.TEST,
        ),
    ),
    ProviderDefinition(
        id="powerbi",
        name="Power BI",
        category=ProviderCategory.MICROSOFT,
        description="Microsoft Power BI provider contract.",
        capabilities=(Capability.BI,),
        auth_methods=(AuthMethod.OAUTH2,),
        supports_multiple_accounts=True,
        adapter_kind=AdapterKind.EXTERNAL,
        actions=tuple(ProviderAction),
    ),
    ProviderDefinition(
        id="vscode",
        name="VS Code",
        category=ProviderCategory.DEVELOPMENT,
        description="Local Visual Studio Code provider contract.",
        capabilities=(Capability.CODE, Capability.FILES, Capability.LOCAL_TOOL),
        auth_methods=(AuthMethod.LOCAL,),
        supports_multiple_accounts=False,
        adapter_kind=AdapterKind.LOCAL,
        actions=(ProviderAction.STATUS, ProviderAction.TEST, ProviderAction.EXECUTE),
    ),
    ProviderDefinition(
        id="erp-generic",
        name="ERP Framework",
        category=ProviderCategory.ERP,
        description="Generic ERP integration provider contract.",
        capabilities=(Capability.ERP_READ, Capability.ERP_WRITE),
        auth_methods=(
            AuthMethod.USER_PASSWORD,
            AuthMethod.API_KEY,
            AuthMethod.OAUTH2,
            AuthMethod.CERTIFICATE,
            AuthMethod.CUSTOM,
        ),
        supports_multiple_accounts=True,
        adapter_kind=AdapterKind.EXTERNAL,
        actions=tuple(ProviderAction),
    ),
)


def create_provider_manager(
    *, codex_adapter: ProviderAdapter | None = None
) -> ProviderManager:
    """Build an isolated manager populated only with static definitions."""

    manager = ProviderManager()
    for definition in PROVIDER_DEFINITIONS:
        manager.register_definition(definition)
    if codex_adapter is not None:
        manager.register_adapter("codex", codex_adapter)
    return manager
