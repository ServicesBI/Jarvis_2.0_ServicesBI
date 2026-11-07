(function exposeAgentStatusView(root) {
  const STATUS_VIEWS = Object.freeze({
    idle: Object.freeze({ status: 'idle', label: 'IDLE' }),
    working: Object.freeze({ status: 'working', label: 'WORKING' }),
    waiting: Object.freeze({ status: 'waiting', label: 'WAITING' }),
    error: Object.freeze({ status: 'error', label: 'ERROR' }),
  });

  function projectAgentStatus(status) {
    if (typeof status !== 'string' || !Object.hasOwn(STATUS_VIEWS, status)) {
      throw new RangeError(`Unsupported agent status: ${String(status)}`);
    }
    return STATUS_VIEWS[status];
  }

  root.AgentStatusView = Object.freeze({ projectAgentStatus });
})(typeof globalThis !== 'undefined' ? globalThis : window);
