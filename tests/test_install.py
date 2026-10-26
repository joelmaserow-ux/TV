import json

import pytest

from samsung_tv_mcp import install


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    path = tmp_path / "Claude" / "claude_desktop_config.json"
    monkeypatch.setattr(install, "config_candidates", lambda: [path])
    return path


def test_creates_new_config(cfg):
    install.install("192.168.1.106")
    data = json.loads(cfg.read_text())
    assert data["mcpServers"]["samsung-tv"]["env"] == {"SAMSUNG_TV_HOST": "192.168.1.106"}
    assert data["mcpServers"]["samsung-tv"]["args"][-1] == "samsung-tv-mcp"


def test_keeps_existing_settings_and_backs_up(cfg):
    cfg.parent.mkdir()
    original = {"preferences": {"x": True}, "mcpServers": {"other": {"command": "foo"}}}
    cfg.write_text("﻿" + json.dumps(original), encoding="utf-8")
    install.install("192.168.1.106")
    data = json.loads(cfg.read_text())
    assert data["preferences"] == {"x": True}
    assert data["mcpServers"]["other"] == {"command": "foo"}
    assert "samsung-tv" in data["mcpServers"]
    assert json.loads(cfg.with_name(cfg.name + ".backup").read_text(encoding="utf-8-sig")) == original


def test_refuses_broken_json(cfg):
    cfg.parent.mkdir()
    cfg.write_text("{ not json")
    with pytest.raises(ValueError, match="isn't valid JSON"):
        install.install("192.168.1.106")
    assert cfg.read_text() == "{ not json"
