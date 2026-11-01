from alicia.app import build_services
from alicia.core.config import load_settings
from alicia.core.duo_presence import ABSENT_AFTER_S, PeerPresence, label


def test_presence_states():
    p = PeerPresence()
    kw = {"enabled": True, "has_code": True, "connected": True}
    assert p.state(0, enabled=False, has_code=True, connected=True) == "off"
    assert p.state(0, enabled=True, has_code=False, connected=False) == "unavailable"
    assert p.state(0, enabled=True, has_code=True, connected=False) == "connecting"
    assert p.state(0, **kw) == "absent"
    p.seen(100)
    assert p.state(150, **kw) == "present"
    assert p.state(150, speaking=True, **kw) == "speaking"
    assert p.state(100 + ABSENT_AFTER_S + 1, **kw) == "absent"
    p.seen(500)
    p.left = True
    assert p.state(510, **kw) == "absent"
    assert label("present", feminine=True) == "Présente" and label("absent") == "Absent"


def test_duo_panel_follows_the_other_robot(qt_app, tmp_path, monkeypatch):
    from dataclasses import replace

    from alicia.core.config import Secret
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    )
    panel = window.duo_panel
    try:
        window._show_duo_panel()
        assert panel.rows["me"][1].text() == "ALICIA"  # ce PC : son propre robot en haut
        assert panel.summary.text() == "DUO DÉSACTIVÉ"
        duo = replace(window.services.settings.duo, enabled=True, code=Secret("x"))
        window.services.settings = replace(window.services.settings, duo=duo)
        window._show_duo_panel()
        assert panel.summary.text() == "EN ATTENTE DE VIIRUS"
        window._duo_received({"kind": "ping", "name": "VIIRUS", "player": "Redem"})
        assert panel.rows["peer"][2].text() == "Présent · avec Redem"
        assert panel.summary.text() == "MODE DUO ACTIF"
        window._duo_received({"kind": "bye", "name": "VIIRUS"})
        assert panel.rows["peer"][2].text() == "Absent"
        window.show_page(0)
        panel.manage.emit()
        assert window.settings_page.current_tab == "social"
    finally:
        window.close()
