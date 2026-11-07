# Puppeteer

**Tipo:** Biblioteca de automacao de browser (Chrome/Chromium)
**Config:** `PUPPETEER_SKIP_DOWNLOAD=true`

## O que e

Puppeteer e uma biblioteca Node.js que controla Chrome/Chromium via protocolo DevTools. Permite navegar paginas, gerar PDFs, tirar screenshots e automatizar interacoes web.

## Como o JARVIS usa

- **Geracao de PDFs:** Converte HTML em PDF de alta qualidade
- Usa o Chrome ja instalado no sistema (nao baixa Chromium proprio)
- `PUPPETEER_SKIP_DOWNLOAD=true` — evita download de ~170MB do Chromium bundled
- Usado por `system/gen-pdf.cjs`, billing, consulta de saldo e testes visuais
- Configurado para modo headless (sem janela visivel)

## Gotchas

- `PUPPETEER_SKIP_DOWNLOAD=true` e **obrigatorio** — sem isso, `npm install` tenta baixar Chromium inteiro
- Precisa que Chrome esteja instalado no sistema e no PATH padrao
- Em Windows, o caminho do Chrome pode variar entre `Program Files` e `Program Files (x86)`
- Processos Chrome headless podem ficar orfaos se o server crashar — cleanup necessario

## Links

- [[Arquitetura]]
