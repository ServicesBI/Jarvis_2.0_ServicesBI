# Excel ao Vivo

Cria e edita planilhas enquanto o usuario assiste.

---

## Criar Planilha

1. `openpyxl` cria o .xlsx com TODOS os dados pedidos
2. `start "" "CAMINHO/arquivo.xlsx"` abre no Excel
3. Usuario ve imediatamente

## Editar Planilha Aberta

Via API `POST /api/excel-live`:

```json
{
  "action": "write",
  "path": "C:/caminho/arquivo.xlsx",
  "operations": [
    {"cell": "A1", "value": "Produto"},
    {"cell": "B1", "value": 100},
    {"cell": "C1", "value": "=A1&B1"}
  ]
}
```

### Fluxo Interno

1. **WM_CLOSE** — fecha Excel graciosamente via `ctypes.user32.PostMessageW`
2. **Espera** — loop ate Excel fechar (max 5s)
3. **Edita** — `openpyxl` edita e salva
4. **Reabre** — `start "" "arquivo.xlsx"`

### Sem Painel de Recuperacao

- AutoRecover desabilitado: `reg add HKCU\...\Excel\Options /v AutoRecoverEnabled /d 0`
- Lock file (`~$arquivo.xlsx`) limpo automaticamente
- Registry Resiliency limpo se necessario

## Resultado

- **10/10 edicoes** sequenciais sem erro
- **Zero** painel de recuperacao
- **Batch:** todas as celulas em 1 ciclo close -> edit -> reopen

Ver [[Decisoes Tecnicas#Excel WM_CLOSE]]
