#!/usr/bin/env python3
"""
analyze.py — Analisa uma pasta de takes de vídeo (sem áudio), detecta sub-cenas,
pontua cada segmento por qualidade visual (nitidez, movimento relevante, estabilidade,
exposição) e gera:
  - candidates.json  (todos os segmentos candidatos, com scores e metadados)
  - contact_sheet.jpg (grade visual com thumbnail + score de cada candidato)
  - thumbs/*.jpg      (thumbnail individual de cada candidato)

Uso:
  python3 analyze.py --folder /caminho/dos/takes --outdir /caminho/de/trabalho \
                      [--min-scene-dur 0.8] [--max-candidates 60] [--sample-fps 4]

Dependências: opencv-python-headless, numpy, ffmpeg (binário no PATH)
"""
import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm", ".mts", ".m2ts"}


def find_videos(folder: Path):
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in VIDEO_EXTS)
    if not files:
        raise SystemExit(f"Nenhum arquivo de vídeo encontrado em {folder}")
    return files


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def detect_scene_cuts(path: Path, sample_fps: float, hist_threshold: float = 0.45):
    """Detecção de corte de cena por correlação de histograma entre frames amostrados.
    Retorna lista de timestamps (segundos) onde ocorre um corte."""
    cap = cv2.VideoCapture(str(path))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(src_fps / sample_fps))

    cuts = []
    prev_hist = None
    frame_idx = 0
    t = 0.0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % step == 0:
            small = cv2.resize(frame, (160, 90))
            hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
            hist = cv2.calcHist([hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
            cv2.normalize(hist, hist)
            if prev_hist is not None:
                corr = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
                # baixa correlação = mudança forte de conteúdo = corte de cena
                if corr < hist_threshold:
                    cuts.append(frame_idx / src_fps)
            prev_hist = hist
        frame_idx += 1
    cap.release()
    return cuts, src_fps


def build_segments(duration: float, cuts: list, min_scene_dur: float):
    bounds = [0.0] + sorted(cuts) + [duration]
    segments = []
    start = bounds[0]
    for b in bounds[1:]:
        if b - start >= min_scene_dur:
            segments.append((start, b))
            start = b
        # senão, funde com o próximo (corte espúrio / cena curta demais)
    if not segments:
        segments = [(0.0, duration)]
    elif segments[-1][1] < duration:
        segments[-1] = (segments[-1][0], duration)
    return segments


def score_segment(path: Path, t0: float, t1: float, src_fps: float, n_samples: int = 6):
    """Amostra frames dentro do segmento e calcula métricas de qualidade visual."""
    cap = cv2.VideoCapture(str(path))
    dur = t1 - t0
    sample_times = [t0 + dur * (i + 0.5) / n_samples for i in range(n_samples)]

    sharpness_vals, luma_means, luma_stds = [], [], []
    frames_gray = []
    motion_centroids = []
    for ts in sample_times:
        cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000)
        ret, frame = cap.read()
        if not ret:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small_gray = cv2.resize(gray, (320, 180))
        sharpness_vals.append(cv2.Laplacian(small_gray, cv2.CV_64F).var())
        luma_means.append(float(small_gray.mean()))
        luma_stds.append(float(small_gray.std()))
        frames_gray.append(small_gray)

    motion_vals = []
    for i in range(1, len(frames_gray)):
        flow = cv2.calcOpticalFlowFarneback(
            frames_gray[i - 1], frames_gray[i], None,
            0.5, 3, 15, 3, 5, 1.2, 0,
        )
        mag, ang = cv2.cartToPolar(flow[..., 0], flow[..., 1])
        motion_vals.append(float(mag.mean()))
        # centróide do movimento (para crop inteligente depois)
        if mag.max() > 1e-3:
            ys, xs = np.mgrid[0:mag.shape[0], 0:mag.shape[1]]
            w = mag / (mag.sum() + 1e-6)
            cx = float((xs * w).sum() / mag.shape[1])  # 0..1
            cy = float((ys * w).sum() / mag.shape[0])  # 0..1
            motion_centroids.append((cx, cy))

    # jitter/tremor: variação frame-a-frame da diferença média (proxy grosseiro de shake)
    frame_diffs = [
        float(np.abs(frames_gray[i].astype(np.int16) - frames_gray[i - 1].astype(np.int16)).mean())
        for i in range(1, len(frames_gray))
    ] or [0.0]

    cap.release()

    sharpness = float(np.mean(sharpness_vals)) if sharpness_vals else 0.0
    motion = float(np.mean(motion_vals)) if motion_vals else 0.0
    jitter = float(np.std(frame_diffs)) if len(frame_diffs) > 1 else 0.0
    luma_mean = float(np.mean(luma_means)) if luma_means else 128.0
    luma_std = float(np.mean(luma_stds)) if luma_stds else 0.0

    # penaliza exposição ruim: muito escuro/claro ou sem contraste (imagem "chapada")
    exposure_penalty = 0.0
    if luma_mean < 35 or luma_mean > 220:
        exposure_penalty += 25.0
    if luma_std < 15:
        exposure_penalty += 15.0

    if motion_centroids:
        cx = float(np.mean([c[0] for c in motion_centroids]))
        cy = float(np.mean([c[1] for c in motion_centroids]))
    else:
        cx, cy = 0.5, 0.5

    return {
        "sharpness_raw": round(sharpness, 2),
        "motion_raw": round(motion, 4),
        "jitter_raw": round(jitter, 3),
        "luma_mean": round(luma_mean, 1),
        "luma_std": round(luma_std, 1),
        "exposure_penalty": exposure_penalty,
        "crop_center_x": round(cx, 3),
        "crop_center_y": round(cy, 3),
    }


def normalize_and_score(raw_list):
    """Normaliza métricas cross-candidato (0-100) e calcula score composto."""
    def norm(values):
        lo, hi = min(values), max(values)
        if hi - lo < 1e-6:
            return [50.0 for _ in values]
        return [100.0 * (v - lo) / (hi - lo) for v in values]

    sharp_n = norm([r["sharpness_raw"] for r in raw_list])
    motion_n = norm([r["motion_raw"] for r in raw_list])
    jitter_n = norm([r["jitter_raw"] for r in raw_list])  # maior = mais tremido (penaliza)

    for i, r in enumerate(raw_list):
        # pesos: nitidez importa mais, movimento relevante soma, tremor e exposição ruim penalizam
        composite = (
            0.40 * sharp_n[i]
            + 0.35 * motion_n[i]
            - 0.20 * jitter_n[i]
            - r["exposure_penalty"]
        )
        r["score"] = round(max(0.0, min(100.0, composite)), 1)
    return raw_list


def make_thumbnail(path: Path, t: float, out_path: Path, width: int = 320):
    cap = cv2.VideoCapture(str(path))
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return False
    h, w = frame.shape[:2]
    new_h = int(width * h / w)
    frame = cv2.resize(frame, (width, new_h))
    cv2.imwrite(str(out_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return True


def build_contact_sheet(candidates, thumbs_dir: Path, out_path: Path, cols: int = 5):
    thumb_w, thumb_h = 320, 180
    label_h = 46
    rows = math.ceil(len(candidates) / cols)
    sheet = np.full((rows * (thumb_h + label_h), cols * thumb_w, 3), 30, dtype=np.uint8)

    for idx, c in enumerate(candidates):
        r, col = divmod(idx, cols)
        thumb_path = thumbs_dir / f"{c['segment_id']}.jpg"
        img = cv2.imread(str(thumb_path))
        if img is None:
            continue
        img = cv2.resize(img, (thumb_w, thumb_h))
        y0 = r * (thumb_h + label_h)
        x0 = col * thumb_w
        sheet[y0:y0 + thumb_h, x0:x0 + thumb_w] = img
        label1 = f"{c['segment_id']}  score={c['score']:.0f}"
        label2 = f"{c['source_file']} [{c['start']:.1f}-{c['end']:.1f}s]"
        cv2.putText(sheet, label1, (x0 + 4, y0 + thumb_h + 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(sheet, label2, (x0 + 4, y0 + thumb_h + 36),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 180, 180), 1, cv2.LINE_AA)
    cv2.imwrite(str(out_path), sheet, [cv2.IMWRITE_JPEG_QUALITY, 90])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--min-scene-dur", type=float, default=0.8)
    ap.add_argument("--max-candidates", type=int, default=60)
    ap.add_argument("--sample-fps", type=float, default=4.0)
    args = ap.parse_args()

    folder = Path(args.folder).expanduser().resolve()
    outdir = Path(args.outdir).expanduser().resolve()
    thumbs_dir = outdir / "thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    videos = find_videos(folder)
    print(f"[analyze] {len(videos)} arquivo(s) de vídeo encontrados em {folder}")

    all_candidates = []
    for video in videos:
        try:
            duration = ffprobe_duration(video)
        except Exception as e:
            print(f"  ! ignorando {video.name}: ffprobe falhou ({e})")
            continue
        cuts, src_fps = detect_scene_cuts(video, args.sample_fps)
        segments = build_segments(duration, cuts, args.min_scene_dur)
        print(f"  - {video.name}: {duration:.1f}s -> {len(segments)} segmento(s)")

        for si, (t0, t1) in enumerate(segments):
            metrics = score_segment(video, t0, t1, src_fps)
            seg_id = f"{video.stem}_{si:03d}"
            cand = {
                "segment_id": seg_id,
                "source_file": video.name,
                "source_path": str(video),
                "start": round(t0, 2),
                "end": round(t1, 2),
                "duration": round(t1 - t0, 2),
                **metrics,
            }
            all_candidates.append(cand)

    if not all_candidates:
        raise SystemExit("Nenhum candidato gerado.")

    all_candidates = normalize_and_score(all_candidates)
    all_candidates.sort(key=lambda c: c["score"], reverse=True)

    if len(all_candidates) > args.max_candidates:
        print(f"[analyze] limitando a {args.max_candidates} melhores candidatos "
              f"(de {len(all_candidates)})")
        all_candidates = all_candidates[: args.max_candidates]

    for c in all_candidates:
        mid = (c["start"] + c["end"]) / 2
        make_thumbnail(Path(c["source_path"]), mid, thumbs_dir / f"{c['segment_id']}.jpg")

    contact_sheet_path = outdir / "contact_sheet.jpg"
    build_contact_sheet(all_candidates, thumbs_dir, contact_sheet_path)

    candidates_path = outdir / "candidates.json"
    with open(candidates_path, "w", encoding="utf-8") as f:
        json.dump({"candidates": all_candidates}, f, ensure_ascii=False, indent=2)

    total_available = sum(c["duration"] for c in all_candidates)
    print(f"\n[analyze] OK — {len(all_candidates)} candidatos, "
          f"{total_available:.1f}s de material disponível no total")
    print(f"[analyze] candidates.json -> {candidates_path}")
    print(f"[analyze] contact_sheet.jpg -> {contact_sheet_path}")


if __name__ == "__main__":
    main()
