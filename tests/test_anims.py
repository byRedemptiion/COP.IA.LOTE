from PIL import Image

from alicia.app import build_services
from alicia.core import anims
from alicia.core.config import load_settings


def _webp(path, color, frames=3, ms=40):
    images = [Image.new("RGBA", (64, 64), (*color, 255 - i * 20)) for i in range(frames)]
    images[0].save(path, save_all=True, append_images=images[1:], duration=ms, loop=0)


def _png(path, color):
    Image.new("RGBA", (64, 64), (*color, 255)).save(path)


def test_inventory_and_lips(tmp_path):
    _webp(tmp_path / "idle.webp", (10, 10, 200))
    _webp(tmp_path / "nod.webp", (10, 200, 10))
    _png(tmp_path / "speaking_0.png", (0, 0, 0))
    _png(tmp_path / "speaking_1.png", (255, 255, 255))
    found = anims.inventory(tmp_path)
    assert found["idle"] == "idle.webp" and found["nod"] == "nod.webp"
    assert found["bouche"] == "speaking_0.png, speaking_1.png"
    assert anims.find("thinking", tmp_path) is None


def test_core_plays_states_gestures_and_lips(qt_app, tmp_path):
    from alicia.ui.core_widget import AliciaCore
    from tests.test_duo import _wait

    _webp(tmp_path / "idle.webp", (10, 10, 200))
    _webp(tmp_path / "thinking.webp", (200, 10, 200))
    _webp(tmp_path / "nod.webp", (10, 200, 10))
    _png(tmp_path / "speaking_0.png", (0, 0, 0))
    _png(tmp_path / "speaking_1.png", (255, 255, 255))
    core = AliciaCore(show_labels=False, minimum=120)
    core.load_anims(tmp_path)
    core.show()
    try:
        assert core._playing == "idle.webp" and core._frame() is not None
        core.set_state("thinking")
        assert core._playing == "thinking.webp"
        core.set_state("listening")  # pas d'animation : on garde idle
        assert core._playing == "idle.webp"
        assert core.play_gesture("nod") and core._playing == "nod.webp"
        _wait(qt_app, lambda: core._playing == "idle.webp", seconds=3)
        assert core._gesture == "" and core._playing == "idle.webp"
        assert not core.play_gesture("hop")  # pas de fichier : rien
        core.set_state("speaking")
        core._level = 0.0
        assert core._frame().toImage().pixelColor(5, 5).red() == 0  # bouche fermée
        core._level = 0.9
        assert core._frame().toImage().pixelColor(5, 5).red() == 255  # bouche ouverte
        core.grab()  # dessin sans erreur
    finally:
        core.close()


def test_window_uses_the_robot_folder(qt_app, tmp_path, monkeypatch):
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    )
    try:
        folder = window._anim_folder()
        assert folder.name == "alicia" and folder.parent.name == "anims"
        folder.mkdir(parents=True)
        _webp(folder / "idle.webp", (10, 10, 200))
        _webp(folder / "wake.webp", (200, 200, 10), frames=4, ms=50)
        window.change_setting("anims_reload", True)
        assert "idle" in window.settings_page.anims_state.text()
        assert window.core._playing == "idle.webp"
        assert window.orb.core._playing == "idle.webp"  # le rond du mode bulle aussi
        window._core("thinking")
        assert window.orb.core.state == "thinking"
        config = window._overlay_config()
        assert "wake.webp" in config["anims"] and config["durations"]["wake"] >= 200
        window.overlay_gesture("wake")
        assert window.core._playing == "wake.webp" and window.orb.core._playing == "wake.webp"
    finally:
        window.close()
