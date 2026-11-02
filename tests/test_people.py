from alicia.app import build_services
from alicia.core import people
from alicia.core.ai.prompts import build_system_prompt
from alicia.core.ai.providers.fake import FakeModel
from alicia.core.config import data_dir, load_settings
from alicia.core.persona import pronounce


def test_one_person_many_names(tmp_path):
    store = people.PeopleStore(tmp_path / "p.json")
    yann = store.upsert(
        people.Person(
            first_name="Yannick",
            nickname="Nova",
            aliases=["NovaJagger", "Yann"],
            pronunciations={"Yannick": "Ya-nik"},
        )
    )
    assert store.find("nova") is yann and store.find("NovaJager") is yann
    assert store.find("Yann") is yann and store.find("Paul") is None
    reloaded = people.PeopleStore(tmp_path / "p.json")
    assert len(reloaded.people) == 1 and reloaded.people[0].id == yann.id
    assert pronounce("Salut Yannick") == "Salut Ya-nik"
    reloaded.remove(yann.id)
    assert people.PeopleStore(tmp_path / "p.json").people == []


def test_present_people_reach_the_prompt(tmp_path):
    store = people.PeopleStore(tmp_path / "p.json")
    store.upsert(people.Person(first_name="Yannick", nickname="Nova", present=True))
    store.upsert(people.Person(first_name="Paul", present=False))
    people.set_store(store)
    try:
        prompt = build_system_prompt("")
        assert "Yannick / Nova" in prompt and "Paul" not in prompt
        assert people.canonical_names("dis a nova de venir") == "dis a Nova de venir"
        store.people[0].aliases = ["NovaJagger"]
        assert "NovaJagger" in people.canonical_names("dis a nova jager de venir")
    finally:
        people.set_store(None)


def test_people_tab_add_edit_present_delete(qt_app, tmp_path, monkeypatch):
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    settings = load_settings(environ={"ALICE_AI_PROVIDER": "fake"})
    window = MainWindow(build_services(settings, demo=True, model=FakeModel()))
    try:
        window.settings_page.show_tab("people")
        page = window.people_page
        assert window.settings_page.stack.currentWidget().isAncestorOf(page)
        page.new_person()
        page.first_name.setText("Yannick")
        page.nickname.setText("Nova")
        page.aliases.setText("NovaJagger, Yann")
        page.pronunciations.setPlainText("Yannick = Ya-nik\nligne sans égal")
        page.present.setChecked(True)
        person = page.save_person()
        assert person is not None and person.pronunciations == {"Yannick": "Ya-nik"}
        assert (data_dir() / "personnes.json").exists()
        assert page.list.count() == 1 and "Nova" in people.known_names()
        assert "Yannick / Nova" in people.people_context()

        from PySide6.QtCore import Qt

        page.list.item(0).setCheckState(Qt.CheckState.Unchecked)
        assert not window.people.people[0].present and people.people_context() == ""

        page.new_person()
        assert page.save_person() is None  # pas de nom : refusé

        page.show_person(window.people.people[0])
        page.delete_person()
        assert page.list.count() == 0 and window.people.people == []

        window._learn_peer_player({"player": "Nova"})  # le pote du duo devient présent
        assert window.people.find("Nova").present and page.list.count() == 1
    finally:
        window.close()
        people.set_store(None)
