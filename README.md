# Edição dos vídeos de produto

`editar_videos.py` transcreve com Whisper cada vídeo de `Downloads\videos_produtos\`, remove as falas que citam
**tiktok / tiktok shop**, **carrinho laranja** ou **preço**, e salva `<nome>_editado.mp4` ao lado do original.

## Instalação (Windows, uma vez)

```powershell
winget install Gyan.FFmpeg          # feche e reabra o terminal depois
pip install -r requirements.txt     # para usar GPU NVIDIA, instale antes o torch com CUDA (pytorch.org)
```

## Uso

```powershell
python editar_videos.py --simular   # transcreve e só lista o que seria cortado
python editar_videos.py             # gera os *_editado.mp4
```

Opções:
- `--modo frase` (padrão) corta a fala inteira que menciona o termo, e o corte fica mais natural. `--modo palavra` corta só as palavras.
- `--modelo small|medium|large-v3` troca o modelo. `medium` é o padrão. O `large-v3` erra menos, mas é mais lento.
- `--margem 0.12` são os segundos extras em volta de cada corte.
- `--refazer` reprocessa vídeos que já foram editados.

As transcrições ficam em cache em `_transcricoes\`, então rodar de novo não transcreve outra vez. A mesma pasta guarda
`relatorio_edicao.csv` (abre no Excel), com os trechos removidos de cada vídeo. O padrão de "preço" é amplo de
propósito (reais, R$, "por apenas", "custa", "valor"...), então revise o relatório.
