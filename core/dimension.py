# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Linear dimension — a measured annotation between two world points.

A ``Dimension`` records two endpoints ``a``/``b`` and an ``offset`` vector
giving where the dimension line sits relative to the measured segment.

An endpoint placed ON a vertex is **anchored** to it (a dimension belongs to
the geometry it measures): the endpoint reads the vertex's
position live, so scaling, moving or stretching the drawing takes the
dimension along and re-measures it — the first thing a user of DriveMeca's
video missed (2026-09-20, Marco: «dibujamos algo, lo acotamos, después lo
escalamos y la acotación se queda allí, no se redimensiona con el dibujo
y no se actualiza la nueva medición»). A vertex inside a component reads
through its placement's transform, so moving the instance moves the
dimension too. When the vertex is gone (erased, welded away) the endpoint
freezes where it last was. An endpoint snapped to a midpoint, an edge or a
face has no vertex to hold and stays static.

It is an annotation, not geometry: it lives in ``Scene.dimensions`` and is
drawn as a screen-space overlay (extension lines + dimension line + value
label), not in the mesh.

Two kinds, the usual convention: **aligned** (``axis`` is None) — the dimension
line parallel to a–b, measuring its length — and **linear** (``axis`` is
``"x"``/``"y"``/``"z"``) — the dimension line parallel to that axis,
measuring the segment's extent along it, the extension lines square to the
axis. A slanted line dimensioned by pulling the cursor to its SIDE gives
the vertical extent, pulling ABOVE gives the horizontal one, pulling square
off the line gives the aligned length (@pacaeiro, issue #50: «the Dimension
tool should be able to measure aligned (as it does now), but also linear»).
"""
from __future__ import annotations
from venv import logger

from PySide6.QtGui import QMatrix4x4, QVector3D
from typing_extensions import Optional

from dataclasses import dataclass

@dataclass
class DimensionLineStyle:
    thickness: float = 1.0
    line_type: Optional[str] = "solid"    
    color: Optional[float] = None
    hidden: bool = False


class VertexAnchor:
    """A hold on one mesh vertex: the vertex, the mesh that registers it
    (to notice when it is gone) and the chain of groups whose transforms
    place it in the world — empty for loose geometry, ``[group]`` for a
    classic group, ``[component, child, …]`` down a nested placement."""

    __slots__ = ("vertex", "mesh", "chain","_count")

    def __init__(self, vertex, mesh, chain=()) -> None:
        self.vertex = vertex
        self.mesh = mesh
        self.chain = tuple(chain)

    def matrix(self):
        """The composed placement transform, or ``None`` when every group
        on the chain keeps its geometry in world coordinates."""
        m = None
        for g in self.chain:
            x = getattr(g, "xform", None)
            if x is None:
                continue
            m = QMatrix4x4(x) if m is None else m * x
        return m

    def alive(self, scene=None) -> bool:
        """Whether the hold still means something: the mesh registers this
        very vertex (not erased, not welded into another one), something
        references it, and — given the scene — the mesh is still part of
        the model: the loose mesh, or a group the scene still lists. A
        group exploded, or grouped into another, leaves its old mesh
        behind with the vertex in it, positions frozen for ever."""
        self._count =  self._count + 1 if hasattr(self, "_count") else 1
        v = self.vertex
        try:
            if self.mesh.vertex_at(v.position) is not v or not v.edges:
                return False
        except Exception:  # noqa: BLE001 — a mesh that cannot answer
            return False
        if scene is None:
            return True
        if not self.chain:
            return self.mesh is getattr(scene, "loose_mesh", scene.mesh)
        return self.chain[0] in (getattr(scene, "groups", None) or ())

    def position(self, scene=None):
        """The vertex's world position now — ``None`` once the hold is no
        longer :meth:`alive`, which is the anchor's cue to let go."""
        if not self.alive(scene):
            return None
        v = self.vertex
        m = self.matrix()
        return m.map(QVector3D(v.position)) if m is not None \
            else QVector3D(v.position)


