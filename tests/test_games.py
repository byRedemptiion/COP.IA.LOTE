import tomllib

import pytest

from alicia.core.capture.models import WindowInfo
from alicia.games.profiles import load_profiles, resolve_profile
from alicia.games.store import GameDraft, GameStore, normalize_site, slugify


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://www.Icy-Veins.com/wow-forever/?x=1#top", "icy-veins.com/wow-forever"),
        ("method.gg/wow-forever/", "method.gg/wow-forever"),
        ("  warcraft.wiki.gg ", "warcraft.wiki.gg"),
        ("pas un site", ""),
        ("", ""),
    ],
)
def test_sites_are_normalized(text, expected):
    assert normalize_site(text) == expected


def test_slugify_handles_accents():
    assert slugify("Élden Ring : Nightreign") == "elden-ring-nightreign"


def test_store_adds_a_game_and_reads_it_back(tmp_path):
    store = GameStore(tmp_path / "games.toml")
    key = store.save(
        None,
        GameDraft(
            "Elden Ring",
            ["EldenRing.exe"],
            [],
            ["https://eldenring.wiki.fextralife.com/", "eldenring.wiki.fextralife.com"],
            "Souls-like.",
        ),
    )
    assert key == "elden-ring"
    assert not store.is_builtin(key)
    tomllib.loads((tmp_path / "games.toml").read_text("utf-8"))  # fichier valide
    profile = load_profiles(tmp_path / "games.toml")[key]
    assert profile.sources == ("eldenring.wiki.fextralife.com",)  # doublon retiré
    window = WindowInfo(1, "ELDEN RING", 2, exe_name="eldenring.exe")
    assert resolve_profile(window, profiles=store.profiles).key == key
    store.delete(key)
    assert key not in store.profiles


def test_store_edits_then_restores_a_builtin_game(tmp_path):
    store = GameStore(tmp_path / "games.toml")
    draft = GameDraft.from_profile(store.profiles["wow-forever"])
    draft.sources.insert(0, "wowhead.com/forever")
    store.save("wow-forever", draft)
    assert store.is_modified("wow-forever")
    assert store.profiles["wow-forever"].sources[0] == "wowhead.com/forever"
    store.reset("wow-forever")
    assert not store.is_modified("wow-forever")
    assert store.profiles["wow-forever"].sources[0] == "icy-veins.com/wow-forever"


def test_store_refuses_a_game_without_name(tmp_path):
    with pytest.raises(ValueError):
        GameStore(tmp_path / "games.toml").save(None, GameDraft(" ", [], [], [], ""))


def test_games_tab_lists_games_and_edits_sites(qt_app, tmp_path):
    from alicia.ui.games_page import GameCard, GamesPage

    store = GameStore(tmp_path / "games.toml")
    page = GamesPage(store, active_game=lambda: "wow-forever")
    cards = [
        page.grid.itemAt(i).widget()
        for i in range(page.grid.count())
        if isinstance(page.grid.itemAt(i).widget(), GameCard)
    ]
    assert {c.key for c in cards} >= {"overwatch", "wow-forever"}
    changed = []
    page.games_changed.connect(lambda: changed.append(True))

    page.open_game("wow-forever")
    assert page.currentWidget() is page.detail_page
    page.site_input.setText("https://www.wowhead.com/forever/")
    page._add_site()
    assert page.site_list()[-1] == "wowhead.com/forever"
    page.sites.setCurrentRow(page.sites.count() - 1)
    page._move_site(-1)
    assert page.site_list()[-2] == "wowhead.com/forever"
    page.site_input.setText("n'importe quoi")
    page._add_site()
    assert "non reconnue" in page.site_error.text()
    assert page.save() == "wow-forever"
    assert changed and "wowhead.com/forever" in store.profiles["wow-forever"].sources

    page.open_game(None)  # nouveau jeu
    page.name_input.setText("Hades II")
    page.site_input.setText("hades.fandom.com")
    page._add_site()
    assert page.save() == "hades-ii"
    page.show_list()
    assert page.currentWidget() is page.list_page


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (r"C:\Program Files (x86)\World of Warcraft\_retail_\Wow.exe", "wow-retail"),
        (r"C:\Games\World of Warcraft\_classic_era_\WowClassic.exe", "wow-classic"),
        (r"D:\World of Warcraft\_forever_\WowClassic.exe", "wow-forever"),
        ("", "wow-forever"),  # sans chemin : le titre « World of Warcraft » suffit
    ],
)
def test_wow_versions_are_told_apart_by_install_folder(path, expected):
    exe = path.rsplit("\\", 1)[-1] if path else ""
    window = WindowInfo(1, "World of Warcraft", 2, exe_name=exe, exe_path=path)
    assert resolve_profile(window, profiles=load_profiles()).key == expected


def test_duplicate_makes_a_new_version_with_its_own_folder(qt_app, tmp_path):
    from alicia.ui.games_page import GamesPage

    window = WindowInfo(
        1, "World of Warcraft", 2, exe_name="Wow.exe", exe_path=r"E:\WoW\_xptr_\Wow.exe"
    )
    store = GameStore(tmp_path / "games.toml")
    page = GamesPage(store, current_window=lambda: window)
    page.open_game("wow-retail")
    page.duplicate()
    assert page.editing is None and "(copie)" in page.name_input.text()
    page.name_input.setText("WoW PTR perso")
    page._fill_from_window()
    assert page.folder_input.text() == "_xptr_"
    key = page.save()
    assert key == "wow-ptr-perso"
    assert resolve_profile(window, profiles=store.profiles).key == key
    assert store.profiles["wow-retail"].folders  # l'original est intact


def test_builtin_game_can_be_removed_and_brought_back(tmp_path):
    store = GameStore(tmp_path / "games.toml")
    assert "wow-classic" in store.profiles
    store.hide("wow-classic")
    assert "wow-classic" not in store.profiles and store.hidden_keys() == ["wow-classic"]
    assert not store.is_modified("wow-classic")
    reloaded = GameStore(tmp_path / "games.toml")
    assert "wow-classic" not in reloaded.profiles
    reloaded.unhide_all()
    assert "wow-classic" in reloaded.profiles and reloaded.hidden_keys() == []


def test_games_tab_removes_a_game_and_picks_an_exe(qt_app, tmp_path):
    from alicia.ui.games_page import GamesPage

    page = GamesPage(GameStore(tmp_path / "games.toml"))
    page.open_game("wow-classic")
    assert page.delete_button.text() == "Retirer de ma liste"
    page.delete_button.click()
    assert "wow-classic" not in page.store.profiles
    assert page.unhide_button.isVisibleTo(page) and "1 jeu retiré" in page.hidden_label.text()

    page.open_game(None)
    page.add_exe("C:\\Program Files\\Ubisoft\\Tom Clancy's Rainbow Six Siege\\RainbowSix.exe")
    assert page.exe_input.text() == "rainbowsix.exe"
    assert page.folder_input.text() == "tom clancy's rainbow six siege"
    page.name_input.setText("Rainbow Six Siege")
    key = page.save()
    window = WindowInfo(1, "Rainbow Six", 2, exe_name="RainbowSix.exe")
    assert resolve_profile(window, "auto", page.store.profiles).key == key
