# Node.js

**Runtime:** v24.x
**Tipo:** Runtime JavaScript auxiliar

## O que e

Node.js e o runtime JavaScript usado pelas ferramentas auxiliares do JARVIS. O backend HTTP operacional e FastAPI/Python.

## Como o JARVIS usa

- Executa o Launcher e o Desktop Pet em Electron
- Executa automacoes Puppeteer, billing e geracao auxiliar de PDF
- Executa testes Node dos modulos preservados de memoria e conexoes
- Nao abre porta de backend; o servidor operacional usa FastAPI em `127.0.0.1:8000`

## Gotchas

- Precisa estar no PATH do sistema para Electron, Puppeteer e testes auxiliares
- Os manifests de `launcher/` e `pet/` possuem dependencias independentes do manifesto raiz

## Links

- [[Arquitetura]]
