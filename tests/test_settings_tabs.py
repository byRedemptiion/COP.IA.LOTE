from alicia.app import build_services
from alicia.core.config import load_settings
from alicia.ui.settings_page import TAB_ALIASES, TABS


def _window(tmp_path, monkeypatch):
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    return MainWindow(
        build_services(load_settings(environ={"ALICE_AI_PROVIDER": "fake"}), demo=True)
    )


def test_new_tabs_and_old_names_still_work(qt_app, tmp_path, monkeypatch):
    window = _window(tmp_path, monkeypatch)
    page = window.settings_page
    try:
        assert [k for k, _ in TABS] == [
            "general",
            "copilot",
            "profile",
            "ai",
            "perception",
            "games",
            "social",
            "stream",
        ]
        for old, new in TAB_ALIASES.items():
            page.show_tab(old)
            assert page.current_tab == new
        # chaque réglage est rangé dans son nouvel onglet
        where = {
            "general": [page.mode_box, page.shortcuts, page.channel_box, page.github_token],
            "copilot": [page.copilot_box, page.copilot_interval],
            "profile": [
                page.persona_box,
                page.player_name,
                page.engine_box,
                page.volume,
                page.effect_box,
                page.anims_folder,
            ],
            "ai": [page.fast_box, page.deep_box, page.ollama_model],
            "perception": [page.vision_box, page.input_box, page.wake_box, page.memory_box],
            "social": [window.people_page, page.duo_box, page.duo_ai],
            "stream": [page.stream_box, page.twitch_input, page.overlay_box],
            "games": [window.games_page],
        }
        for tab, widgets in where.items():
            for widget in widgets:
                assert page.tabs[tab].isAncestorOf(widget), (tab, widget)
    finally:
        window.close()


def test_last_mode_is_remembered(qt_app, tmp_path, monkeypatch):
    import tomllib

    from alicia.core.config import data_dir

    window = _window(tmp_path, monkeypatch)
    window.services.demo = False  # pour enregistrer le dernier mode
    try:
        window.show_panel()
        window.show_orb()
        saved = tomllib.loads((data_dir() / "alicia.toml").read_text("utf-8"))
        assert saved["ui"]["last_mode"] == "orb"
        window.settings_page.mode_box.setCurrentIndex(
            window.settings_page.mode_box.findData("last")
        )
        assert load_settings().ui_mode == "last" and load_settings().ui_last == "orb"
    finally:
        window.services.demo = True
        window.close()
