```
# combine‑wav‑from‑output
Combine sorted tts audio shards(wav/mp3) and standalone MP3 ID3 metadata editor custom nodes for ComfyUI.
> 
> [!NOTE]
> This projected was created with a [cookiecutter](https://github.com/ltdrdata/cookiecutter-comfy-extension) template. It helps you start writing custom nodes without worrying about the Python setup.
## Quickstart
1. Install [ComfyUI](https://docs.comfy.org/get_started).
2. Install [ComfyUI‑Manager](https://github.com/ltdrdata/ComfyUI%E2%80%91Manager)
3. Look up this extension in ComfyUI‑Manager. If you are installing manually, clone this repository under `ComfyUI/custom_nodes`.
4. Install extra python dependencies:
```

pip install pydub mutagen torchaudio

```
> 
> `pydub` for audio concatenation; `mutagen` for MP3 ID3 tag read/write; `torchaudio` for in‑memory audio tensor processing.
1. Restart ComfyUI.

# Features
### 1. TTS分片音频合并 `TTS分片音频合并(自定义前缀+MP3‑ID3)`
Combine numbered audio shards in a directory (pattern: `<prefix>_000.wav`, `<prefix>_001.wav` …) in ascending numeric order.
- Input support: source shard `wav` / `mp3`
- Output format: export to `wav` or `mp3`
- MP3 export enhancements:
  - Configurable CBR bitrate (128k/192k/256k/320k, minimum 256k for Tencent Music requirement)
  - Force stereo channel conversion
  - Resample audio sample rate to 44100 Hz (required for high‑bitrate mp3 from 24kHz TTS source)
  - Write MP3 ID3 metadata tags on export: Title, Artist, Album, Year, embedded multiline Chinese lyric(USLT), cover image from ComfyUI IMAGE tensor
- Optional auto‑delete source shard files after successful merge
- Output merged audio file to **parent folder of shard directory**, not inside shard directory
- Trigger input port for workflow timing synchronization

**Main parameters**
| Parameter | Description |
| --- | --- |
| audio_dir | Absolute path of directory storing numbered audio shards |
| file_prefix | Filename prefix of split audio pieces, default `tts` |
| in_suffix | File extension of source shards: `wav` or `mp3` |
| out_format | Target output format: `wav` / `mp3` |
| delete_source | Whether delete original shard files after merge |
| trigger | Timing trigger port, only for workflow ordering |
| mp3_bitrate | MP3 CBR bitrate, only works when out_format=mp3 |
| force_stereo | Force output audio to stereo 2‑channel |
| resample_to_44100 | Resample audio sample rate to 44100 Hz |
| title | MP3 ID3 title(TIT2), ignored for wav output |
| lyric_text | Multiline lyric text for MP3 embedded USLT tag |
| cover_image | ComfyUI IMAGE tensor for mp3 album cover |
| artist / album / year | MP3 ID3 artist, album, year metadata fields |

**Outputs**
- `output_audio_path`: absolute file path for merged audio
- `output_parent_dir`: parent directory path of merged output file

---
### 2. MP3 Editor ID3 Tag｜MP3标签编辑器 (`Mp3EditID3Tags`)
Standalone node for editing ID3 metadata tags of **existing MP3 file on disk**.
> 
> ⚠️ This node modifies your original mp3 file **in‑place**, no new copy will be generated. Back‑up important mp3 files before usage.
- Does **not re‑encode audio stream**, only manipulate metadata tags, very fast execution
- Behaviour rule: **empty input string / unconnected image port → preserve original tag value inside mp3; only non‑empty input overwrites corresponding tag**
- Supported ID3 fields: Title(TIT2), Artist(TPE1), Album(TALB), Year(TYER), multiline Chinese lyric(USLT‑zho), album cover from ComfyUI IMAGE tensor
- Timing trigger port for workflow synchronization
- Returns status log text for debugging

**Main parameters**
| Parameter | Description |
| --- | --- |
| mp3_file_path | Absolute path to target existing mp3 file to modify |
| trigger | Timing trigger port for workflow ordering |
| title | MP3 title; leave empty to keep original tag |
| artist | MP3 artist; leave empty to keep original tag |
| album | MP3 album; leave empty to keep original tag |
| year | MP3 year; leave empty to keep original tag |
| lyric_text | Multiline lyric text, empty keeps original embedded lyric |
| cover_image | IMAGE tensor for new album cover; disconnect port to keep original cover |

**Outputs**
- `output_mp3_path`: absolute path of processed mp3 (same as input path, in‑place edited)
- `status_message`: human readable processing log string

---
### 3. Audio 流处理器｜重采样/立体声/增益/淡入淡出 (`AudioStreamProcessor`)
In‑memory ComfyUI AUDIO tensor processing node. **Works purely on audio tensor data, no disk read/write**. Designed to be placed before native `SaveAudio` node.

> ⚠️ This node only manipulates waveform tensor.
> Bitrate, file format, ID3 metadata are **export‑time parameters**, configure those in downstream `SaveAudio`.

Features:
‑ Resample audio to target sample rate(22050/44100/48000). Skip resampling if source sample rate matches target.
‑ Force‑stereo: duplicate mono channel to stereo, satisfies music‑platform upload validation.
‑ Adjustable overall audio gain (‑20 ~ +6 dB), with amplitude clipping to prevent audio clipping.
‑ Fade‑in / fade‑out effect for eliminating click noise at audio start/end.

**Main parameters**
| Parameter | Description |
| --- | --- |
| audio | Standard ComfyUI AUDIO input dict: `{waveform:tensor, sample_rate:int}` |
| target_sample_rate | Target sample‑rate, recommend 44100 for music‑platform submission |
| force_stereo | Convert mono audio to stereo by channel duplication, no‑op if already stereo |
| gain_db | Overall volume gain in dB; 0 = no change, avoid values >+3dB to prevent clipping |
| fade_in_sec | Fade‑in duration in seconds, `0` disables fade‑in |
| fade_out_sec | Fade‑out duration in seconds, `0` disables fade‑out |

**Outputs**
‑ `audio`: Processed ComfyUI standard AUDIO tensor, directly connect to `SaveAudio`.

**Typical workflow chain**
```

TTS‑Node(AUDIO‑24000 mono) → AudioStreamProcessor(target=44100, force_stereo=True) → SaveAudio(format=mp3, bitrate=320k)

```

## Develop
To install the dev dependencies and pre‑commit (will run the ruff hook), do:
```

git clone [https://github.com/feishengfei/comfyui-combine-wav-from-output](https://github.com/feishengfei/comfyui-combine-wav-from-output)
cd comfyui-combine-wav-from-output
pip install -e .
pre-commit install

```

```

### 修改要点汇总

1. Quickstart依赖增加 `torchaudio`；
2. 新增第3大章节：`AudioStreamProcessor`完整说明，包含功能、注意事项、参数表格、典型工作流链路；
3. 明确边界：本节点**只处理内存张量，比特率/格式/ID3交给下游SaveAudio**；
4. 保持原有两个节点文档完全不变。
