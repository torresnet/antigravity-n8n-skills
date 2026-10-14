# video-takes-to-cut

Skill no formato aberto **Agent Skills** (SKILL.md + scripts) — funciona tanto
em **Claude Code** quanto em **Gemini CLI**, sem alterações. Transforma uma
pasta de takes de vídeo (sem áudio) em um único vídeo curto, no formato e
duração pedidos.

## Instalar

### Claude Code
- **Global:** copie para `~/.claude/skills/video-takes-to-cut` (no Windows: `%USERPROFILE%\.claude\skills\video-takes-to-cut`)
- **Projeto local:** copie para `.claude/skills/video-takes-to-cut`

### Gemini (Antigravity & Gemini CLI)
- **Global Antigravity:** `%USERPROFILE%\.gemini\config\skills\video-takes-to-cut`
- **Global Gemini CLI:** `%USERPROFILE%\.gemini\skills\video-takes-to-cut`
- **Projeto local:** `.agents/skills/video-takes-to-cut` (ou `.gemini/skills/video-takes-to-cut`)

### Dependências
1. Instale as dependências Python:
   ```bash
   pip install -r requirements.txt
   ```
2. Garanta que `ffmpeg` e `ffprobe` estejam no PATH (`ffmpeg -version`).
3. No Windows utilize o comando `python`; no Linux/macOS utilize `python3`.

## Usar

Dentro de um projeto/pasta onde a skill está instalada (Claude Code ou
Gemini CLI), basta pedir:

> Faça um vídeo no formato 9:16 de 30 segundos com os takes da pasta ./takes_producao

A skill (ver `SKILL.md`) roda `scripts/analyze.py` para pontuar os takes,
Claude decide a sequência olhando o contact sheet gerado, e
`scripts/render.py` monta o vídeo final.

## Estrutura

- `SKILL.md` — instruções que o Claude Code lê e segue.
- `scripts/analyze.py` — detecção de cena + scoring visual (nitidez, movimento, tremor, exposição) + contact sheet.
- `scripts/render.py` — smart-crop para o aspect ratio alvo + crossfade + render final.
- `requirements.txt` — dependências Python (opencv-python-headless, numpy). ffmpeg é dependência de sistema.

## Limitações conhecidas

- Assume takes sem áudio relevante (o áudio é sempre descartado).
- Crop automático usa o centróide de movimento como proxy de "o que importa no quadro" — não é detecção de objeto/rosto. Para produtos/pessoas específicas, seria necessário estender `analyze.py` com um detector (ex. YOLO).
- Scores são relativos ao lote analisado, não uma métrica absoluta.
