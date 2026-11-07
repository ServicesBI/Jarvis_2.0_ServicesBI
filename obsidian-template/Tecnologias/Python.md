# Python

**Versao:** 3.11

## O que e

Python e a linguagem usada pelo JARVIS para todas as operacoes que exigem controle direto do sistema operacional — automacao de desktop, captura de tela e manipulacao de arquivos Excel.

## Como o JARVIS usa

- **Computer Use:** Controle de mouse e teclado via [[Tecnologias/pyautogui]]
- **Screenshots:** Captura multi-monitor via [[Tecnologias/mss]] com stitching PIL
- **Excel:** Criacao e edicao de planilhas via [[Tecnologias/openpyxl]]
- Scripts Python sao spawnados como child processes pelo [[Tecnologias/Node.js]]
- Caminho absoluto usado para evitar conflitos com outras instalacoes Python

## Bibliotecas principais

| Biblioteca | Uso |
|---|---|
| [[Tecnologias/pyautogui]] | Mouse, teclado, automacao |
| [[Tecnologias/mss]] | Screenshot multi-monitor |
| [[Tecnologias/openpyxl]] | Excel (.xlsx) |
| PIL/Pillow | Processamento de imagens |

## Gotchas

- Deve ser a versao 3.11 especifica — outras versoes podem ter incompatibilidades com as dependencias
- `python.exe` vs `python3.exe` — no Windows e sempre `python.exe`
- Encoding UTF-8 precisa ser explicito nos scripts (`encoding='utf-8'`)
- Instalacao offline via bundle com wheels pre-baixados

## Links

- [[Computer Use]]
- [[Excel ao Vivo]]
- [[Visao de Tela]]
