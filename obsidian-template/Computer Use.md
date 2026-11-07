# Computer Use

Controle total do mouse e teclado.

---

## Script: `system/computer-action.py`

Usa `pyautogui` para executar acoes no PC.

## Acoes Disponiveis

| Acao | Descricao |
|------|-----------|
| `click` | Clique esquerdo em coordenada |
| `doubleclick` | Duplo clique |
| `rightclick` | Clique direito |
| `move` | Move o cursor |
| `type` | Digita texto (via clipboard pra unicode) |
| `hotkey` | Atalho de teclado (ex: Ctrl+C) |
| `press` | Pressiona tecla (ex: Enter) |
| `scroll` | Scroll up/down |
| `drag` | Arrasta de A ate B |

## Type via Clipboard

Para suportar caracteres especiais e emojis:
1. Copia texto para clipboard (`pyperclip`)
2. Cola com `Ctrl+V`
3. Funciona com qualquer idioma/emoji

## Integracao com [[Visao de Tela]]

Fluxo completo:
1. Captura screenshot
2. GPT-4o analisa -> identifica elementos
3. Calcula coordenadas
4. Executa acao (click, type, etc.)
5. Captura novo screenshot pra verificar
