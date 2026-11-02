import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Aucun test ne lit le vrai .env, les vraies clés ni le dossier utilisateur."""
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ALICE_AI_PROVIDER", "ALICE_LOG_LEVEL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    monkeypatch.chdir(tmp_path)
    from alicia.core.audio import voice_design

    voice_design.resume_online()  # pause « quota » d'un autre test : oubliée
    monkeypatch.setattr(voice_design, "on_notice", None)
    yield


_QT_APP = None


@pytest.fixture(scope="session")
def qt_app():
    """Une seule QApplication pour toute la session, gardée en vie jusqu'à la fin :
    si elle était détruite avant les fenêtres, Qt plante à la sortie."""
    global _QT_APP
    from PySide6.QtWidgets import QApplication

    _QT_APP = QApplication.instance() or QApplication([])
    yield _QT_APP
    # Détruire toutes les fenêtres pendant que Qt est encore là : sinon le ramasse-miettes
    # de Python les libère après la QApplication et le processus plante à la sortie.
    import gc

    from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool

    QThreadPool.globalInstance().waitForDone(5000)
    for widget in QApplication.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()
    gc.collect()