def resolve_vertex_anchor(scene, point: QVector3D, tol: float = 1e-4) -> bool | None:
    """The vertex sitting at *point* (world), as a :class:`VertexAnchor`,
    or ``None``. Loose geometry first, then every group placement, the
    point taken back into each placement's local coordinates — O(1) per
    mesh through the vertex registry, so a click costs nothing on a big
    model. ``tol`` is the registry's own weld resolution (0.1 mm): a
    point that came through a placement's float32 matrix and back lands
    within a micron of the vertex, which a tighter tolerance rejected on
    far-out coordinates."""
    from core.group import iter_placements
    print("resolve_vertex_anchor called with point:", point, "tol:", tol)
    def hit(mesh, local, chain):
        v = mesh.vertex_at(local)
        if v is None or (v.position - local).length() > tol:
            return None
        if not v.edges:
            # An orphan: a vertex nothing references any more. Make Group
            # moves the geometry into the group's mesh and leaves these
            # behind in the loose one, at the very same spots — so a
            # dimension on a fresh group anchored to the ghost, and the
            # group scaled away from under it (Marco, 2026-09-20: «faltaba
            # en grupo»). A point held by nothing holds nothing.
            return None
        return VertexAnchor(v, mesh, chain)

    found = hit(scene.mesh, QVector3D(point), ())
    if found is not None:
        return found
    for g in getattr(scene, "groups", None) or ():
        if getattr(g, "billboard", False):
            continue
        for placed, m in iter_placements(g):
            local = QVector3D(point)
            chain = _chain_to(g, placed)
            if m is not None:
                inv, ok = m.inverted()
                if not ok:
                    continue
                local = inv.map(local)
            found = hit(placed.mesh, local, chain)
            if found is not None:
                return found
    return None


def _chain_to(root, target) -> tuple:
    """The groups from *root* down to *target* (inclusive) — the transforms
    an anchor composes. Depth-first, like ``iter_placements``."""
    if root is target:
        return (root,)
    for child in getattr(root, "children", None) or ():
        below = _chain_to(child, target)
        if below:
            return (root,) + below
    return ()


_AXIS_VECTORS = {
    "x": QVector3D(1.0, 0.0, 0.0),
    "y": QVector3D(0.0, 1.0, 0.0),
    "z": QVector3D(0.0, 0.0, 1.0),
}

#: A linear dimension is offered only when the segment makes at least this
#: angle with the axis (a near-parallel one reads the same as the aligned
#: dimension) and at most its complement (a near-square one measures
#: nothing). Between those, the two kinds say different things.
_LINEAR_MIN_DEG = 15.0

#: The cursor pulled square off the segment — within this angle of its
#: perpendicular, measured from the midpoint — always asks for the aligned
#: dimension, however far it goes: on a steep line a square pull soon
#: passes the lower endpoint's column, and without this corridor it would
#: turn into the vertical linear one under the drafter's hand.
_ALIGNED_CONE_DEG = 20.0


def _linear_frame(a: QVector3D, b: QVector3D, axis: str | None):
    """``(u, e)`` for a linear dimension along ``axis``: ``u`` the axis and
    ``e`` the extension-line direction — square to ``u``, in the plane of
    the axis and the segment. ``None`` for an aligned dimension, a
    degenerate segment, or a segment that runs along the axis (nothing to
    project; the dimension falls back to aligned)."""
    u = _AXIS_VECTORS.get(axis)
    if u is None:
        return None
    ab = b - a
    length = ab.length()
    if length < 1e-9:
        return None
    d = ab / length
    e = d - u * QVector3D.dotProduct(d, u)
    if e.length() < 1e-6:
        return None
    return u, e / e.length()


