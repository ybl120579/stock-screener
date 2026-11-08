# -*- coding: utf-8 -*-
"""打印本机局域网 IP（用于手机访问时提示地址）。"""
import socket

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(("223.5.5.5", 80))
    ip = s.getsockname()[0]
except Exception:
    ip = "127.0.0.1"
finally:
    s.close()
print(ip)
