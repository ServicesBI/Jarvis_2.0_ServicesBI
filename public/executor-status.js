// Fonte unica de decisao de status do EXECUTOR (SERVER ONLINE) e do AI MODELS.
// Script isomorfico de proposito: sem import/export, para poder ser carregado
// tanto por <script src="executor-status.js"> no navegador quanto por node:test.
(function attachExecutorStatus(target) {
  'use strict';

  function formatProviderStatus(provider) {
    const status = provider && provider.status || 'unknown';
    if (status === 'online' || status === 'ok') return { text: 'ONLINE', tone: 'online', ok: true };
    // Instalado/autenticado mas nunca observado em uma execucao real: a UI
    // nao pode dizer READY (isso implicaria online/verde) sem evidencia real
    // de capability. Mostra CHECK ate record_success() confirmar operational.
    if (status === 'checking' || (provider && provider.reason === 'capability_not_validated')) {
      return { text: 'CHECK', tone: 'neutral', ok: false };
    }
    if (status === 'offline' || status === 'not_installed') return { text: 'OFF', tone: 'error', ok: false };
    if (status === 'not_authenticated' || status === 'auth') return { text: 'AUTH', tone: 'error', ok: false };
    if (status === 'entitlement_unavailable') return { text: 'PLAN', tone: 'error', ok: false };
    if (status === 'error' || status === 'limit' || status === 'off') return { text: 'ERROR', tone: 'error', ok: false };
    return { text: 'UNKNOWN', tone: 'error', ok: false };
  }

  // AUTO usa a mesma prioridade de roteamento do backend (codex, depois claude).
  function getAutoExecutorStatus(providers) {
    if (providers && providers.codex && providers.codex.status === 'online') return providers.codex;
    if (providers && providers.claude && providers.claude.status === 'online') return providers.claude;
    return { status: 'error' };
  }

  // Ponto unico de leitura: SERVER ONLINE e AI MODELS devem chamar esta funcao
  // com o mesmo payload de /api/providers/health, nunca reimplementar a escolha.
  function resolveExecutorStatus(activeExecutor, providers) {
    const source = activeExecutor === 'auto'
      ? getAutoExecutorStatus(providers)
      : providers && providers[activeExecutor];
    return formatProviderStatus(source);
  }

  // Guarda de sequenciamento: garante que apenas o resultado da chamada mais
  // recentemente INICIADA possa ser aplicado, mesmo que uma chamada mais antiga
  // (ex.: de uma troca de modo anterior) resolva depois dela.
  function createStalenessGuard() {
    let latest = 0;
    return {
      next() {
        latest += 1;
        return latest;
      },
      isCurrent(id) {
        return id === latest;
      },
    };
  }

  // Orquestra uma leitura de health com protecao contra sobrescrita fora de ordem.
  // Espelha o trecho relevante de updateHealth() em script.js, mas testavel sem DOM.
  async function refreshExecutorStatus({ activeExecutor, fetchProviders, guard, onResult }) {
    const requestId = guard.next();
    const providers = await fetchProviders();
    if (!guard.isCurrent(requestId)) return 'stale-discarded';
    onResult(resolveExecutorStatus(activeExecutor, providers));
    return 'applied';
  }

  target.ExecutorStatus = {
    formatProviderStatus,
    getAutoExecutorStatus,
    resolveExecutorStatus,
    createStalenessGuard,
    refreshExecutorStatus,
  };
})(typeof window !== 'undefined' ? window : globalThis);
