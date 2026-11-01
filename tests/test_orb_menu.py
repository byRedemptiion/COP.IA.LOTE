import json

from PySide6.QtWidgets import QMenu

from alicia.app import build_services
from alicia.core.config import load_settings


def _texts(menu):
    out = []
    for action in menu.actions():
        if action.isSeparator():
            out.append("—")
        elif action.menu() is not None:
            out.append((action.text(), _texts(action.menu())))
        else:
            out.append(action.text())
    return out


def _find(menu, text):
    for action in menu.actions():
        if action.menu() is not None:
            found = _find(action.menu(), text)
            if found:
                return found
        elif text in action.text():
            return action
    return None


def test_bubble_menu_structure_and_actions(qt_app, tmp_path, monkeypatch):
    from alicia.ui.main_window import MainWindow
    from alicia.ui.orb import build_menu

    monkeypatch.chdir(tmp_path)
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    )
    orb = window.orb
    try:
        menu = QMenu()
        build_menu(orb, menu)
        texts = _texts(menu)
        top = [t if isinstance(t, str) else t[0] for t in texts]
        assert top[:3] == [
            "💬  Ouvrir COP'IA'LOTE",
            "🎙  Parler à ALICIA",
            "🔊  Réécouter le dernier message",
        ]
        assert top[3] == "—" and top[4] == "💡  Mode Copilote"
        assert top[5:8] == ["👁  Vision", "🔊  Voix", "🎥  Stream"]
        assert top[9:12] == ["✏  Mode édition", "⚙  Réglages", "↻  Mettre à jour COP'IA'LOTE"]
        assert top[-1] == "✕  Quitter ALICIA"
        flat = json.dumps(texts, ensure_ascii=False)
        assert "Choisir l'IA" not in flat and "Replacer en haut" not in flat
        for kept in (
            "Analyse rapide",
            "Couper la voix",
            "Chat Twitch",
            "Message à l'autre robot",
            "Visible dans OBS",
            "Écran entier",
            "Masquer la bulle",
        ):
            assert kept in flat, kept

        calls = []
        orb.copilot_toggled.connect(lambda on: calls.append(("copilot", on)))
        _find(menu, "Mode Copilote").trigger()
        assert calls == [("copilot", True)] and window.copilot_timer.isActive()
        _find(menu, "Écran entier").trigger()
        assert window.services.analysis.vision_mode == "screen"
        window._say = lambda text: calls.append(("say", text)) or True
        window.answer.setPlainText("Garde-le pour l'instant.")
        _find(menu, "Réécouter le dernier message").trigger()
        assert ("say", "Garde-le pour l'instant.") in calls
        _find(menu, "Voix activée").trigger()
        assert not window.voice_box.isChecked() and orb.speak_on is False
        _find(menu, "Réglages").trigger()
        assert window.pages.currentWidget() is window.settings_page
    finally:
        window.close()


def test_bubble_prefs_and_edit_mode(qt_app, tmp_path, monkeypatch):
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    )
    orb = window.orb
    page = window.settings_page
    try:
        window.show_page(2)  # les réglages se chargent à l'ouverture
        assert page.orb_checks["show_hud"].isChecked()
        page.orb_checks["show_hud"].setChecked(False)
        page.orb_checks["locked"].setChecked(True)
        page.orb_checks["anims"].setChecked(False)
        assert orb.core.show_hud is False and orb.core.anims_on is False
        assert orb.prefs["locked"] is True
        if orb.position_file is not None:
            saved = json.loads(orb.position_file.read_text("utf-8"))
            assert saved["show_hud"] is False and saved["locked"] is True
        page.orb_size.setValue(300)
        page.orb_size.sliderReleased.emit()
        assert orb.size_px == 300

        orb.start_editing()
        panel = orb.edit_panel
        texts = [b.text() for b in panel.findChildren(type(page.mic_test))]
        assert "Recoller la bulle au rond" in texts and "Replacer en haut à droite" in texts
        assert "✓  Terminer l'édition" in texts
        assert orb.bubble.editing
        orb.stop_editing()
        assert not orb.bubble.editing
    finally:
        window.close()
