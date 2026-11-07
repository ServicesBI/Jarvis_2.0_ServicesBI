# mss

**Tipo:** Biblioteca Python para captura de tela

## O que e

mss (Multiple Screen Shot) e uma biblioteca Python ultra-rapida para captura de tela. Mais performatica que alternativas como PIL.ImageGrab, com suporte nativo a multiplos monitores.

## Como o JARVIS usa

- Captura screenshots de todos os monitores simultaneamente
- **Stitching multi-monitor:** Combina capturas de multiplos monitores em uma unica imagem usando PIL
- Screenshots sao enviados codificados em base64 para analise via [[Tecnologias/OpenAI API]] (GPT-4o Vision)
- Integrado com [[Tecnologias/pyautogui]] para ciclo captura -> analise -> acao
- Usado no pipeline de [[Computer Use]] e [[Visao de Tela]]

## Pipeline de Captura

```
mss.grab() -> PIL.Image (stitching) -> base64 -> OpenAI Vision -> analise
```

## Gotchas

- Captura multi-monitor retorna coordenadas relativas a cada monitor — precisa calcular offset global
- Imagens em resolucao nativa (4K, etc.) geram base64 muito grandes — resize pode ser necessario
- Em setups com monitores de DPI diferente, o stitching pode desalinhar
- Performance: ~20-50ms por captura full screen (muito mais rapido que PIL.ImageGrab)

## Links

- [[Visao de Tela]]
