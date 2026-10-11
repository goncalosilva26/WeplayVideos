"""Split a tall PNG into side-by-side columns for quick visual review."""
import sys
from PIL import Image
src, out = sys.argv[1], sys.argv[2]
col_h = int(sys.argv[3]) if len(sys.argv) > 3 else 2000
img = Image.open(src).convert("RGB")
cols = (img.height + col_h - 1) // col_h
sheet = Image.new("RGB", (cols * (img.width + 20), col_h), (60, 60, 60))
for i in range(cols):
    part = img.crop((0, i * col_h, img.width, min(img.height, (i + 1) * col_h)))
    sheet.paste(part, (i * (img.width + 20), 0))
sheet.save(out, quality=88)
print(sheet.size)
