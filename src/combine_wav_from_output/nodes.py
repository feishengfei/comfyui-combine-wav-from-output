import os
import re
import io
import numpy as np
from pathlib import Path
from inspect import cleandoc
from PIL import Image
from pydub import AudioSegment
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TPE1, TALB, TYER, USLT, TIT2


class CombineTtsAudio:
    """
    将目录下 <prefix>_000.wav / <prefix>_001.wav 按数字序号升序合并音频
    audio_dir：分片音频存放目录；
    file_prefix：分片文件前缀，默认 tts
    in_suffix：原始分片文件后缀 wav / mp3
    out_format：合并输出格式 wav / mp3
    mp3_bitrate：mp3输出恒定码率，仅mp3生效；腾讯音乐专栏最低要求256k
    force_stereo：开启则强制转为双声道，单声道音频会复制填充左右声道；默认关闭
    resample_to_44100：开启将音频重采样到44100Hz；24000Hz源想要真正达到256k/320k mp3必须开启
    delete_source：合并完成后是否删除原始分片文件
    title：【可选】单曲名称，mp3写入ID3 TIT2标题标签
    lyric_text：【可选】歌词多行字符串；仅mp3生效，写入ID3 USLT内嵌歌词
    cover_image: 【可选】ComfyUI IMAGE张量，用作mp3专辑封面，仅mp3生效
    artist: ID3艺术家标签(mp3 only)
    album: ID3专辑标签(mp3 only)
    year: ID3年份标签(mp3 only)
    trigger：时序触发端口，连接上游输出，保证磁盘文件全部写完再执行合并
    输出：
        output_audio_path：合成后音频完整磁盘路径
        output_parent_dir：合成音频文件所在父目录路径
    示例：输入目录 /a/b/02丁香结，输出文件 /a/b/02丁香结.mp3（输出到目录的父级，不放进分片目录内部）
    """
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "audio_dir": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "分片音频所在目录，填写绝对路径"
                }),
                "file_prefix": ("STRING", {
                    "default": "tts",
                    "tooltip": "零散分片文件前缀，例如 tts，则匹配 tts_000.wav、tts_001.wav"
                }),
                "in_suffix": (["wav", "mp3"], {"default": "wav", "tooltip": "待合并分片文件的后缀"}),
                "out_format": (["wav", "mp3"], {"default": "wav", "tooltip": "合并输出音频格式"}),
                "delete_source": ("BOOLEAN", {"default": False, "tooltip": "合并完成后删除 <prefix>_000.* 等分片源文件"}),
                "trigger": ("*", {"tooltip": "时序触发端口，连接上游输出，仅用于等待全部文件保存到磁盘，不读取数据"})
            },
            "optional": {
                "mp3_bitrate": (["128k","192k","256k","320k"], {"default":"256k", "tooltip":"仅out_format=mp3生效；腾讯音乐专栏最低要求256k，CBR恒定码率；24k源需要打开resample_to_44100才能达到高码率"}),
                "force_stereo": ("BOOLEAN", {"default": False, "tooltip":"强制转为双声道；单声道音频会复制内容填充左右声道，腾讯音乐专栏需要立体声，默认关闭"}),
                "resample_to_44100": ("BOOLEAN", {"default": False, "tooltip":"重采样到44100Hz；24kHz的TTS源，想要真正输出256k/320k mp3必须开启此选项"}),
                "title": ("STRING", {
                    "default": "",
                    "tooltip": "单曲名称，mp3模式写入ID3标题(TIT2)标签；wav忽略"
                }),
                "lyric_text": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "歌词文本，多行；输出mp3时写入ID3 USLT内嵌歌词；wav格式忽略此字段"
                }),
                "cover_image": ("IMAGE", {"tooltip": "mp3专辑封面图片，接Load Image输出；仅out_format=mp3时生效"}),
                "artist": ("STRING", {"default": "artist", "tooltip": "ID3 artist 艺术家标签(mp3 only)"}),
                "album": ("STRING", {"default": "album", "tooltip": "ID3 album 专辑标签(mp3 only)"}),
                "year": ("STRING", {"default": "year", "tooltip": "ID3 year 年份标签(mp3 only)"}),
            }
        }
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("output_audio_path", "output_parent_dir")
    FUNCTION = "run"
    CATEGORY = "AudioTools"
    OUTPUT_NODE = True
    DESCRIPTION = cleandoc(__doc__)

    async def run(self,
                  audio_dir: str,
                  file_prefix: str,
                  in_suffix: str,
                  out_format: str,
                  delete_source: bool,
                  trigger,
                  mp3_bitrate="256k",
                  force_stereo=False,
                  resample_to_44100=False,
                  title="",
                  lyric_text="",
                  cover_image=None,
                  artist="artist",
                  album="album",
                  year="year"):
        target_dir = Path(audio_dir).absolute()
        if not target_dir.is_dir():
            raise NotADirectoryError(f"音频目录不存在：{target_dir}")

        dir_name = target_dir.name
        parent_dir = target_dir.parent
        output_file = parent_dir / f"{dir_name}.{out_format}"

        escaped_prefix = re.escape(file_prefix)
        pattern = re.compile(rf"^{escaped_prefix}_(\d+)\.{re.escape(in_suffix)}$", re.IGNORECASE)
        matched = []
        for fname in os.listdir(target_dir):
            m = pattern.match(fname)
            if m:
                seq = int(m.group(1))
                matched.append((seq, fname))

        if len(matched) == 0:
            raise FileNotFoundError(
                f"目录内未找到匹配 {file_prefix}_xxx.{in_suffix} 的分片音频文件；目录：{target_dir}"
            )

        matched.sort(key=lambda x: x[0])
        sorted_files = [target_dir / fn for _, fn in matched]
        print(f"\n===== CombineTtsAudio: 找到 {len(sorted_files)} 个分片音频，前缀=[{file_prefix}] =====")
        for f in sorted_files:
            print(f"  > {f.name}")

        # -------- 合并音频 --------
        combined = AudioSegment.empty()
        for file_path in sorted_files:
            seg = AudioSegment.from_file(file_path, format=in_suffix)
            combined += seg

        # 强制转为立体声：单声道复制填充左右声道
        if force_stereo:
            print(f"ℹ️ force_stereo已开启，将音频强制转换为双声道(stereo)")
            combined = combined.set_channels(2)

        # 重采样到44100Hz，解决24k采样率mp3无法输出256k/320k码率的限制
        if resample_to_44100:
            old_rate = combined.frame_rate
            combined = combined.set_frame_rate(44100)
            print(f"ℹ️ resample_to_44100已开启，采样率 {old_rate} Hz → 44100 Hz")

        # 根据输出格式设置码率
        if out_format == "mp3":
            combined.export(output_file, format="mp3", bitrate=mp3_bitrate)
            print(f"✅ 合并完成，输出文件: {output_file} | mp3 CBR bitrate={mp3_bitrate} | force_stereo={force_stereo} | resample_to_44100={resample_to_44100}")
        else:
            combined.export(output_file, format=out_format)
            print(f"✅ 合并完成，输出文件: {output_file} | force_stereo={force_stereo} | resample_to_44100={resample_to_44100}")

        print(f"ℹ️ 输出音频父目录: {parent_dir}")

        # -------- MP3 ID3标签处理：仅输出为mp3时执行 --------
        if out_format == "mp3":
            print(f"ℹ️ 开始写入MP3 ID3元数据标签")
            audio_mp3 = MP3(output_file)
            # 初始化ID3，不存在则新建
            if not audio_mp3.tags:
                audio_mp3.tags = ID3()
            tags = audio_mp3.tags

            # 单曲标题 TIT2
            if title.strip():
                tags["TIT2"] = TIT2(encoding=3, text=title)
                print(f"ℹ️ MP3标题标签(title): {title}")

            # 写入 artist / album / year
            tags["TPE1"] = TPE1(encoding=3, text=artist)
            tags["TALB"] = TALB(encoding=3, text=album)
            tags["TYER"] = TYER(encoding=3, text=year)

            # 写入内嵌歌词 USLT，非同步歌词，语言代码zh
            if lyric_text.strip():
                tags["USLT"] = USLT(
                    encoding=3,
                    lang="zho",
                    desc="",
                    text=lyric_text
                )
                print(f"ℹ️ MP3已写入ID3内嵌歌词，字符数：{len(lyric_text)}")

            # 处理专辑封面 cover_image: IMAGE tensor [B,H,W,C] float 0~1
            if cover_image is not None:
                # 取batch第0张图
                img_np = (cover_image[0].cpu().numpy() * 255).astype(np.uint8)
                pil_img = Image.fromarray(img_np)
                buf = io.BytesIO()
                pil_img.save(buf, format="PNG")
                pic_bytes = buf.getvalue()
                # APIC 添加封面图片
                tags.add(APIC(
                    encoding=3,
                    mime="image/png",
                    type=3,  # 3=专辑封面
                    desc="Cover",
                    data=pic_bytes
                ))
                print(f"ℹ️ MP3已嵌入专辑封面图片")

            tags.save(output_file)
            print(f"✅ MP3 ID3标签写入完成(title:{title}, artist:{artist}, album:{album}, year:{year})")

        if delete_source:
            print(f"🗑️ 开启删除源分片，开始清理分片文件……")
            for f in sorted_files:
                try:
                    os.unlink(f)
                    print(f"    deleted: {f.name}")
                except Exception as e:
                    print(f"⚠️ 删除失败 {f.name}: {str(e)}")

        print(f"===== CombineTtsAudio: 全部处理结束 =====\n")
        return (str(output_file), str(parent_dir))

