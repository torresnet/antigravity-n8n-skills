#!/usr/bin/env python3
"""
render.py — Renderiza o vídeo final a partir de uma selection.json (lista ordenada
de segmentos escolhidos), aplicando smart-crop para o aspect ratio alvo e
crossfade entre os cortes.

Uso:
  python3 render.py --selection selection.json --candidates candidates.json \
                     --output final.mp4 [--aspect 9:16] [--crossfade 0.25] \
                     [--workdir /tmp/render_work]

selection.json esperado:
{
  "target_duration": 30,
  "aspect": "9:16",
  "segments": [
    {"segment_id": "takeA_002", "in": 12.3, "out": 15.1},
    {"segment_id": "takeB_000", "in": 0.0, "out": 4.6}
  ]
}
"in"/"out" são relativos ao início do ARQUIVO FONTE (não do segmento candidato) —
permitem que o agente re-apare o segmento candidato original, se quiser um trecho
mais curto do que o candidato completo.

Dependências: ffmpeg/ffprobe no PATH.
"""
import argparse
import json
import subprocess
from pathlib import Path

ASPECT_RESOLUTIONS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Comando falhou: {' '.join(cmd)}\n{result.stderr[-2000:]}")
    return result


def probe_dims(path: str):
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
               "-show_entries", "stream=width,height",
               "-of", "csv=s=x:p=0", path])
    w, h = out.stdout.strip().split("x")
    return int(w), int(h)


def crop_filter(src_w, src_h, target_w, target_h, cx, cy):
    """Gera filtro crop+scale centrado em (cx, cy) fração 0..1, preservando o aspect alvo."""
    target_ratio = target_w / target_h
    src_ratio = src_w / src_h

    if src_ratio > target_ratio:
        # fonte mais larga que o alvo -> cortar largura
        crop_h = src_h
        crop_w = int(src_h * target_ratio)
    else:
        # fonte mais "alta"/estreita que o alvo -> cortar altura
        crop_w = src_w
        crop_h = int(src_w / target_ratio)

    max_x = max(0, src_w - crop_w)
    max_y = max(0, src_h - crop_h)
    x = int(max(0, min(max_x, cx * src_w - crop_w / 2)))
    y = int(max(0, min(max_y, cy * src_h - crop_h / 2)))

    return (
        f"crop={crop_w}:{crop_h}:{x}:{y},"
        f"scale={target_w}:{target_h}:flags=lanczos,setsar=1"
    )


def extract_clip(source_path, in_t, out_t, target_w, target_h, cx, cy, dst_path, fps=30):
    src_w, src_h = probe_dims(source_path)
    vf = crop_filter(src_w, src_h, target_w, target_h, cx, cy)
    run([
        "ffmpeg", "-y", "-ss", f"{in_t:.3f}", "-to", f"{out_t:.3f}",
        "-i", source_path,
        "-vf", f"{vf},fps={fps}",
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", str(dst_path),
    ])


def get_duration(path: str) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", str(path)])
    return float(out.stdout.strip())


def concat_with_xfade(clip_paths, crossfade, output_path):
    if len(clip_paths) == 1:
        run(["ffmpeg", "-y", "-i", str(clip_paths[0]), "-c", "copy", str(output_path)])
        return

    durations = [get_duration(str(p)) for p in clip_paths]
    inputs = []
    for p in clip_paths:
        inputs += ["-i", str(p)]

    filter_parts = []
    cum_duration = durations[0]
    last_label = "0:v"
    for i in range(1, len(clip_paths)):
        offset = max(0.0, cum_duration - crossfade)
        out_label = f"v{i}" if i < len(clip_paths) - 1 else "vout"
        filter_parts.append(
            f"[{last_label}][{i}:v]xfade=transition=fade:duration={crossfade}:"
            f"offset={offset:.3f}[{out_label}]"
        )
        cum_duration = cum_duration + durations[i] - crossfade
        last_label = out_label

    filter_complex = ";".join(filter_parts)
    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", filter_complex,
           "-map", "[vout]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
           "-pix_fmt", "yuv420p", str(output_path)]
    run(cmd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selection", required=True)
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--aspect", default=None, help="ex: 9:16, 16:9, 1:1, 4:5 (default: da selection.json)")
    ap.add_argument("--crossfade", type=float, default=0.25)
    ap.add_argument("--workdir", default=None)
    args = ap.parse_args()

    selection = json.loads(Path(args.selection).read_text(encoding="utf-8"))
    candidates = {c["segment_id"]: c for c in json.loads(Path(args.candidates).read_text(encoding="utf-8"))["candidates"]}

    aspect = args.aspect or selection.get("aspect", "9:16")
    if aspect not in ASPECT_RESOLUTIONS:
        raise SystemExit(f"Aspect '{aspect}' não suportado. Use um de: {list(ASPECT_RESOLUTIONS)}")
    target_w, target_h = ASPECT_RESOLUTIONS[aspect]

    workdir = Path(args.workdir) if args.workdir else Path(args.output).parent / "_render_work"
    workdir.mkdir(parents=True, exist_ok=True)

    clip_paths = []
    total = 0.0
    for i, seg in enumerate(selection["segments"]):
        cand = candidates.get(seg["segment_id"])
        if cand is None:
            raise SystemExit(f"segment_id '{seg['segment_id']}' não encontrado em candidates.json")
        in_t = seg.get("in", cand["start"])
        out_t = seg.get("out", cand["end"])
        dur = out_t - in_t
        total += dur
        clip_path = workdir / f"clip_{i:03d}.mp4"
        print(f"  [{i}] {cand['source_file']} {in_t:.2f}-{out_t:.2f}s ({dur:.2f}s) -> {clip_path.name}")
        extract_clip(cand["source_path"], in_t, out_t, target_w, target_h,
                     cand.get("crop_center_x", 0.5), cand.get("crop_center_y", 0.5),
                     clip_path)
        clip_paths.append(clip_path)

    print(f"[render] {len(clip_paths)} clipe(s), {total:.1f}s de material bruto selecionado "
          f"(saída final será um pouco menor devido ao crossfade)")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    concat_with_xfade(clip_paths, args.crossfade, args.output)

    final_dur = get_duration(args.output)
    target_duration = selection.get("target_duration")
    print(f"\n[render] OK -> {args.output}")
    print(f"[render] duração final: {final_dur:.2f}s"
          + (f" (alvo: {target_duration}s)" if target_duration else ""))


if __name__ == "__main__":
    main()
