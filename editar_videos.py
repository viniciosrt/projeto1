"""Transcreve os vídeos de produto com Whisper e corta as falas proibidas.

Remove trechos que mencionam "tiktok", "tiktok shop", "carrinho laranja" ou o
preço, e salva "<nome>_editado.mp4" ao lado de cada original. As transcrições
e o relatório ficam na subpasta "_transcricoes".

Uso (Windows):
    python editar_videos.py
    python editar_videos.py "C:\\Users\\voce\\Downloads\\videos_produtos" --modelo medium
    python editar_videos.py --simular      # só transcreve e mostra o que cortaria
"""

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

EXTENSOES = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}
SUFIXO = "_editado"

# Aplicados sobre o texto em minúsculas e sem acentos.
PADROES = {
    "tiktok": r"\bti[ck]\s*-?\s*to[ck]\w*(?:\s+shop\w*)?",
    "carrinho laranja": r"\bcarrinh\w*\s+(?:\w+\s+)?laranj\w*",
    "preco": (
        r"r\s?\$\s*\d"
        r"|\b\d+(?:[.,]\d+)?\s*(?:reais|real|conto|contos|pila)\b"
        r"|\b(?:reais|centavos)\b"
        r"|\bpor\s+(?:apenas|so|somente)\b"
        r"|\bprec(?:o|inho)\b"
        r"|\bcust(?:a|ando|ou)\b"
        r"|\bvalor\b"
    ),
}
REGEX = {nome: re.compile(p) for nome, p in PADROES.items()}


def normalizar(texto):
    sem_acento = unicodedata.normalize("NFD", texto)
    sem_acento = "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")
    return sem_acento.lower()


def motivos(texto):
    t = normalizar(texto)
    return [nome for nome, rx in REGEX.items() if rx.search(t)]


def trechos_proibidos(segmentos, modo):
    """Retorna [(inicio, fim, motivo, texto)] a remover."""
    cortes = []
    for seg in segmentos:
        if modo == "frase":
            m = motivos(seg["text"])
            if m:
                cortes.append((seg["start"], seg["end"], ",".join(m), seg["text"].strip()))
            continue

        # modo palavra: remove só as palavras que casam com os padrões
        palavras = seg.get("words") or []
        if not palavras:
            continue
        partes, offsets, pos = [], [], 0
        for p in palavras:
            n = normalizar(p["word"].strip())
            offsets.append((pos, pos + len(n)))
            partes.append(n)
            pos += len(n) + 1
        texto = " ".join(partes)
        for nome, rx in REGEX.items():
            for achado in rx.finditer(texto):
                idx = [i for i, (a, b) in enumerate(offsets) if a < achado.end() and b > achado.start()]
                if idx:
                    ini, fim = palavras[idx[0]]["start"], palavras[idx[-1]]["end"]
                    trecho = "".join(palavras[i]["word"] for i in idx).strip()
                    cortes.append((ini, fim, nome, trecho))
    return cortes


def trechos_mantidos(cortes, duracao, margem, minimo=0.05):
    """Complemento dos cortes (com margem), mesclando sobreposições."""
    intervalos = sorted((max(0.0, a - margem), min(duracao, b + margem)) for a, b, *_ in cortes)
    mesclados = []
    for a, b in intervalos:
        if mesclados and a <= mesclados[-1][1]:
            mesclados[-1][1] = max(mesclados[-1][1], b)
        else:
            mesclados.append([a, b])
    manter, cursor = [], 0.0
    for a, b in mesclados:
        if a - cursor > minimo:
            manter.append((cursor, a))
        cursor = b
    if duracao - cursor > minimo:
        manter.append((cursor, duracao))
    return manter


def achar_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        sys.exit("ffmpeg não encontrado. Instale com: winget install Gyan.FFmpeg")


def info_video(ffmpeg, arquivo):
    """(duração em segundos, tem_audio) lidos da saída do ffmpeg -i."""
    saida = subprocess.run([ffmpeg, "-hide_banner", "-i", str(arquivo)],
                           capture_output=True, text=True, errors="replace").stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", saida)
    if not m:
        raise RuntimeError(f"não consegui ler a duração de {arquivo.name}")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s), "Audio:" in saida