class Mp3EditID3Tags:
    """
    MP3 ID3标签编辑器【独立节点】
    原地修改磁盘上已存在的mp3文件元信息，不重新编码音频流，速度快
    规则：输入为空字符串 / None，则保留文件原有标签，不会清空；只有传入非有效值才覆盖对应字段
    mp3_file_path：待修改mp3绝对磁盘路径
    trigger：时序触发端口，用于控制执行时机
    title：单曲标题(TIT2)，空字符串=保留原值
    lyric_text：多行非同步歌词 USLT(zho中文)，空字符串=保留原值
    cover_image：ComfyUI IMAGE张量专辑封面；None=不修改原有封面
    artist：艺术家 TPE1，空字符串=保留原值
    album：专辑 TALB，空字符串=保留原值
    year：年份 TYER，空字符串=保留原值

    输出：
        output_mp3_path：处理完成mp3文件路径（原地修改，和输入路径一致）
        status_message：处理状态文本日志
    """
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "mp3_file_path": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "待编辑MP3文件的绝对磁盘路径"
                }),
                "trigger": ("*", {"tooltip": "时序触发端口，仅用于工作流等待，不读取数据"})
            },
            "optional": {
                "title": ("STRING", {"default": "", "tooltip": "MP3标题；留空保留原有标签"}),
                "lyric_text": ("STRING", {"multiline": True, "default": "", "tooltip": "ID3内嵌中文非同步歌词；留空保留原有"}),
                "cover_image": ("IMAGE", {"tooltip": "专辑封面IMAGE张量；不接入则不修改原有封面"}),
                "artist": ("STRING", {"default": "", "tooltip": "艺术家；留空保留原有标签"}),
                "album": ("STRING", {"default": "", "tooltip": "专辑名称；留空保留原有标签"}),
                "year": ("STRING", {"default": "", "tooltip": "年份；留空保留原有标签"}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("output_mp3_path", "status_message")
    FUNCTION = "run"
    CATEGORY = "AudioTools"
    OUTPUT_NODE = True
    DESCRIPTION = cleandoc(__doc__)

    async def run(self,
                  mp3_file_path: str,
                  trigger,
                  title="",
                  lyric_text="",
                  cover_image=None,
                  artist="",
                  album="",
                  year="year"):

        mp3_path = Path(mp3_file_path).absolute()
        status_lines = []

        if not mp3_path.exists():
            msg = f"错误：MP3文件不存在 -> {mp3_path}"
            print(f"\n❌ Mp3EditID3Tags: {msg}")
            raise FileNotFoundError(msg)
        if mp3_path.suffix.lower() != ".mp3":
            msg = f"错误：输入不是mp3文件，后缀:{mp3_path.suffix}"
            print(f"\n❌ Mp3EditID3Tags: {msg}")
            raise ValueError(msg)

        print(f"\n===== Mp3EditID3Tags 开始处理：{mp3_path} =====")
        status_lines.append(f"开始处理：{str(mp3_path)}")

        audio_mp3 = MP3(mp3_path)
        # 不存在ID3对象就新建
        if not audio_mp3.tags:
            audio_mp3.tags = ID3()
        tags = audio_mp3.tags

        # TIT2 标题，非空才覆盖
        if title.strip():
            tags["TIT2"] = TIT2(encoding=3, text=title.strip())
            log = f"更新标题(TIT2): {title.strip()}"
            print(f"ℹ️ {log}")
            status_lines.append(log)
        else:
            status_lines.append("title：保留原始值")

        # TPE1 艺术家
        if artist.strip():
            tags["TPE1"] = TPE1(encoding=3, text=artist.strip())
            log = f"更新艺术家(TPE1): {artist.strip()}"
            print(f"ℹ️ {log}")
            status_lines.append(log)
        else:
            status_lines.append("artist：保留原始值")

        # TALB 专辑
        if album.strip():
            tags["TALB"] = TALB(encoding=3, text=album.strip())
            log = f"更新专辑(TALB): {album.strip()}"
            print(f"ℹ️ {log}")
            status_lines.append(log)
        else:
            status_lines.append("album：保留原始值")

        # TYER 年份
        if year.strip():
            tags["TYER"] = TYER(encoding=3, text=year.strip())
            log = f"更新年份(TYER): {year.strip()}"
            print(f"ℹ️ {log}")
            status_lines.append(log)
        else:
            status_lines.append("year：保留原始值")

        # USLT 中文内嵌歌词，非空才覆盖
        if lyric_text.strip():
            tags["USLT"] = USLT(
                encoding=3,
                lang="zho",
                desc="",
                text=lyric_text
            )
            log = f"更新内嵌歌词，字符数：{len(lyric_text)}"
            print(f"ℹ️ {log}")
            status_lines.append(log)
        else:
            status_lines.append("lyric_text：保留原始值")

        # APIC专辑封面，仅传入图片张量才替换封面；cover_image=None则跳过不修改
        if cover_image is not None:
            img_np = (cover_image[0].cpu().numpy() * 255).astype(np.uint8)
            pil_img = Image.fromarray(img_np)
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            pic_bytes = buf.getvalue()
            tags.add(APIC(
                encoding=3,
                mime="image/png",
                type=3,
                desc="Cover",
                data=pic_bytes
            ))
            log = "更新MP3专辑封面图片"
            print(f"ℹ️ {log}")
            status_lines.append(log)
        else:
            status_lines.append("cover_image：保留原始封面")

        # 原地保存标签到原文件
        tags.save(mp3_path)
        done_msg = f"✅ ID3标签原地写入完成 {mp3_path}"
        print(done_msg)
        status_lines.append(done_msg)
        print(f"===== Mp3EditID3Tags 处理结束 =====\n")

        status_msg_out = "\n".join(status_lines)
        return (str(mp3_path), status_msg_out)


class AudioStreamProcessor:
    """
    内存音频张量处理节点，输入输出均为ComfyUI标准AUDIO，串接在SaveAudio之前。
    全部操作内存张量，不读写磁盘；比特率、文件格式、ID3标签由下游SaveAudio负责。
    """
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "audio": ("AUDIO", {
                    "tooltip": "ComfyUI标准AUDIO输入，字典 {waveform:tensor, sample_rate:int}"
                }),
            },
            "optional": {
                "target_sample_rate": (["22050", "44100", "48000"], {
                    "default": "44100",
                    "tooltip": "目标重采样率。音乐平台推荐44100；源采样率与目标一致则跳过重采样。"
                }),
                "force_stereo": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "强制转为双声道。单声道音频直接复制通道生成立体声，满足平台上传校验；已是立体声则无动作。"
                }),
                "gain_db": ("FLOAT", {
                    "default": 0.0,
                    "min": -20.0,
                    "max": 6.0,
                    "step": 0.1,
                    "tooltip": "整体增益(dB)，正值放大音量，负值降低；0为不修改。避免大于+3防止削波爆音。"
                }),
                "fade_in_sec": ("FLOAT", {
                    "default": 0.0,
                    "min": 0.0,
                    "max": 2.0,
                    "step": 0.01,
                    "tooltip": "开头淡入时长(秒)，0代表关闭淡入，用于消除音频起始爆音。"
                }),
                "fade_out_sec": ("FLOAT", {
                    "default": 0.0,
                    "min": 0.0,
                    "max": 2.0,
                    "step": 0.01,
                    "tooltip": "结尾淡出时长(秒)，0代表关闭淡出，消除音频截断爆音。"
                }),
            }
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "run"
    CATEGORY = "AudioTools"
    DESCRIPTION = cleandoc(__doc__)

    def run(self,
            audio,
            target_sample_rate="44100",
            force_stereo=True,
            gain_db=0.0,
            fade_in_sec=0.0,
            fade_out_sec=0.0):

        waveform: torch.Tensor = audio["waveform"]  # shape [B, C, T]
        src_sr: int = audio["sample_rate"]
        dst_sr = int(target_sample_rate)
        device = waveform.device

        print(f"\n===== AudioStreamProcessor =====")
        print(f"源: sr={src_sr}, shape={list(waveform.shape)}, gain={gain_db}dB")

        # 1. 重采样
        if src_sr != dst_sr:
            resampler = torchaudio.transforms.Resample(
                orig_freq=src_sr,
                new_freq=dst_sr
            ).to(device)
            waveform = resampler(waveform)
            print(f"ℹ️ 已重采样: {src_sr}Hz → {dst_sr}Hz")
        else:
            print(f"ℹ️ 采样率无需转换，保持 {src_sr}Hz")

        # 2. 强制立体声：单声道复制通道 [B,1,T] → [B,2,T]
        _, ch, _ = waveform.shape
        if force_stereo and ch == 1:
            waveform = waveform.repeat(1, 2, 1)
            print(f"ℹ️ 已强制转为立体声")

        # 3. 增益 gain db: dB转线性系数 gain_lin = 10^(db/20)
        if abs(gain_db) > 1e-6:
            gain_lin = 10.0 ** (gain_db / 20.0)
            waveform = waveform * gain_lin
            # 钳位防止削波
            waveform = torch.clamp(waveform, min=-1.0, max=1.0)
            print(f"ℹ️ 应用增益 {gain_db} dB")

        # 4. 淡入淡出
        total_samples = waveform.shape[-1]

        # 淡入
        fade_in_samples = int(fade_in_sec * dst_sr)
        if fade_in_samples > 0 and fade_in_samples <= total_samples:
            fade_in = torch.linspace(0.0, 1.0, fade_in_samples, device=device)
            waveform[..., :fade_in_samples] *= fade_in

        # 淡出
        fade_out_samples = int(fade_out_sec * dst_sr)
        if fade_out_samples > 0 and fade_out_samples <= total_samples:
            fade_out = torch.linspace(1.0, 0.0, fade_out_samples, device=device)
            waveform[..., -fade_out_samples:] *= fade_out

        if fade_in_sec > 0 or fade_out_sec >0:
            print(f"ℹ️ 淡入:{fade_in_sec}s 淡出:{fade_out_sec}s")

        print("===== AudioStreamProcessor 处理完成 =====\n")

        out_audio = {
            "waveform": waveform,
            "sample_rate": dst_sr
        }
        return (out_audio,)


NODE_CLASS_MAPPINGS = {
    "CombineTtsAudio": CombineTtsAudio,
    "Mp3EditID3Tags": Mp3EditID3Tags,
    "AudioStreamProcessor": AudioStreamProcessor,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CombineTtsAudio": "TTS分片音频合并(自定义前缀+MP3‑ID3)",
    "Mp3EditID3Tags": "MP3 Editor ID3 Tag｜MP3标签编辑器",
    "AudioStreamProcessor": "Audio 流处理器｜重采样/立体声/增益/淡入淡出",
}
# NODE_CLASS_MAPPINGS 内追加

# NODE_DISPLAY_NAME_MAPPINGS 内追加


