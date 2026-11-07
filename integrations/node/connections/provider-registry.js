const deepFreeze = (value) => {
  if (!value || typeof value !== 'object' || Object.isFrozen(value)) return value;
  Object.freeze(value);
  for (const nested of Object.values(value)) deepFreeze(nested);
  return value;
};

export const CONNECTION_CATEGORIES = deepFreeze([
  { id: 'ai-models', name: 'IA E MODELOS', order: 10 },
  { id: 'google-productivity', name: 'GOOGLE E PRODUTIVIDADE', order: 20 },
  { id: 'development', name: 'DESENVOLVIMENTO', order: 30 },
  { id: 'data-systems', name: 'DADOS E SISTEMAS', order: 40 }
]);

export const CONNECTION_TYPES = deepFreeze({
  API_KEY: 'api-key',
  OAUTH: 'oauth',
  CLI_LOGIN: 'cli-login',
  LOCAL_BRIDGE: 'local-bridge',
  CUSTOM: 'custom'
});

export const AUTH_TYPES = deepFreeze({
  API_KEY: CONNECTION_TYPES.API_KEY,
  OAUTH: CONNECTION_TYPES.OAUTH,
  CLI_LOGIN: CONNECTION_TYPES.CLI_LOGIN,
  LOCAL_BRIDGE: CONNECTION_TYPES.LOCAL_BRIDGE,
  CUSTOM: CONNECTION_TYPES.CUSTOM
});

export const IMPLEMENTATION_STATUSES = deepFreeze({
  NOT_CONFIGURED: 'not_configured',
  STRUCTURE_AVAILABLE: 'structure_available',
  UNAVAILABLE: 'unavailable',
  ERROR: 'error'
});

export const IMPLEMENTATION_STATUS_LABELS = deepFreeze({
  [IMPLEMENTATION_STATUSES.NOT_CONFIGURED]: 'NÃO CONFIGURADO',
  [IMPLEMENTATION_STATUSES.STRUCTURE_AVAILABLE]: 'ESTRUTURA DISPONÍVEL',
  [IMPLEMENTATION_STATUSES.UNAVAILABLE]: 'INDISPONÍVEL',
  [IMPLEMENTATION_STATUSES.ERROR]: 'ERRO'
});

export const PROVIDERS = deepFreeze([
  {
    id: 'openai',
    name: 'OpenAI',
    category: 'ai-models',
    description: 'Estrutura para um cadastro futuro de contas da API OpenAI, sem alterar a configuração atual.',
    connectionType: CONNECTION_TYPES.API_KEY,
    authTypes: [AUTH_TYPES.API_KEY],
    capabilities: ['Modelos de linguagem', 'Geração e análise de conteúdo'],
    supportsMultipleAccounts: true,
    implementationStatus: IMPLEMENTATION_STATUSES.STRUCTURE_AVAILABLE
  },
  {
    id: 'codex',
    name: 'Codex',
    category: 'ai-models',
    description: 'Estrutura para integração futura com o executor Codex, sem presumir sessão ativa.',
    connectionType: CONNECTION_TYPES.CLI_LOGIN,
    authTypes: [AUTH_TYPES.CLI_LOGIN],
    capabilities: ['Assistência de desenvolvimento', 'Execução de tarefas autorizadas'],
    supportsMultipleAccounts: false,
    implementationStatus: IMPLEMENTATION_STATUSES.STRUCTURE_AVAILABLE
  },
  {
    id: 'claude-api',
    name: 'Claude API',
    category: 'ai-models',
    description: 'Cadastro futuro de contas da API Claude e suas permissões declaradas.',
    connectionType: CONNECTION_TYPES.API_KEY,
    authTypes: [AUTH_TYPES.API_KEY],
    capabilities: ['Modelos de linguagem', 'Análise e geração de conteúdo'],
    supportsMultipleAccounts: true,
    implementationStatus: IMPLEMENTATION_STATUSES.NOT_CONFIGURED
  },
  {
    id: 'claude-code',
    name: 'Claude Code',
    category: 'ai-models',
    description: 'Estrutura para integração futura com o Claude Code, sem presumir autenticação local.',
    connectionType: CONNECTION_TYPES.CLI_LOGIN,
    authTypes: [AUTH_TYPES.CLI_LOGIN],
    capabilities: ['Assistência de desenvolvimento', 'Execução de tarefas autorizadas'],
    supportsMultipleAccounts: false,
    implementationStatus: IMPLEMENTATION_STATUSES.STRUCTURE_AVAILABLE
  },
  {
    id: 'gemini',
    name: 'Gemini',
    category: 'ai-models',
    description: 'Cadastro futuro de contas Gemini sem declarar uma conexão existente.',
    connectionType: CONNECTION_TYPES.API_KEY,
    authTypes: [AUTH_TYPES.API_KEY, AUTH_TYPES.OAUTH],
    capabilities: ['Modelos de linguagem', 'Análise multimodal'],
    supportsMultipleAccounts: true,
    implementationStatus: IMPLEMENTATION_STATUSES.NOT_CONFIGURED
  },
  {
    id: 'google-workspace',
    name: 'Google Workspace',
    category: 'google-productivity',
    description: 'Integração futura com serviços Google mediante autorização explícita por conta.',
    connectionType: CONNECTION_TYPES.OAUTH,
    authTypes: [AUTH_TYPES.OAUTH],
    capabilities: ['Drive, Agenda e Gmail', 'Fluxos de produtividade autorizados'],
    supportsMultipleAccounts: true,
    implementationStatus: IMPLEMENTATION_STATUSES.NOT_CONFIGURED
  },
  {
    id: 'vscode',
    name: 'VS Code',
    category: 'development',
    description: 'Integração local futura com o editor e os arquivos escolhidos pelo usuário.',
    connectionType: CONNECTION_TYPES.LOCAL_BRIDGE,
    authTypes: [AUTH_TYPES.LOCAL_BRIDGE],
    capabilities: ['Abrir arquivos autorizados', 'Contexto de desenvolvimento local'],
    supportsMultipleAccounts: false,
    implementationStatus: IMPLEMENTATION_STATUSES.NOT_CONFIGURED
  },
  {
    id: 'powerbi',
    name: 'Power BI',
    category: 'data-systems',
    description: 'Integração futura com workspaces e conjuntos de dados autorizados do Power BI.',
    connectionType: CONNECTION_TYPES.OAUTH,
    authTypes: [AUTH_TYPES.OAUTH],
    capabilities: ['Metadados de workspaces', 'Consulta de conjuntos de dados autorizados'],
    supportsMultipleAccounts: true,
    implementationStatus: IMPLEMENTATION_STATUSES.NOT_CONFIGURED
  },
  {
    id: 'erp-generic',
    name: 'Outros ERPs',
    category: 'data-systems',
    description: 'Estrutura genérica para integrações futuras com ERPs explicitamente autorizados.',
    connectionType: CONNECTION_TYPES.CUSTOM,
    authTypes: [AUTH_TYPES.CUSTOM, AUTH_TYPES.OAUTH, AUTH_TYPES.API_KEY],
    capabilities: ['Metadados de sistemas autorizados', 'Conectores específicos futuros'],
    supportsMultipleAccounts: true,
    implementationStatus: IMPLEMENTATION_STATUSES.NOT_CONFIGURED
  }
]);

const providersById = new Map(PROVIDERS.map((provider) => [provider.id, provider]));

export function getProviders() {
  return PROVIDERS;
}

export function getProviderById(providerId) {
  return providersById.get(String(providerId || '').trim()) || null;
}
