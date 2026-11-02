---
name: video-takes-to-cut
description: "Transforma uma pasta de takes de vídeo (sem áudio, ex. linha de produção) em um único vídeo curto pronto, no aspect ratio e duração pedidos. Use SEMPRE que o usuário pedir para montar/gerar um vídeo a partir de uma pasta de takes/gravações, com frases como 'faça um vídeo de X segundos com os takes da pasta Y', 'monta um vídeo 9:16 com esses takes', 'corta os melhores momentos dessa pasta de vídeos', mesmo sem a palavra 'skill'. Cobre apenas vídeo sem trilha de fala relevante (scoring é 100% visual: nitidez, movimento, estabilidade, exposição) — se os takes tiverem fala/narração importante, avise o usuário que este pipeline não considera áudio."
---

# video-takes-to-cut

Pipeline de 3 passos: **análise mecânica** (script) → **decisão criativa** (você, o agente, olhando o contact sheet) → **renderização** (script). Você é a camada de IA que falta nos scripts — eles não decidem nada, só medem e executam.

## Quando usar

- O usuário aponta uma pasta com múltiplos arquivos de vídeo (takes de uma gravação/produção) e pede um vídeo final único, curto, num aspect ratio específico.
- Os takes **não têm áudio relevante** (ou o áudio não deve ser considerado). Se o usuário mencionar que há fala/narração importante nos takes, pare e avise: este pipeline pontua apenas por qualidade visual, não por conteúdo falado — sugira revisar manualmente ou adaptar o scoring antes de prosseguir.

## Passo 1 — Analisar a pasta

Rode o script de análise, que detecta sub-cenas dentro de cada take, pontua cada uma (nitidez, movimento relevante, tremor de câmera, exposição) e gera thumbnails:

```bash
# No Windows use 'python', no Linux/macOS use 'python3'
# Se o comando for executado fora da pasta da skill, use o caminho completo <SKILL_DIR>/scripts/analyze.py
python scripts/analyze.py --folder "<PASTA_DOS_TAKES>" --outdir "<PASTA_DE_TRABALHO>" \
  --min-scene-dur 0.8 --max-candidates 60 --sample-fps 4
```

- `<PASTA_DE_TRABALHO>` é um diretório temporário seu (ex. pasta de trabalho temporária do projeto ou dentro do output do usuário) — vai conter `candidates.json`, `contact_sheet.jpg` e `thumbs/`.
- Se a pasta tiver dezenas de takes longos, isso pode levar alguns minutos (é CPU-bound, um vídeo por vez).

## Passo 2 — Decidir a sequência (é aqui que você pensa, não o script)

1. **Veja `contact_sheet.jpg`** (abra/leia o arquivo de imagem com sua ferramenta de visualização — em Claude Code, a ferramenta `view`; no Gemini / Antigravity, leia/abra o arquivo diretamente). Cada célula mostra thumbnail, `segment_id`, score 0-100, arquivo fonte e intervalo de tempo.
2. Leia `candidates.json` para os números exatos (start/end/duration/score de cada segmento).
3. Monte a sequência final respeitando:
   - **Duração alvo pedida pelo usuário**, com tolerância de ±10%. A soma das durações dos clipes escolhidos deve ficar perto disso, descontando o crossfade (cada corte "come" ~0.25s do total — veja a fórmula no passo 3).
   - **Priorize score alto**, mas não pegue só os 3 melhores se forem do mesmo take/fase — busque diversidade (evite dois segmentos seguidos do mesmo arquivo fonte, a menos que a narrativa peça continuidade).
   - **Ordem com lógica de produção**: se os nomes de arquivo ou a ordem cronológica sugerirem etapas de um processo (ex. "01_materia_prima", "02_montagem", "03_acabamento"), respeite essa progressão em vez de embaralhar.
   - Você pode **recortar um segmento candidato** (usar `in`/`out` menores que o candidato inteiro) se ele for mais longo do que o necessário — não precisa usar o segmento inteiro.
   - Descarte segmentos com score muito baixo (ex. <20) mesmo que sejam necessários para bater a duração — é melhor um vídeo 10% mais curto que o alvo do que incluir um take ruim.
4. Escreva o arquivo de decisão, ex. `<PASTA_DE_TRABALHO>/selection.json`:

```json
{
  "target_duration": 30,
  "aspect": "9:16",
  "segments": [
    {"segment_id": "take1_acao_000", "in": 0.0, "out": 7.0},
    {"segment_id": "take3_detalhe_000", "in": 2.0, "out": 7.25}
  ]
}
```

## Passo 3 — Renderizar

```bash
# No Windows use 'python', no Linux/macOS use 'python3'
# Se o comando for executado fora da pasta da skill, use o caminho completo <SKILL_DIR>/scripts/render.py
python scripts/render.py --selection "<PASTA_DE_TRABALHO>/selection.json" \
  --candidates "<PASTA_DE_TRABALHO>/candidates.json" \
  --output "<CAMINHO_DO_VIDEO_FINAL>.mp4" --crossfade 0.25
```

- O script já faz **smart-crop** para o aspect ratio pedido (9:16, 16:9, 1:1 ou 4:5), centrado no ponto de maior movimento de cada segmento (calculado no passo 1) — não simplesmente corta ao centro geométrico.
- Aplica crossfade de 0.25s entre cortes por padrão (ajustável com `--crossfade 0`, para cortes secos, se o usuário preferir um ritmo mais rápido/produção industrial).
- No final, o script imprime a duração real obtida — confira se bateu com o alvo; se estourou/faltou mais de ~10%, ajuste `selection.json` e rode `render.py` de novo (não precisa refazer o `analyze.py`).
- Salve o resultado no caminho indicado pelo usuário e informe a duração final e os arquivos gerados.

## Notas de calibração do scoring

- O score é **relativo aos candidatos da mesma pasta** (normalizado 0-100 dentro do lote) — não é uma nota absoluta de qualidade de vídeo. Rodar `analyze.py` em pastas diferentes não gera scores comparáveis entre si.
- `motion_raw` mede movimento geral, sem distinguir "movimento de produção relevante" de "câmera tremendo" além do proxy de `jitter_raw` (variação da diferença frame-a-frame). Em takes com muita vibração de câmera de mão, revise visualmente antes de confiar cegamente no score.
- Se os takes tiverem uma pessoa/produto que deveria ficar sempre em foco, e o crop automático por movimento não estiver funcionando bem, informe o usuário que dá para trocar por detecção de objeto/rosto (YOLO/face-detector) no lugar do centróide de movimento — é uma extensão do `analyze.py`, não coberta nesta versão.

## Anti-padrões

- Não pule o Passo 2 tentando decidir a sequência só lendo `candidates.json` sem olhar `contact_sheet.jpg` — os números não capturam se o enquadramento faz sentido visualmente.
- Não rode `render.py` sem antes conferir que a soma das durações do `selection.json` bate com o alvo — o script não trunca automaticamente para caber no tempo.
- Não assuma áudio: os scripts sempre descartam a trilha de áudio (`-an`). Se o usuário quiser música de fundo depois, isso é um passo separado (adicionar trilha com ffmpeg), não coberto aqui.
