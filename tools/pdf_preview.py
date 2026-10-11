"""Render the first pages of a PDF into a contact sheet (uses Qt PDF)."""
import sys
from PIL import Image
from PySide6.QtCore import QSize
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtPdf import QPdfDocument


def render(path, maxpages=8, w=300):
    doc = QPdfDocument()
    doc.load(path)
    imgs = []
    for i in range(min(maxpages, doc.pageCount())):
        ps = doc.pagePointSize(i)
        h = int(w * ps.height() / ps.width())
        q = doc.render(i, QSize(w, h)).convertToFormat(QImage.Format.Format_RGBA8888)
        imgs.append(Image.frombuffer("RGBA", (q.width(), q.height()), bytes(q.constBits()), "raw", "RGBA", q.bytesPerLine(), 1).convert("RGB"))
    return imgs, doc.pageCount()


if __name__ == "__main__":
    app = QGuiApplication(sys.argv[:1])
    src, out = sys.argv[1], sys.argv[2]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    width = int(sys.argv[4]) if len(sys.argv) > 4 else 300
    imgs, count = render(src, n, width)
    sheet = Image.new("RGB", (len(imgs) * (width + 10), max(i.height for i in imgs) + 10), (80, 80, 80))
    for k, im in enumerate(imgs):
        sheet.paste(im, (k * (width + 10), 5))
    sheet.save(out, quality=85)
    print(count, "pages")
