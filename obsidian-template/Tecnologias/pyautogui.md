# pyautogui

**Tipo:** Biblioteca Python para automacao de mouse e teclado

## O que e

pyautogui permite controlar programaticamente o mouse e teclado do sistema operacional. Simula cliques, movimentos, digitacao e atalhos de teclado.

## Como o JARVIS usa

- **Click:** Clique em coordenadas especificas da tela (`pyautogui.click(x, y)`)
- **Type:** Digitacao de texto (via clipboard para suporte Unicode)
- **Hotkey:** Atalhos de teclado (`pyautogui.hotkey('ctrl', 'c')`)
- **Scroll:** Rolagem de pagina (`pyautogui.scroll(amount)`)
- **Drag:** Arrastar elementos de um ponto a outro
- **moveTo:** Mover cursor para coordenadas especificas
- Integrado com [[Tecnologias/mss]] para captura de tela + acao coordenada
- Scripts chamados como child processes pelo [[Tecnologias/Node.js]]

## Solucao Unicode via Clipboard

`pyautogui.typewrite()` nao suporta caracteres Unicode (acentos, c cedilha, etc.). A solucao:

1. Copia o texto para o clipboard (`pyperclip.copy(text)`)
2. Executa `Ctrl+V` para colar (`pyautogui.hotkey('ctrl', 'v')`)

Isso garante que caracteres PT-BR sejam digitados corretamente.

## Gotchas

- **Unicode:** `typewrite()` so aceita ASCII — sempre usar clipboard para PT-BR
- **Fail-safe:** pyautogui tem fail-safe no canto superior esquerdo — mover mouse para (0,0) aborta o script
- **Coordenadas:** Dependem da resolucao e escala DPI do monitor
- **Timing:** Operacoes muito rapidas podem falhar — `pyautogui.PAUSE` configura delay entre acoes
- **Foco de janela:** A janela alvo precisa estar em foco para receber inputs

## Links

- [[Computer Use]]
