"""Demo for #1695: an atlas PDF with a clickable sheet index; renders pages with the links outlined."""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.getcwd())
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from PySide6.QtCore import QSize, QRectF, Qt, QPointF
from PySide6.QtGui import QImage, QPainter, QColor, QPen, QFont
from core.composition import Composicion, IndiceLaminas, TextoItem, FormaItem
from core.sheet_folders import SheetFolder
from formats import pdf_links as PL
from views.main_window import MainWindow

OUT = os.path.abspath(os.environ.get("OUT", "out"))
os.makedirs(OUT, exist_ok=True)
win = MainWindow(); win.resize(1500, 950)
scene = win.viewport.scene
plans, details = SheetFolder("Plans"), SheetFolder("Details")
scene.sheet_folders[:] = [plans, details]
def sheet(name, folder=None, paper="A3", land=True, label=""):
    c = Composicion(name=name, paper=paper, landscape=land)
    c.folder_id = folder.id if folder else None
    w, h = c.page_size_mm()
    c.shapes.append(FormaItem(kind="rect", x_mm=25, y_mm=25, w_mm=w - 50, h_mm=h - 50))
    c.texts.append(TextoItem(x_mm=35, y_mm=35, w_mm=200, text=label or name, size_pt=28, bold=True))
    return c
cover = Composicion(name="Cover", paper="A3", landscape=True)
cover.texts.append(TextoItem(x_mm=30, y_mm=30, w_mm=300, text="Sample house — drawing set", size_pt=30, bold=True))
cover.indices.append(IndiceLaminas(x_mm=30, y_mm=60, w_mm=150, size_pt=12, layout="tree", title="SHEET INDEX"))
sheets = [cover,
          sheet("Ground floor", plans), sheet("Upper floor", plans), sheet("Roof", plans),
          sheet("Section A-A", None), sheet("Window detail", details, "A4", False), sheet("Stair detail", details, "A4", False)]
scene.compositions[:] = sheets
comp = win._ensure_composer()
pdf = os.path.join(OUT, "sheet-set.pdf")
print("troubled", comp.export_all_pdf(pdf))
data = open(pdf, "rb").read()
pages = PL.page_objects(data)
import re
def links_on(pobj):
    body = PL._find_object(data, pobj)
    ref = re.search(rb"/Annots\s+(\d+)\s+0\s+R", body)
    arr = PL._find_object(data, int(ref.group(1))) if ref else body
    out = []
    for n in re.findall(rb"(\d+)\s+0\s+R", re.search(rb"\[([^\]]*)\]", arr).group(1)):
        a = PL._find_object(data, int(n)) or b""
        m = re.search(rb"/Dest \[(\d+) 0 R", a)
        if m:
            r = [float(v) for v in re.search(rb"/Rect \[([^\]]*)\]", a).group(1).split()]
            out.append((r, pages.index(int(m.group(1)))))
    return out
from PySide6.QtPdf import QPdfDocument, QPdfDocumentRenderOptions
doc = QPdfDocument(); doc.load(pdf)
print("pages", doc.pageCount())
scale = 1.4
imgs = []
for i in range(doc.pageCount()):
    ps = doc.pagePointSize(i)
    size = QSize(int(ps.width() * scale), int(ps.height() * scale))
    img = doc.render(i, size).convertToFormat(QImage.Format_ARGB32)
    p = QPainter(img); p.setRenderHint(QPainter.Antialiasing)
    for (x0, y0, x1, y1), tgt in links_on(pages[i]):
        r = QRectF(x0 * scale, (ps.height() - y1) * scale, (x1 - x0) * scale, (y1 - y0) * scale)
        p.setPen(QPen(QColor(230, 90, 0), 2)); p.setBrush(QColor(255, 140, 0, 45)); p.drawRect(r)
        f = QFont("DejaVu Sans"); f.setPixelSize(13); f.setBold(True); p.setFont(f)
        p.setPen(QColor(200, 60, 0))
        lab = f"→ p.{tgt + 1}"
        if r.width() > 120:
            p.drawText(QPointF(r.right() + 6, r.center().y() + 5), lab)
        else:
            p.drawText(QPointF(r.left() - 60, r.bottom() + 16), lab)
    p.end()
    img.save(os.path.join(OUT, f"b_page{i + 1}.png")); imgs.append(img)
# overview: cover big + 3 thumbnails
W = imgs[0].width()
thumbs = [im.scaledToHeight(int(imgs[0].height() * 0.48), Qt.SmoothTransformation) for im in imgs[1:4]]
ov = QImage(W + 20 + max(t.width() for t in thumbs), imgs[0].height(), QImage.Format_ARGB32); ov.fill(QColor(235, 235, 235))
p = QPainter(ov); p.drawImage(0, 0, imgs[0]); y = 0
for t in thumbs[:2]:
    p.drawImage(W + 20, y, t); y += t.height() + 10
p.end(); ov.save(os.path.join(OUT, "b_overview.png"))
# the properties panel of the index
from views.composer import IndiceCanvasItem
comp.resize(1500, 950); comp.show()
for _ in range(5): app.processEvents()
comp.comp = cover; comp._rebuild_canvas()
for _ in range(5): app.processEvents()
items = [it for it in comp.canvas.items() if isinstance(it, IndiceCanvasItem)]
comp.canvas.clearSelection(); items[0].setSelected(True)
for _ in range(10): app.processEvents()
comp.props.currentWidget().grab().save(os.path.join(OUT, "b_props.png"))
comp.grab().save(os.path.join(OUT, "b_composer.png"))
print("done")
comp._saved_version = scene.version; win._saved_version = scene.version
os._exit(0)
