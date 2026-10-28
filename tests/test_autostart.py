import pytest

from samsung_tv_mcp import autostart


def test_install_writes_a_hidden_startup_script_and_off_removes_it(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("SAMSUNG_TV_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(autostart.shutil, "which", lambda name: r"C:\Users\b\.local\bin\uvx.exe")
    path = autostart.install(start_now=False)
    assert path.parent == tmp_path / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    text = path.read_text()
    assert ', 0, False' in text  # hidden, don't wait
    assert '""C:\\Users\\b\\.local\\bin\\uvx.exe"" --from git+https://github.com/joelmaserow-ux/TV@' in text
    assert "samsung-tv remote --port 8765" in text and "remote.log" in text
    assert "--refresh --from" in text and "for /l %i in (0,0,1)" in text  # newest version, kept running
    assert autostart.uninstall() is True and not path.exists()
    assert autostart.uninstall() is False


def test_needs_windows(monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    with pytest.raises(ValueError):
        autostart.startup_folder()
