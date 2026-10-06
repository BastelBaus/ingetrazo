"""Layer organization, inherited state and saved-view persistence."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D

from core.camera import OrbitCamera
from core.layers import DEFAULT_LAYER, Layer, LayerFolder, assign_layer
from core.saved_views import SavedView
from core.scene import Scene
from formats.igz import load_into, save_scene
from views.tray import LayersPanel


@pytest.fixture
def panel():
    scene = Scene()
    viewport = SimpleNamespace(scene=scene, update=lambda: None)
    widget = LayersPanel(SimpleNamespace(viewport=viewport))
    yield widget
    widget.close()


def populate(panel):
    scene = panel._scene()
    root = LayerFolder("Building", position=1)
    child = LayerFolder("Ground", parent_id=root.uid)
    layer = Layer("Walls", folder_id=child.uid)
    scene.layer_folders = [root, child]
    scene.layers += [layer, Layer("Furniture", position=2)]
    panel.refresh()
    return scene, root, child, layer


def test_folder_state_filters_geometry_and_selection(panel):
    scene, root, child, layer = populate(panel)
    edge = scene.mesh.add_edge(QVector3D(), QVector3D(1, 0, 0))
    assign_layer(edge, layer.name)
    scene.selection.add(edge)
    item = panel.tree.topLevelItem(1)
    item.setCheckState(2, Qt.Checked)
    assert scene.entity_visible(edge)
    assert not scene.entity_selectable(edge)
    assert not scene.selection
    item.setCheckState(2, Qt.Unchecked)
    item.setCheckState(1, Qt.Unchecked)
    assert not scene.entity_visible(edge)
    assert not list(scene.render_edges())
    assert layer.visible  # folder switches preserve individual layer switches
    item.setCheckState(1, Qt.Checked)
    assert scene.entity_visible(edge)
    child.visible = False
    assert not scene.entity_visible(edge)
    assert scene.layer_state(DEFAULT_LAYER) == (True, False)


def test_nested_folders_round_trip_and_clear(panel, tmp_path):
    scene, root, child, layer = populate(panel)
    root.visible = False
    root.locked = True
    root.expanded = False
    layer.position = 4
    scene.saved_views = [SavedView.capture("Plan", scene, OrbitCamera())]
    path = tmp_path / "folders.igz"
    save_scene(scene, path)
    fresh = Scene()
    load_into(fresh, path)
    assert [f.to_dict() for f in fresh.layer_folders] == [f.to_dict() for f in scene.layer_folders]
    assert fresh.layer("Walls").to_dict() == layer.to_dict()
    assert fresh.layer_state("Walls") == (False, True)
    root2 = fresh.layer_folders[0]
    root2.visible = True
    fresh.saved_views[0].apply(fresh, OrbitCamera())
    assert not root2.visible
    fresh.clear()
    assert fresh.layer_folders == []
    assert [ly.name for ly in fresh.layers] == [DEFAULT_LAYER]


def test_move_reorder_and_root(panel):
    scene, root, child, layer = populate(panel)
    tree = panel.tree
    ground = tree.topLevelItem(1).child(0)
    furniture = tree.takeTopLevelItem(2)
    ground.insertChild(0, furniture)
    panel._on_tree_moved()
    assert scene.layer("Furniture").folder_id == child.uid
    assert scene.layer("Furniture").position < layer.position
    ground = tree.topLevelItem(1).child(0)
    tree.setCurrentItem(ground.child(0))
    panel._on_move_to_root()
    assert scene.layer("Furniture").folder_id is None
    assert layer.folder_id == child.uid


def test_delete_folder_keeps_layers_and_subfolders(panel):
    scene, root, child, layer = populate(panel)
    panel.tree.setCurrentItem(panel.tree.topLevelItem(1))
    panel._on_delete()
    assert scene.layer_folders == [child]
    assert child.parent_id is None
    assert layer in scene.layers and layer.folder_id == child.uid
    panel.tree.setCurrentItem(panel.tree.topLevelItem(1))
    panel._on_delete()
    assert scene.layer_folders == []
    assert layer.folder_id is None


def test_add_and_collapse(panel):
    scene, root, child, layer = populate(panel)
    tree = panel.tree
    tree.setCurrentItem(tree.topLevelItem(1).child(0))
    panel._on_add()
    assert scene.layers[-1].folder_id == child.uid
    height = tree.height()
    tree.topLevelItem(1).setExpanded(False)
    assert not root.expanded and tree.height() < height
    panel.refresh()
    assert not tree.topLevelItem(1).isExpanded()
    tree.setCurrentItem(tree.topLevelItem(1))
    panel._on_add_folder()
    assert scene.layer_folders[-1].parent_id == root.uid


def test_legacy_order_and_invalid_parents(panel):
    scene = panel._scene()
    scene.layers += [Layer.from_dict({"name": name}) for name in ("B", "A", "C")]
    panel.refresh()
    assert [panel.tree.topLevelItem(i).text(0) for i in range(4)] == [DEFAULT_LAYER, "B", "A", "C"]
    root = LayerFolder("Root", uid="a", parent_id="b")
    child = LayerFolder("Child", uid="b", parent_id="a", visible=False)
    scene.layer_folders = [root, child]
    scene.layer("B").folder_id = root.uid
    panel.refresh()
    assert panel.tree.topLevelItemCount() == 5
    assert scene.layer_state("B") == (False, False)
    assert not panel.tree.topLevelItem(0).flags() & Qt.ItemIsDragEnabled
    assert not panel.tree.topLevelItem(0).flags() & Qt.ItemIsDropEnabled


def test_legacy_scene_recall_restores_flat_visibility(panel):
    scene, root, child, layer = populate(panel)
    root.visible = False
    SavedView.from_dict({"name": "Old", "hidden_layers": ["Walls"]}).apply(scene, OrbitCamera())
    assert root.visible and child.visible and not layer.visible
    root.visible = False
    view = SavedView.capture("New", scene, OrbitCamera())
    root.visible = True
    view.recapture(scene, OrbitCamera())
    assert not view.hidden_layer_folders


def test_empty_folder_document_clears():
    scene = Scene()
    scene.layer_folders.append(LayerFolder("Empty"))
    scene.clear()
    assert not scene.layer_folders


@pytest.mark.parametrize("fail", [False, True])
def test_sheet_scene_restores_live_folder_visibility(panel, fail):
    from core.composition import MarcoVista
    import views.composer as composer
    scene, root, child, layer = populate(panel)
    camera = OrbitCamera()
    root.visible = False
    scene.saved_views = [SavedView.capture("Plan", scene, camera)]
    root.visible = True
    owner = next(c for c in vars(composer).values()
                 if isinstance(c, type) and hasattr(c, "_with_frame_camera"))
    fake = SimpleNamespace(_window=SimpleNamespace(viewport=SimpleNamespace(
        scene=scene, camera=camera, update=lambda: None)))
    frame = MarcoVista(view_key="scene:Plan")
    def render():
        assert not root.visible
        assert not scene.layer_state(layer.name)[0]
        if fail:
            raise RuntimeError("Rendering failed")
        return "ok"
    if fail:
        with pytest.raises(RuntimeError):
            owner._with_frame_camera(fake, frame, render)
    else:
        assert owner._with_frame_camera(fake, frame, render) == "ok"
    assert root.visible


def test_rename_nested_layer_updates_geometry_and_saved_views(panel):
    from core.group import Group
    from core.mesh import Mesh
    from core.textlabel import TextLabel
    scene, root, child, layer = populate(panel)
    group = Group(Mesh())
    edge = group.mesh.add_edge(QVector3D(), QVector3D(1, 0, 0))
    assign_layer(edge, layer.name)
    scene.groups.append(group)
    label = TextLabel(QVector3D(), QVector3D(1, 1, 0), "Wall")
    assign_layer(label, layer.name)
    scene.text_labels.append(label)
    scene.saved_views.append(SavedView("Plan", hidden_layers=[layer.name]))
    panel.tree.topLevelItem(1).child(0).child(0).setText(0, "Structure")
    assert edge.layer == label.layer == "Structure"
    assert scene.saved_views[0].hidden_layers == ["Structure"]
    assert layer.folder_id == child.uid
