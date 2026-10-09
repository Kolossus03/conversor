# Conversor

An offline file converter for Windows. Drop files in, pick what you want, and the result is saved next to the original. Nothing is uploaded anywhere.

![icon](src/conversor/qml/icon.png)

## What it does

| Drop in | Convert to | Tools |
|---|---|---|
| **Images:** PNG, JPG, WEBP, AVIF, HEIC, SVG, ICO, GIF, BMP, TIFF | Any of those, ICO with several sizes, PDF | Remove background (AI), Upscale (AI), Resize, Compress (or fit under a size), Remove metadata, Extract text (OCR), Combine into PDF |
| **PDF** | Word, PNG/JPG pages, Text | Merge (reorderable), Pick/remove pages, Split, Compress, Rotate, Add/Remove password, Read scanned text (OCR) |
| **Word, Excel, PowerPoint** (and ODF, RTF, TXT) | PDF, DOCX/XLSX/PPTX, ODT/ODS/ODP, CSV, TXT, slides as PNG | |
| **Video:** MP4, MKV, MOV, WEBM, AVI, WMV, FLV, TS | MP4, WEBM, MKV, MOV, GIF, MP3/WAV (sound only) | Trim, Compress (or fit under a size, e.g. 25 MB), Remove sound |
| **Audio:** MP3, WAV, FLAC, M4A, OGG, OPUS, AAC, WMA, AIFF | MP3, M4A, WAV, FLAC, OGG, OPUS | Trim, Normalize volume |
| **Data:** CSV, TSV, JSON, YAML | Excel, CSV, JSON, YAML, TSV | |

The window starts as a single drop zone. File types are detected from their content, only the outputs that make sense are offered, and settings stay in a collapsed "Options" panel.

## Requirements

- Windows 10 or 11 and Python 3.14
- **Optional:**
  - Microsoft Office, for Word, Excel and PowerPoint files
  - [ffmpeg](https://ffmpeg.org/) on `PATH`, for audio, video and HEIC
  - an NVIDIA GPU, which makes the AI tools much faster. Without one they run on the CPU.

## Install and run

First, get the code. Either clone it:

```
git clone https://github.com/Kolossus03/conversor.git
cd conversor
```

or download the ZIP from the green **Code** button on GitHub, extract it, and open a terminal in that folder.

Then install the libraries and start the app with [uv](https://docs.astral.sh/uv/):

```
uv sync
uv run conversor
```

`uv sync` downloads the exact library versions from `uv.lock` into a local `.venv` folder (about 2 GB, mostly NVIDIA GPU libraries). This happens only once.

Or with pip:

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install -e . --no-deps
.venv\Scripts\python -m conversor
```

**Optional shortcuts:** add a Start Menu entry and an Explorer "Send to → Conversor" entry with:

```
uv run python scripts/install_shortcuts.py --start-menu --send-to
```

**Uninstall:** run `Uninstall Conversor.cmd`. It lists what it will remove (shortcuts, settings, cache and AI models), asks before deleting anything, and never touches your converted files. Then delete the folder.

## AI models

Models download on first use, only after you confirm. Each one is pinned to a SHA-256 hash and verified before every load.

| Tool | Model | License |
|---|---|---|
| Remove background | [BiRefNet](https://github.com/ZhengPeng7/BiRefNet), ONNX exports from the [rembg](https://github.com/danielgatis/rembg) releases | MIT |
| Upscale | [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN), [ONNX export](https://huggingface.co/jonathanst29/tinier-upscale-models) | BSD-3-Clause |
| Extract text | [RapidOCR](https://github.com/RapidAI/RapidOCR) PP-OCR models, bundled with the package | Apache-2.0 |

## Security model

**Isolation**
- Every file is opened in a separate worker process inside a Windows Job Object. The worker has a memory cap, a limit on how many child processes it can start, and a kill-on-close flag. The UI process never parses user files; it only shows PNG previews the worker produced.
- **Office files:** Office runs as a private, hidden instance with macros forced off, and files open read-only. Hung Office processes are killed.
- **Media files:** ffmpeg is restricted to the `file` protocol and a forced demuxer. GPS and other metadata are removed from videos by default.

**Hostile input**
- File types are detected from magic bytes, not extensions.
- Decompression bombs are refused.
- SVGs can't reference other files.
- YAML is loaded safely, and spreadsheet formulas in data become plain text.

**Output safety**
- Output is written to a temporary file and then renamed atomically. Originals are never modified or overwritten.

**Network and privacy**
- No telemetry. The only network access is a model download you approve.
- PDF passwords stay in memory and are never written to disk.

## Development

```
uv run pytest
```

## License

MIT. See [LICENSE](LICENSE). Third-party models and tools keep their own licenses, listed above. ffmpeg and Microsoft Office are not bundled.
