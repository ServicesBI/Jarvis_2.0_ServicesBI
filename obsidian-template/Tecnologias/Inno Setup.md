# Inno Setup

**Tipo:** Compilador de instaladores para Windows

## O que e

Inno Setup e um compilador gratuito de instaladores para Windows. Cria executaveis de setup profissionais a partir de scripts `.iss`.

## Como o JARVIS usa

- Compila o instalador offline completo do JARVIS
- Script `.iss` define toda a logica de instalacao
- Gera instalador contendo:
  - Node.js MSI
  - Python EXE
  - Wheels Python pre-baixados
  - node_modules completo
  - Chromium pre-cacheado para Puppeteer
- `PrivilegesRequired=lowest` — nao exige admin para instalar

## Configuracao chave

- **PrivilegesRequired=lowest** — Instalacao sem privilegios de administrador
- Instala em pasta do usuario por padrao
- Cria atalhos no menu iniciar e desktop
- Registra desinstalador automatico

## Gotchas

- O script `.iss` precisa ser recompilado manualmente quando ha mudancas
- Paths absolutos no script podem quebrar em maquinas diferentes
- `PrivilegesRequired=lowest` significa que a instalacao vai para `%LOCALAPPDATA%` e nao `Program Files`

## Links

- [[Arquitetura]]
