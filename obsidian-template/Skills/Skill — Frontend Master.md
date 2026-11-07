# Skill — Frontend Master (2026)

Expertise de UI/UX nivel mundial. Parte do [[Cerebro 2 — Mega-Brain]].

---

## Filosofia de Design

- **Purposeful motion** — Toda animacao tem razao de existir
- **Perceived performance** — Parecer rapido e tao importante quanto ser rapido
- **Craftsmanship** — Cada pixel importa
- **Dark mode first** — Design comeca no escuro
- **Reduced motion respect** — Acessibilidade acima de estetica

## CSS Architecture (2026)

- **Design tokens** — Variaveis centralizadas (cores, espacamento, tipografia)
- **Glassmorphism** — GPU-accelerated, `backdrop-filter`
- **Scroll-driven animations** — `animation-timeline: scroll()`
- **CSS containment** — `contain: layout style paint`
- **Container queries** — `@container` pra componentes responsivos
- **oklch()** — Espaco de cor perceptualmente uniforme

## Timing Bible

| Elemento | Duracao |
|----------|---------|
| Button press | 120-150ms |
| Modal open | 200-250ms |
| Page transition | 300-350ms |
| Hover state | 100ms |
| Tooltip appear | 150ms |

## Tipografia

- **Fluid:** `clamp(1rem, 0.5rem + 1vw, 1.25rem)`
- **Scale:** 1.250 Major Third ratio
- **Font:** Inter (sans-serif)

## Performance Targets

| Metrica | Target |
|---------|--------|
| LCP | < 2.5s |
| INP | < 200ms |
| CLS | < 0.1 |

## Stack 2026

shadcn/ui, Framer Motion, Lucide icons, Inter font, oklch(), Playwright, Vitest

## Acessibilidade

- Focus management com `focus-visible`
- `aria-live` pra conteudo dinamico
- Contraste minimo 4.5:1 (AA), ideal 7:1 (AAA)
- `prefers-reduced-motion` sempre respeitado

## Referencias de Design

Linear, Vercel, Stripe, Apple, Raycast
