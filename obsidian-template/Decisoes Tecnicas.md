# Decisoes Tecnicas

Escolhas que foram feitas e por que. Cada decisao e uma licao armazenada no [[Cerebro 3 — Obsidian]].
Todas envolvem a [[Arquitetura]] do JARVIS e foram validadas na pratica.

---

## Excel WM_CLOSE
**Relacionado:** [[Excel ao Vivo]]

**Problema:** Editar planilha aberta no Excel
**5 tentativas que falharam:**
1. `xlwings` COM automation -> erro -2147467259
2. `openpyxl` direto -> PermissionError (Excel trava o arquivo)
3. `taskkill /F` -> cria painel de Recuperacao
4. `Alt+F4` via pyautogui -> foco inconsistente
5. `taskkill` sem /F -> dialogo de salvar

**Solucao:** `WM_CLOSE` via ctypes + AutoRecover desabilitado via registry
**Resultado:** 10/10 edicoes, zero recovery

---

## Voz Hybrid
**Relacionado:** [[Voz em Tempo Real]], [[Skill — Voice Realtime]]

**Escolha:** Web Speech (0ms) + Claude streaming (300ms) + sentence TTS (150ms) = ~600ms
**Por que:** Melhor custo-beneficio vs Cascading (1-3s) e Realtime S2S (caro)

---

## Setup Obrigatorio

**Decisao:** Tudo que o JARVIS precisa e ERRO FATAL se nao instalar. Nada e warning.
**Filosofia:** "Tudo o que e necessario e obrigatorio"

Validado pelo [[Conclave]] — o Advogado encontrou 3 problemas CRITICOS antes da entrega.

---

## Orb Rainbow Sphere

Particulas so em formato esfera (sem face/ear/brain). Cores arco-iris. ~250 particulas.