class Dimension:
    """See the module docstring. ``a`` and ``b`` read live through their
    anchors; assigning them sets the frozen position (what a rigid
    transform of the whole model does) and keeps the anchor."""

    def __init__(self, a: QVector3D, b: QVector3D, offset: QVector3D,
                 layer: str | None = None, text: str | None = None,
                 axis: str | None = None) -> None:
        #self._a = QVector3D(a)
        #self._b = QVector3D(b)

        print(f"new dim: a={a} {id(a)=}\n"
              f"         b={b} {id(b)=}\n")


        self._a = a
        self._b = b
        self.ofs = offset.length()

        self.offset = QVector3D(offset)/self.ofs        
        self.height_vec = QVector3D.crossProduct(self.a-self.b,self.offset)
        self.height_vec = self.height_vec / self.height_vec.length()
        self.height=0

        #self.dimension_style = DimensionLineStyle(1.5) # the line with the arrows
        #self.endline_style   = DimensionLineStyle(1.0) # the line from the arraws to the surface of the anker points
        #self.helpline_style  = DimensionLineStyle(0.5) # the line from the anker points to the endline (i.e. optional)

        self._ab_uvector : QVector3D | None = None    # a unit vector from a to b
        self._ofs_uvector : QVector3D | None = None   # a orthogonal unit vector in the direction the dimension line is shown

                        


        
        #: ``None`` = aligned; ``"x"``/``"y"``/``"z"`` = linear along that
        #: world axis (see the module docstring).
        self.axis = axis if axis in _AXIS_VECTORS else None


        #: Layer (tag) the annotation lives on; ``None`` = default
        #: layer. Scenes hide layers, so a plan scene can show a clean model
        #: and an "Anotaciones" layer can carry the cotas and leader texts.
        self.layer = layer
        #: Custom text (double-click the value to edit it);
        #: ``None`` shows the measured value, and ``<>`` inside the text
        #: stands for it.
        self.text = text
        self.anchor_a: VertexAnchor | None = None
        self.anchor_b: VertexAnchor | None = None
        self._scene = None                   # set by bind(); re-binding

        print(self)


    @property
    def _ab_unit_vector(self) -> QVector3D:
        """ returns the unit length of teh vector between bot anchor points """
        #raise NotImplemented("not correct, only if bot are on the same axis !!")
        ab = (self.a-self.b)
        length = ab.length()
        return ab/length if length > 1e-9 else QVector3D(1,0,0)

    @property
    def _offset_unit_vector(self):
        ab = (self.a-self.b)
        return ab/ab.length()


    def __str__(self) -> str:  # pragma: no cover - debug aid
        return (f"Dimension( a={self.a} {id(self.a)=}\n"
                f"           b={self.b} {id(self.b)=}\n"
                f"           offset={self.offset},\n"
                f"           ofs={self.ofs},\n"
                f"           height={self.height},\n"
                f"           axis={self.axis},\n"
                f"           layer={self.layer},\n"
                f"           text={self.text})")

    
    @property
    def ab(self) -> QVector3D:
        return self._b - self._a

    @property
    def a(self) -> QVector3D:
        return self._a 
    @property
    def a_dim(self) -> QVector3D:
        height_vector = QVector3D.crossProduct(self.offset,self.ab)
        #return self.line_points()[0] + self.height_vec * self.height
        return self.line_points()[0] + height_vector * self.height
    
    @property
    def a_end(self) -> QVector3D:     
        height_vector = QVector3D.crossProduct(self.offset,self.ab)
        #return self.a + self.height_vec * self.height
        return self.a + height_vector * self.height
                

    @property
    def b(self) -> QVector3D:
        return self._b 
    @property
    def b_dim(self) -> QVector3D:
        height_vector = QVector3D.crossProduct(self.offset,self.ab)
        #return self.line_points()[1] + self.height_vec * self.height
        return self.line_points()[1] + height_vector * self.height
    @property
    def b_end(self) -> QVector3D:
        height_vector = QVector3D.crossProduct(self.offset,self.ab)
        #return self.b + self.height_vec * self.height
        return self.b + height_vector * self.height



    def switch_endpoints(self):
        ''' switch the endpoints a and b of the dimension, keeping the offset and axis the same '''
        self._a, self._b = self._b, self._a

    
    def move_by(self, step: QVector3D, mode: Optional[str] = None  ) -> None:
        """Apply one step — the tool's live preview uses it too."""
        print("Dim.MoveDim:",mode,step)
        print(self)
        print(f"{step=}")

    
        if self.axis is None:
            ab = self.b - self.a
        else:
            # TODO: use the axis from starting from A
            ab = self.b - self.a

    
        length = ab.length()
        if length <= 1e-9:
            return
        
        #d = ab / length
        #step = step - d * QVector3D.dotProduct(step, d)
        
        #self.offset = self.offset + self.offset/self.offset.length()*step.length()
        if True: # offset
            #step_projected = QVector3D.dotProduct(step, self.offset) / self.offset.lengthSquared() * self.offset
            step_projected = QVector3D.dotProduct(step, self.offset) / self.offset.lengthSquared() 
            self.ofs += step_projected
        if True:
            #else: # height
            height_vector = QVector3D.crossProduct(self.offset,self.ab)
            step_projected = QVector3D.dotProduct(step, height_vector) / height_vector.lengthSquared() 
            self.height += step_projected


        
        print(f"{step=}")
        print(f"{step_projected=}")
        print(f"{self.offset=}")
        print(f"{mode=}")


        return

        #self.offset += step_projected

        print(f"{self.offset=}")

        height_step = step-step_projected

        print(f"{height_step=}")
        height_step_projected = QVector3D.dotProduct(height_step, self.height_vec) / self.height_vec.lengthSquared() * self.height_vec

        direction = height_step_projected/height_step_projected.length()
        print(f"{direction=}")
        direction2 = QVector3D.dotProduct(direction,self.height_vec)
        print(f"{direction2=}")

        #self.height += height_step.length() * (-1 if direction2<0 else 1)

        #h= QVector3D.crossProduct(ab, step_projected)
        #print(f"{h=}")

        #step_orthogonal = h
        #print(f"{step_orthogonal=}")
        #ll = step_orthogonal.lengthSquared()
        #if ll > 0:
            #height_projected= QVector3D.dotProduct(step, step_orthogonal) / step_orthogonal.lengthSquared() * step_orthogonal
            #print(f"{height_projected=}")
            #self.height +=  height_projected

        #if mode == "line":            
        #    ab = self.b - self.a
        #    length = ab.length()
        #    if length > 1e-9:
        #        d = ab / length
        #        step = step - d * QVector3D.dotProduct(step, d)
        #    dim.offset = dim.offset + step
        #else:
        #    if dim.anchor_a is None:
        #        dim.a = dim.a + step
        #    if dim.anchor_b is None:
        #        dim.b = dim.b + step

    # ---- drawing style ------------------------------------------------------
    @property
    def dimension_style(self) -> tuple[float, str, float]:
        #thickness, style, color
        return (1.5, "solid", (0.0,1.0,0.5) )

    # ---- endpoints ----------------------------------------------------------
    def _live(self, which: str) -> QVector3D:
        anchor = getattr(self, "anchor_" + which)
        if anchor is None:
            return getattr(self, "_" + which)
        scene = self._scene
        p = anchor.position(scene)
        if p is None:
            # The hold is gone — but the geometry may just have changed
            # hands: Make Group puts new vertices in the group's mesh at
            # the very spots the loose ones stood, Explode the other way
            # round (Marco, 2026-09-20: a cube dimensioned, then cube AND
            # dimension grouped, then scaled — «la cota no sigue»). Look
            # again where the endpoint last was; freeze only when nothing
            # stands there any more.
            frozen = getattr(self, "_" + which)
            again = (resolve_vertex_anchor(scene, frozen)
                     if scene is not None else None)
            setattr(self, "anchor_" + which, again)
            if again is None:
                return frozen
            p = again.position(scene)
            if p is None:
                setattr(self, "anchor_" + which, None)
                return frozen
        setattr(self, "_" + which, p)
        return p

    #@property
    #def a(self) -> QVector3D:
    #    return self._live("a")

    @a.setter
    def a(self, value: QVector3D) -> None:
        #self._a = QVector3D(value)
        print("set_a")
        self._a = value

    #@property
    #def b(self) -> QVector3D:
    #    return self._live("b")

    @b.setter
    def b(self, value: QVector3D) -> None:
        #self._b = QVector3D(value)
        print("set_b")
        self._b = value

    def bind(self, scene) -> None:
        """Anchor each endpoint to the vertex under it, if there is one —
        at placement, and again when a document is opened (the .igz keeps
        positions, and the vertex at that very position is the one the
        drafter snapped to)."""
        #print("bind called with scene:", scene,"\n")
        #print("- ", scene.mesh.edges,'\n"')
        self._scene = scene
        self.anchor_a = resolve_vertex_anchor(scene, self._a)
        self.anchor_b = resolve_vertex_anchor(scene, self._b)

        #self._a = resolve_vertex_anchor(scene, self._a)
        #self._b = resolve_vertex_anchor(scene, self._b)
        
        #print(self)  


    def refresh_anchors(self, scene) -> None:
        """Re-take a hold that died — the vertex changed meshes — from the
        vertex now standing at the endpoint; the history calls this after
        every command, so a group made and scaled in one breath still
        carries its dimension. An endpoint never anchored stays static."""
        self._scene = scene
        for which in ("a", "b"):
            anchor = getattr(self, "anchor_" + which)
            if anchor is None or anchor.alive(scene):
                continue
            setattr(self, "anchor_" + which,
                    resolve_vertex_anchor(scene, getattr(self, "_" + which)))

    @property
    def anchored(self) -> bool:
        """Both endpoints held by vertices."""
        return self.anchor_a is not None and self.anchor_b is not None

    def anchor_points(self) -> list:
        """The world positions of the anchored endpoints (0, 1 or 2)."""
        return [p for p, an in ((self.a, self.anchor_a), (self.b, self.anchor_b))
                if an is not None]

    # ---- geometry -----------------------------------------------------------
    def display_text(self, measured: str) -> str:
        """What the annotation shows: the custom text with ``<>`` swapped
        for the formatted measurement, or the measurement itself."""
        if self.text:
            return self.text.replace("<>", measured)
        return measured

    def value(self) -> float:
        """Measured length (metres): the segment's, or — linear — its extent
        along the axis."""
        frame = _linear_frame(self.a, self.b, self.axis)
        if frame is not None:
            return abs(QVector3D.dotProduct(self.b - self.a, frame[0]))
        return (self.b - self.a).length()

    def label(self) -> str:
        from core.units import fmt_len
        return fmt_len(self.value())

    def perpendicular_offset(self) -> QVector3D:
        """The offset with any component ALONG the measured segment
        removed: the geometry may have turned under an anchored dimension
        since it was placed, and the extension lines must stay square to
        the line (the line itself is parallel to a–b whatever the offset)."""
        frame = _linear_frame(self.a, self.b, self.axis)
        if frame is not None:
            # Linear: only the pull along the extension direction counts.
            e = frame[1]
            return e * QVector3D.dotProduct(self.offset*self.ofs, e)
        ab = self.b - self.a
        length = ab.length()
        if length < 1e-9:
            return QVector3D(self.offset*self.ofs)
        dir_ = ab / length
        along = QVector3D.dotProduct(self.offset*self.ofs, dir_)
        return self.offset*self.ofs - dir_ * along

    def line_points(self) -> tuple[QVector3D, QVector3D]:
        """The dimension line's endpoints. Aligned: ``a``/``b`` shifted by
        the offset. Linear: each endpoint pushed along the extension
        direction until both sit on one line parallel to the axis — the one
        through ``a + offset``."""

        #return self.a_dim, self.b_dim
    
        frame = _linear_frame(self.a, self.b, self.axis)
        if frame is not None:
            _u, e = frame
            t_a = QVector3D.dotProduct(self.offset*self.ofs, e)
            t_b = t_a - QVector3D.dotProduct(self.b - self.a, e)
            return self.a + e * t_a, self.b + e * t_b
        off = self.perpendicular_offset()
        return self.a + off, self.b + off

    def midpoint(self) -> QVector3D:
        ap, bp = self.line_points()
        return (ap + bp) * 0.5

    @staticmethod
    def offset_for_cursor(a: QVector3D, b: QVector3D,
                          cursor: QVector3D) -> QVector3D:
        """Offset placing the dimension line through ``cursor`` while staying
        parallel to ``a``–``b``: the component of ``cursor − a`` perpendicular
        to the segment direction."""
        ab = b - a
        length = ab.length()
        if length < 1e-9:
            return cursor - a
        dir_ = ab / length
        to_cursor = cursor - a
        along = QVector3D.dotProduct(to_cursor, dir_)
        return to_cursor - dir_ * along

    @staticmethod
    def placement_for_cursor(a: QVector3D, b: QVector3D,
                             cursor: QVector3D) -> tuple[QVector3D, str | None]:
        """``(offset, axis)`` for the cursor's position — which dimension
        the drafter is asking for, and where its line goes. The usual
        reading: the cursor pulled PAST both endpoints along an axis's
        extension direction asks for the linear dimension along that axis
        (to the side of a slanted line → its vertical extent; above it →
        the horizontal one); pulled square off the segment, anywhere else,
        or past both endpoints in two directions at once (the corner), the
        aligned one. An axis within
        ``_LINEAR_MIN_DEG`` of the segment, or of square to it, is never
        offered: the linear reading would only duplicate or annul the
        aligned one."""
        import math
        ab = b - a
        length = ab.length()
        if length < 1e-9:
            return cursor - a, None
        d = ab / length
        aligned = Dimension.offset_for_cursor(a, b, cursor)
        w = cursor - (a + b) * 0.5
        along = abs(QVector3D.dotProduct(w, d))
        perp = (w - d * QVector3D.dotProduct(w, d)).length()
        if along <= math.tan(math.radians(_ALIGNED_CONE_DEG)) * perp:
            return aligned, None
        lo = math.sin(math.radians(_LINEAR_MIN_DEG))
        hi = math.cos(math.radians(_LINEAR_MIN_DEG))
        best = None                          # (overshoot, axis, offset)
        beyond = 0
        for name in ("x", "y", "z"):
            frame = _linear_frame(a, b, name)
            if frame is None:
                continue
            u, e = frame
            along = abs(QVector3D.dotProduct(d, u))
            if along < lo or along > hi:
                continue
            t = QVector3D.dotProduct(cursor - a, e)
            span = QVector3D.dotProduct(ab, e)
            low, high = min(0.0, span), max(0.0, span)
            over = (low - t) if t < low else (t - high) if t > high else 0.0
            if over <= 1e-9:
                continue
            beyond += 1
            if best is None or over > best[0]:
                best = (over, name, e * t)
        if best is None or beyond > 1:
            return aligned, None
        return best[2], best[1]
