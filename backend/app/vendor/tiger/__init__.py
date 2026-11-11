"""Vendored TIGER-DnR model code.

Source: https://github.com/JusperLee/TIGER (MIT License)
Weights: https://huggingface.co/JusperLee/TIGER-DnR (Apache-2.0)
Only the files required for inference are vendored; imports were adjusted.
"""
from .tiger_dnr import TIGERDNR

__all__ = ["TIGERDNR"]
