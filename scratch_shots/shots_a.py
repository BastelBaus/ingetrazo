"""Screenshots for #1694: Expand all / Collapse all in Scenes, Sheets, BIM, the composer's scenes."""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.getcwd())
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QVector3D as V, QPen
OUT = os.path.abspath(os.environ.get("OUT", "out")); os.makedirs(OUT, exist_ok=True)
from views.main_window import MainWindow
from views.tray import ScenesPanel
ScenesPanel._render_thumbnail = lambda self, view: None
win = MainWindow(); win.resize(1500, 950); win.show()
def pump(n=8):
    for _ in range(n): app.processEvents()
pump()
scene = win.viewport.scene
from core.saved_views import SavedView
scene.scene_folders = ["Ground floor", "Upper floor", "Sections", "Exterior"]
scene.scene_folder_parents = {}
scene.saved_views[:] = [SavedView("GF plan", folder="Ground floor"), SavedView("GF kitchen", folder="Ground floor"),
    SavedView("UF plan", folder="Upper floor"), SavedView("UF bath", folder="Upper floor"),
    SavedView("Section A-A", folder="Sections"), SavedView("Section B-B", folder="Sections"),
    SavedView("Street view", folder="Exterior"), SavedView("Garden", folder="Exterior")]
from core.composition import Composicion
from core.sheet_folders import SheetFolder
plans, sec, det = SheetFolder("Plans"), SheetFolder("Sections"), SheetFolder("Details")
scene.sheet_folders[:] = [plans, sec, det]
def sh(n, f):
    c = Composicion(name=n); c.folder_id = f.id; return c
scene.compositions[:] = [sh("A-101 Ground floor", plans), sh("A-102 Upper floor", plans), sh("A-201 Section A-A", sec),
                         sh("A-202 Section B-B", sec), sh("D-01 Window", det), sh("D-02 Stair", det)]
from core.bim import tag_group
from core.group import Group
from core.mesh import Mesh
def box(x):
    m = Mesh(); m.add_face([V(x, 0, 0), V(x + 1, 0, 0), V(x + 1, 1, 0), V(x, 1, 0)]); return m
for fi, fl in enumerate(("Ground floor", "Upper floor")):
    outer = Group(Mesh(), name=fl)
    for k, (cls, nm) in enumerate((("IfcWall", "Wall N"), ("IfcWall", "Wall S"), ("IfcSlab", "Slab"), ("IfcWindow", "Window"))):
        g = Group(box(fi * 10 + k * 2)); g.name = nm; tag_group(g, cls, nm); outer.children.append(g)
    scene.groups.append(outer)
scene.version += 1
pump()

def label(img, text):
    out = QImage(img.width(), img.height() + 34, QImage.Format_ARGB32); out.fill(QColor(255, 255, 255))
    p = QPainter(out); p.drawImage(0, 34, img); f = QFont("DejaVu Sans"); f.setPixelSize(16); f.setBold(True)
    p.setFont(f); p.setPen(QColor(30, 36, 44)); p.drawText(QRect(8, 0, img.width(), 34), Qt.AlignVCenter, text); p.end(); return out
def side(imgs, name):
    w = sum(i.width() for i in imgs) + 16 * (len(imgs) - 1); h = max(i.height() for i in imgs)
    out = QImage(w, h, QImage.Format_ARGB32); out.fill(QColor(225, 228, 232)); p = QPainter(out); x = 0
    for i in imgs: p.drawImage(x, 0, i); x += i.width() + 16
    p.end(); out.save(os.path.join(OUT, name))
def ring(img, widget, btn):
    """Circle the button on a grab of widget."""
    pos = btn.mapTo(widget, btn.rect().topLeft()); r = QRect(pos, btn.size()).adjusted(-4, -4, 4, 4)
    p = QPainter(img); p.setRenderHint(QPainter.Antialiasing); p.setPen(QPen(QColor(230, 90, 0), 3)); p.drawEllipse(r); p.end(); return img

# Scenes tab
panel = win.scenes_dock.panel
dock = win.scenes_dock; dock.show(); dock.raise_()
panel.setFixedSize(360, 360); panel._shape = None; panel.refresh(); pump()
a = ring(panel.grab().toImage(), panel, panel.expand_btn)
panel.expand_btn.click(); pump()
b = ring(panel.grab().toImage(), panel, panel.expand_btn)
side([label(a, "Scenes — all open: ⊟ Collapse all"), label(b, "after one click: all folded")], "a_scenes.png")
print("scenes folds", sorted(scene.tree_folds.get("scenes", [])))
# Sheets explorer (list)
from views.sheet_browser import SheetExplorer, SceneList, _titled
ex = SheetExplorer(win); ex.setFixedSize(380, 330); ex.show(); ex.refresh(force=True); pump()
a = ring(ex.grab().toImage(), ex, ex.expand_btn)
ex.expand_btn.click(); pump()
b = ring(ex.grab().toImage(), ex, ex.expand_btn)
side([label(a, "Sheets (List) — all open"), label(b, "folded (kept in SheetFolder.expanded)")], "a_sheets.png")
# BIM
bim = win.bim_tray.bim; win.bim_tray.show(); bim.refresh(); bim.setFixedWidth(420); pump()
bim.tree.setFixedHeight(300); pump()
bar_parent = bim
a = ring(bim.grab().toImage(), bim, bim.expand_btn)
bim.expand_btn.click(); pump()
b = ring(bim.grab().toImage(), bim, bim.expand_btn)
side([label(a, "BIM — all open"), label(b, "folded")], "a_bim.png")
print("bim folds", sorted(scene.tree_folds.get("bim", [])))
# Composer scenes heading
lst = SceneList(win); box_ = _titled("Scenes", lst, tail=(lst.expand_btn,)); box_.setFixedSize(320, 300); box_.show(); pump()
a = ring(box_.grab().toImage(), box_, lst.expand_btn)
lst.expand_btn.click(); pump()
b = ring(box_.grab().toImage(), box_, lst.expand_btn)
side([label(a, "Composer · Scenes"), label(b, "folded")], "a_composer_scenes.png")
# Saved and reopened
from formats import igz
from core.scene import Scene
from pathlib import Path; path = Path(OUT) / "folds.igz"; igz.save_scene(scene, path)
other = Scene(); igz.load_into(other, path)
print("reopened tree_folds:", {k: sorted(v) for k, v in other.tree_folds.items()})
os.remove(path)
win._saved_version = scene.version
os._exit(0)
