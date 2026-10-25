import os
import re
import io
import numpy as np
from pathlib import Path
from inspect import cleandoc
from PIL import Image
from pydub import AudioSegment
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TPE1, TALB, TYER


class CombineTtsAudio:
    """
    将目录下 <prefix>_000.wav / <prefix>_001.wav 按数字序号升序合并音频
    audio_dir：分片音频存放目录；
    file_prefix：分片文件前缀，默认 tts
    in_suffix：原始分片文件后缀 wav / mp3
    out_format：合并输出格式 wav / mp3
    delete_source：合并完成后是否删除原始分片文件
    cover_image: 【可选】ComfyUI IMAGE张量，用作mp3专辑封面，仅mp3生效
    artist: ID3艺术家标签(mp3 only)
    album: ID3专辑标签(mp3 only)
    year: ID3年份标签(mp3 only)
    trigger：时序触发端口，连接上游输出，保证磁盘文件全部写完再执行合并

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
                "trigger": ("*", {"tooltip": "时序触发端口，连接上游节点输出，仅用于等待全部文件保存到磁盘，不读取数据"})
            },
            "optional": {
                "cover_image": ("IMAGE", {"tooltip": "mp3专辑封面图片，接Load Image输出；仅out_format=mp3时生效"}),
                "artist": ("STRING", {"default": "artist", "tooltip": "ID3 artist 艺术家标签(mp3 only)"}),
                "album": ("STRING", {"default": "album", "tooltip": "ID3 album 专辑标签(mp3 only)"}),
                "year": ("STRING", {"default": "year", "tooltip": "ID3 year 年份标签(mp3 only)"}),
            }
        }

    RETURN_TYPES = ()
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

        combined.export(output_file, format=out_format)
        print(f"✅ 合并完成，输出文件: {output_file}")

        # -------- MP3 ID3标签处理：仅输出为mp3时执行 --------
        if out_format == "mp3":
            print(f"ℹ️ 开始写入MP3 ID3元数据标签")
            audio_mp3 = MP3(output_file)
            # 初始化ID3，不存在则新建
            if not audio_mp3.tags:
                audio_mp3.tags = ID3()
            tags = audio_mp3.tags

            # 写入 artist / album / year
            tags["TPE1"] = TPE1(encoding=3, text=artist)
            tags["TALB"] = TALB(encoding=3, text=album)
            tags["TYER"] = TYER(encoding=3, text=year)

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
            print(f"✅ MP3 ID3标签写入完成(artist:{artist}, album:{album}, year:{year})")

        if delete_source:
            print(f"🗑️ 开启删除源分片，开始清理分片文件……")
            for f in sorted_files:
                try:
                    os.unlink(f)
                    print(f"    deleted: {f.name}")
                except Exception as e:
                    print(f"⚠️ 删除失败 {f.name}: {str(e)}")

        print(f"===== CombineTtsAudio: 全部处理结束 =====\n")
        return {}


NODE_CLASS_MAPPINGS = {
    "CombineTtsAudio": CombineTtsAudio
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CombineTtsAudio": "TTS分片音频合并(自定义前缀+MP3‑ID3)"
}
