(function (scope) {
  'use strict';
  const normalize = value => String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/\s+/g, ' ').trim().toLowerCase();
  const money = value => {
    const matches = [...String(value || '').matchAll(/(?:US\s*)?\$\s*(\d[\d,]*\.\d{2})/gi)];
    if (matches.length !== 1) return null;
    const parsed = Number(matches[0][1].replace(/,/g, ''));
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
  };
  function parseBalanceCards(cards) {
    const values = cards.filter(card => normalize(card?.label) === 'credit balance').map(card => money(card.value)).filter(value => value !== null);
    if (!values.length) throw new Error('BALANCE_NOT_FOUND');
    if (values.length !== 1) throw new Error('BALANCE_AMBIGUOUS');
    return values[0];
  }
  function readCreditBalance(root = document) {
    const labels = [...root.querySelectorAll('body *')].filter(element => {
      const direct = [...element.childNodes].filter(node => node.nodeType === 3).map(node => node.textContent).join(' ');
      return normalize(direct || element.getAttribute('aria-label')) === 'credit balance';
    });
    const cards = labels.map(label => {
      let container = label.nextElementSibling;
      if (!container || money(container.textContent) === null) container = label.parentElement;
      if (!container || money(container.textContent) === null) container = label.parentElement?.parentElement;
      return { label: 'Credit balance', value: container?.textContent || '' };
    });
    return parseBalanceCards(cards);
  }
  scope.JarvisBalanceParser = { parseBalanceCards, readCreditBalance };
})(globalThis);
