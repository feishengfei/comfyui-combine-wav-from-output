import os
import re
from pathlib import Path
from inspect import cleandoc
from pydub import AudioSegment


class CombineTtsAudio:
    """
    将目录下 tts_000.wav / tts_001.wav 按数字序号升序合并音频
    输入目录：tts分片音频存放目录；
    in_suffix：原始分片文件后缀 wav / mp3
    out_format：合并输出格式 wav / mp3
    delete_source：合并完成后是否删除原始分片tts_xxx文件
    输出文件：输入目录下，以目录名作为文件名，例：/xxx/myfolder → /xxx/myfolder/myfolder.wav
    """
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "audio_dir": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "tts分片音频所在目录，填写绝对路径"
                }),
                "in_suffix": (["wav", "mp3"], {"default": "wav", "tooltip": "待合并分片文件的后缀"}),
                "out_format": (["wav", "mp3"], {"default": "wav", "tooltip": "合并输出音频格式"}),
                "delete_source": ("BOOLEAN", {"default": False, "tooltip": "合并完成后删除tts_000.*等分片源文件"})
            }
        }

    RETURN_TYPES = ()
    FUNCTION = "run"
    CATEGORY = "AudioTools"
    OUTPUT_NODE = True
    DESCRIPTION = cleandoc(__doc__)

    async def run(self, audio_dir: str, in_suffix: str, out_format: str, delete_source: bool):
        target_dir = Path(audio_dir).absolute()
        if not target_dir.is_dir():
            raise NotADirectoryError(f"音频目录不存在：{target_dir}")

        dir_name = target_dir.name  # 获取目录名，用作输出文件名
        output_file = target_dir / f"{dir_name}.{out_format}"

        # 匹配 tts_数字.后缀 正则，捕获序号
        pattern = re.compile(r"^tts_(\d+)\." + re.escape(in_suffix) + r"$", re.IGNORECASE)
        matched = []

        for fname in os.listdir(target_dir):
            m = pattern.match(fname)
            if m:
                seq = int(m.group(1))
                matched.append((seq, fname))

        if len(matched) == 0:
            raise FileNotFoundError(f"目录内未找到匹配 tts_xxx.{in_suffix} 的分片音频文件；目录：{target_dir}")

        # 按数字序号升序排序
        matched.sort(key=lambda x: x[0])
        sorted_files = [target_dir / fn for _, fn in matched]
        print(f"\n===== CombineTtsAudio: 找到 {len(sorted_files)} 个分片音频 =====")
        for f in sorted_files:
            print(f"  > {f.name}")

        # 音频合并
        combined = AudioSegment.empty()
        for file_path in sorted_files:
            seg = AudioSegment.from_file(file_path, format=in_suffix)
            combined += seg

        # 导出合并后的音频
        combined.export(output_file, format=out_format)
        print(f"✅ 合并完成，输出文件: {output_file}")

        # 是否删除源分片文件
        if delete_source:
            print(f"🗑️ 开启删除源分片，开始清理tts分片文件……")
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
    "CombineTtsAudio": "TTS分片音频合并(tts_xxx)"
}
