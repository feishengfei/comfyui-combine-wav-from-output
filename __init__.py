"""Top-level package for combine_wav_from_output."""

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
]

__author__ = """comfyui-combine-wav-from-output"""
__email__ = "feishengfei@126.com"
__version__ = "0.0.1"

from .src.combine_wav_from_output.nodes import NODE_CLASS_MAPPINGS
from .src.combine_wav_from_output.nodes import NODE_DISPLAY_NAME_MAPPINGS

WEB_DIRECTORY = "./web"
