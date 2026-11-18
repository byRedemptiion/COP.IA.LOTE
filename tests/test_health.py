from alicia.core.health import Health, measure


def test_health_is_measured_and_problems_named():
    health = measure()
    assert health.threads >= 1 and "mémoire" in health.text()
    bad = Health(ram_mb=3000, threads=40, handles=20000, gdi=9000, user=10, captures_open=5)
    problems = bad.problems()
    assert len(problems) == 4 and any("captures" in p for p in problems)
    assert not Health(400, 20, 900, 300, 200, 0).problems()


def test_check_health_cleans_up(qt_app, tmp_path, monkeypatch):
    from alicia.app import build_services
    from alicia.core import health as health_module
    from alicia.core.config import load_settings
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    window = MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    )
    notes = []
    window._notify = notes.append
    try:
        monkeypatch.setattr(health_module, "measure", lambda: Health(3000, 50, captures_open=6))
        window.check_health()
        assert notes and "trop" in notes[0]
        window.check_health()
        assert len(notes) == 1  # prévenu une seule fois
    finally:
        window.close()