def cortar(ffmpeg, origem, destino, manter):
    filtros, rotulos = [], ""
    for i, (a, b) in enumerate(manter):
        filtros.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}]")
        filtros.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{i}]")
        rotulos += f"[v{i}][a{i}]"
    filtros.append(f"{rotulos}concat=n={len(manter)}:v=1:a=1[v][a]")
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(origem),
           "-filter_complex", ";".join(filtros), "-map", "[v]", "-map", "[a]",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(destino)]
    subprocess.run(cmd, check=True)


def main():
    padrao = Path.home() / "Downloads" / "videos_produtos"
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pasta", nargs="?", default=str(padrao))
    ap.add_argument("--modelo", default="medium", help="tiny, base, small, medium, large-v3 (padrão: medium)")
    ap.add_argument("--modo", choices=["frase", "palavra"], default="frase",
                    help="frase: corta a fala inteira que menciona o termo (padrão); palavra: só as palavras")
    ap.add_argument("--margem", type=float, default=0.12, help="segundos extras em volta de cada corte")
    ap.add_argument("--simular", action="store_true", help="não gera vídeos, só relatório")
    ap.add_argument("--refazer", action="store_true", help="reprocessa vídeos que já têm _editado")
    args = ap.parse_args()

    pasta = Path(args.pasta)
    videos = sorted(p for p in pasta.iterdir()
                    if p.suffix.lower() in EXTENSOES and not p.stem.endswith(SUFIXO))
    if not videos:
        sys.exit(f"Nenhum vídeo em {pasta}")
    print(f"{len(videos)} vídeos em {pasta}")

    ffmpeg = achar_ffmpeg()
    pasta_transc = pasta / "_transcricoes"
    pasta_transc.mkdir(exist_ok=True)

    import whisper  # importado aqui para --help funcionar sem o pacote
    print(f"Carregando Whisper '{args.modelo}'...")
    modelo = whisper.load_model(args.modelo)

    linhas = []
    for n, video in enumerate(videos, 1):
        destino = video.with_name(f"{video.stem}{SUFIXO}.mp4")
        print(f"[{n}/{len(videos)}] {video.name}")
        if destino.exists() and not args.refazer and not args.simular:
            print("   já editado, pulando (use --refazer)")
            continue
        try:
            duracao, tem_audio = info_video(ffmpeg, video)
            if not tem_audio:
                print("   sem áudio, nada a cortar")
                linhas.append([video.name, "sem audio", "", "", ""])
                continue

            json_path = pasta_transc / f"{video.stem}.json"
            if json_path.exists():
                resultado = json.loads(json_path.read_text(encoding="utf-8"))
            else:
                resultado = modelo.transcribe(str(video), language="pt", word_timestamps=True,
                                              condition_on_previous_text=False)
                json_path.write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
                (pasta_transc / f"{video.stem}.txt").write_text(
                    "\n".join(f"[{s['start']:6.2f}-{s['end']:6.2f}] {s['text'].strip()}"
                              for s in resultado["segments"]), encoding="utf-8")

            cortes = trechos_proibidos(resultado["segments"], args.modo)
            for a, b, motivo, texto in cortes:
                print(f"   corta {a:6.2f}-{b:6.2f} [{motivo}] {texto}")
            manter = trechos_mantidos(cortes, duracao, args.margem)
            final = sum(b - a for a, b in manter)
            removidos = " | ".join(f"{a:.2f}-{b:.2f} [{m}] {t}" for a, b, m, t in cortes)

            if not cortes:
                status = "sem cortes (copiado)"
                if not args.simular:
                    shutil.copy2(video, destino)
            elif final < 1.0:
                status = "ATENCAO: sobraria menos de 1s, não editado"
            else:
                status = "editado"
                if not args.simular:
                    cortar(ffmpeg, video, destino, manter)
            if args.simular:
                status = "simulado: " + status
            print(f"   {status} ({duracao:.1f}s -> {final:.1f}s)")
            linhas.append([video.name, status, f"{duracao:.1f}", f"{final:.1f}", removidos])
        except Exception as erro:  # segue para o próximo vídeo
            print(f"   ERRO: {erro}")
            linhas.append([video.name, f"ERRO: {erro}", "", "", ""])

    relatorio = pasta_transc / "relatorio_edicao.csv"
    with open(relatorio, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["arquivo", "status", "duracao_original_s", "duracao_final_s", "trechos_removidos"])
        w.writerows(linhas)
    print(f"\nRelatório: {relatorio}")
    print("Revise os trechos marcados em 'preco' — o padrão é amplo de propósito.")


if __name__ == "__main__":
    main()
