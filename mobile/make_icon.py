# -*- coding: utf-8 -*-
"""Telefon surumunun ana ekran simgesi (apple-touch-icon.png, 180x180).
iOS koseleri kendisi yuvarlar; burada tam kare cizilir."""
import os
from PIL import Image, ImageDraw

S = 180 * 4
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apple-touch-icon.png")

img = Image.new("RGB", (S, S))
top, mid, bot = (255, 74, 61), (192, 124, 255), (74, 134, 255)   # kirmizi · mor · mavi (irzubal)
px = img.load()
for y in range(S):
    for x in range(S):
        t = (0.75 * y + 0.25 * x) / S
        a, b, u = (top, mid, t / 0.55) if t < 0.55 else (mid, bot, (t - 0.55) / 0.45)
        px[x, y] = tuple(int(a[i] + (b[i] - a[i]) * min(u, 1)) for i in range(3))

d = ImageDraw.Draw(img)
c, w = S / 2, S * 0.30
shield = [(c, S * 0.20), (c + w, S * 0.30), (c + w, S * 0.50),
          (c + w * 0.78, S * 0.66), (c, S * 0.81),
          (c - w * 0.78, S * 0.66), (c - w, S * 0.50), (c - w, S * 0.30)]
d.polygon(shield, fill=(255, 255, 255))
lw = int(S * 0.045)
d.line([(c - w * 0.42, S * 0.49), (c - w * 0.08, S * 0.60), (c + w * 0.48, S * 0.38)],
       fill=(91, 43, 147), width=lw, joint="curve")
img.resize((180, 180), Image.LANCZOS).save(OUT, optimize=True)
print("yazildi:", OUT)
