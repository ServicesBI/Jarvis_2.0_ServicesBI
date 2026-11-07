# openpyxl

**Tipo:** Biblioteca Python para Excel (.xlsx)

## O que e

openpyxl e uma biblioteca Python para ler e escrever arquivos Excel no formato `.xlsx`. Suporta formatacao, formulas, graficos e estilos.

## Como o JARVIS usa

- Cria planilhas Excel novas a partir de dados estruturados
- Edita planilhas existentes (adicionar linhas, modificar celulas, formatacao)
- Parte da solucao **Excel ao Vivo** — edicao de planilhas enquanto estao abertas
- Usa abordagem `WM_CLOSE` para fechar Excel antes de salvar e reabrir depois

## Solucao WM_CLOSE

O Excel trava o arquivo `.xlsx` enquanto esta aberto, impedindo que openpyxl salve alteracoes. A solucao:

1. Detecta se o arquivo esta aberto no Excel
2. Envia `WM_CLOSE` para fechar o Excel graciosamente
3. openpyxl faz as alteracoes e salva
4. Reabre o arquivo no Excel

## Gotchas

- **PermissionError** — Erro mais comum. Acontece quando o arquivo esta aberto no Excel e a solucao WM_CLOSE falha
- Arquivos `.xls` (formato antigo) **nao sao suportados** — apenas `.xlsx`
- Formatacao complexa (tabelas dinamicas, macros) pode ser perdida ao salvar
- Encoding de caracteres especiais precisa de atencao

## Links

- [[Excel ao Vivo]]
- [[Decisoes Tecnicas]]
