# Arquitetura do JARVIS

Como o JARVIS funciona por dentro.

---

## Stack Completo

```
Frontend e voz -> FastAPI/Python -> executores e integracoes
```

## Componentes

### Servidor — `run.py` + `app/`
- **Porta:** 8000
- **Framework:** FastAPI/Uvicorn
- Gerencia voz, tarefas, APIs, screenshots, Excel e frontend estatico

### [[Voz em Tempo Real]]
- **STT:** Web Speech API (0ms latencia) + Whisper fallback
- **LLM:** GPT-4o Realtime para conversa
- **TTS:** Streaming por sentenca, voices: ash (EN) / nova (BR)
- **VAD:** Silence 1800ms, threshold 8, min record 1200ms
- **Audio:** 64kbps WebM Opus
- **Modo continuo:** Loop hands-free com 1.5s pausa

### [[Execucao de Tarefas]]
- **Motor:** Claude Code CLI (spawn)
- **Warm Pool:** Opus x 1, Sonnet x 3, Haiku x 4 pre-spawned
- **Roteamento:** Opus (arquitetura), Sonnet (build), Haiku (rapido)
- **Fast-path:** Regex ~100ms para comandos comuns
- **Smart fast-path:** GPT-4o-mini gera shell commands ~500ms
- **Paralelo:** `detectParallelTasks()` divide multi-tarefas

### [[Visao de Tela]]
- **Screenshot:** `system/screenshot.py` — captura todos monitores
- **Cursor:** `system/screenshot-cursor.py` — 800x600 ao redor do cursor
- **Analise:** GPT-4o vision API

### [[Computer Use]]
- **Acoes:** `system/computer-action.py` via pyautogui
- Click, doubleclick, rightclick, move, type, hotkey, press, scroll, drag
- Type usa clipboard (suporta unicode)

### [[Excel ao Vivo]]
- **Criar:** openpyxl + `start "" CAMINHO`
- **Editar:** API `/api/excel-live` -> WM_CLOSE graceful -> openpyxl -> reopen
- **Sem recovery:** AutoRecover desabilitado via registry
- Ver [[Decisoes Tecnicas#Excel WM_CLOSE]]

## Endpoints Principais

| Endpoint | Funcao |
|----------|--------|
| `/api/health` | Status do sistema |
| `/api/chat` | Chat com Claude CLI |
| `/api/excel-live` | Edicao Excel ao vivo |
| `/api/screenshot` | Captura de tela |
| `/api/computer-use` | Mouse/teclado |
| `/api/computer-use/task` | Tarefa visual complexa |
| `/api/weather` | Clima via wttr.in |
| `/api/pdf` | Gera PDF de HTML |
| `/api/read-file` | Le arquivo |
| `/api/read-excel` | Le planilha |

## Rate Limiter
- 500ms minimo entre chamadas OpenAI
- 3 retries com delays de 3s/6s em 429

## Dependencias
- `requirements.txt`: backend FastAPI e automacoes Python
- `package.json`: Puppeteer para ferramentas auxiliares, billing e testes
- `launcher/package.json` e `pet/package.json`: aplicativos Electron preservados
