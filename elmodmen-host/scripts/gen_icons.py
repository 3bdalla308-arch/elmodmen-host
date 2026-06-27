from PIL import Image
import os

base = "/data/elmodmen-host/static"
src = Image.open(os.path.join(base, "install.png")).convert("RGBA")

def square(img):
    w, h = img.size
    s = min(w, h)
    l = (w - s) // 2
    t = (h - s) // 2
    return img.crop((l, t, l + s, t + s))

sq = square(src)

def save(size, path):
    sq.resize((size, size), Image.LANCZOS).save(path)

ico = os.path.join(base, "icons")
save(512, os.path.join(ico, "icon-512.png"))
save(192, os.path.join(ico, "icon-192.png"))
save(512, os.path.join(ico, "icon-512-maskable.png"))
save(192, os.path.join(ico, "icon-192-maskable.png"))
save(180, os.path.join(ico, "apple-touch-icon.png"))
save(32, os.path.join(ico, "favicon-32.png"))
save(16, os.path.join(ico, "favicon-16.png"))

sq.resize((64, 64), Image.LANCZOS).save(
    os.path.join(base, "favicon.ico"),
    sizes=[(16, 16), (32, 32), (48, 48), (64, 64)],
)
print("ICONS_OK")
