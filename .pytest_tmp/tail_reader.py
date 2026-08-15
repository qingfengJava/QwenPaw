# -*- coding: utf-8 -*-
"""读取日志文件尾部，UTF-8 输出到 stdout。用法: python tail_reader.py <path> [lines]"""
import io
import sys

path = sys.argv[1]
n = int(sys.argv[2]) if len(sys.argv) > 2 else 25
lines = io.open(path, "r", errors="replace").readlines()
sys.stdout.buffer.write("".join(lines[-n:]).encode("utf-8", errors="replace"))
