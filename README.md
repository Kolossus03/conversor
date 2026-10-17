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

## Install

Download an installer from the [latest release](https://github.com/Kolossus03/conversor/releases/latest) and run it. Choose one of the two:

| Installer | Download | Installed | Choose it if |
|---|---|---|---|
| `Conversor-<version>-setup.exe` | about 190 MB | about 650 MB | you don't have an NVIDIA graphics card. The AI tools run on the processor. |
| `Conversor-<version>-setup-nvidia.exe` | about 1.3 GB | about 2.4 GB | you have an NVIDIA graphics card. The AI tools run about 10 times faster. |

The installer doesn't need administrator rights. It installs Conversor for your user only and adds it to the Start Menu. It can also add a desktop shortcut and an Explorer **Send to → Conversor** entry. ffmpeg is included, so audio and video work straight away.

To switch versions, run the other installer. It replaces the current install.

**"Windows protected your PC":** the installer isn't code-signed, so Windows SmartScreen may warn you the first time. Click **More info**, then **Run anyway**.

### Requirements

- Windows 10 or 11, 64-bit
- **Optional:**
  - Microsoft Office, for Word, Excel and PowerPoint files
  - for the NVIDIA installer, NVIDIA driver 580 or newer. Without it, the AI tools fall back to the processor.

### Uninstall

Open **Settings → Apps → Installed apps**, find Conversor and choose **Uninstall**. The uninstaller asks whether to also delete your settings and downloaded AI models; the default is No. Your converted files are never touched.

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
- No telemetry and no update checks. The only network access is a model download you approve.
- PDF passwords stay in memory and are never written to disk.

## Run from source

You need Python 3.14 and [uv](https://docs.astral.sh/uv/). Without the installer, ffmpeg must be on `PATH` for audio, video and HEIC.

```
git clone https://github.com/Kolossus03/conversor.git
cd conversor
uv sync
uv run conversor
```

`uv sync` downloads the exact library versions from `uv.lock` into a local `.venv` folder, about 3 GB with the NVIDIA libraries. It only does this once.

To add a Start Menu entry and an Explorer "Send to → Conversor" entry that point to the source version, run:

```
uv run python scripts/install_shortcuts.py --start-menu --send-to
```

To remove those shortcuts with your settings, cache and AI models, run `Uninstall Conversor.cmd`. It lists everything it will remove and asks before deleting. Then delete the folder.

### Tests

```
uv run pytest
```

### Build the installers

The build needs [Inno Setup](https://jrsoftware.org/isinfo.php) 6. Point the `ISCC` environment variable at `ISCC.exe` if it isn't the Scoop install.

```
uv run python scripts/build_installer.py
```

The script downloads a pinned ffmpeg build and checks its SHA-256. It freezes the app with PyInstaller (`packaging/conversor.spec`) and writes both installers to `dist/`. A build takes about 5 minutes.

## License

MIT. See [LICENSE](LICENSE). Third-party models and tools keep their own licenses, listed above. The installers bundle an unmodified [ffmpeg](https://ffmpeg.org/) build from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) ([source](https://github.com/GyanD/codexffmpeg/releases/tag/9.0.2)), licensed under the GPL v3. Its license is in the `ffmpeg` folder of the install. Microsoft Office is not bundled.
