import socket

import pytest

from samsung_tv_mcp import encrypted
from samsung_tv_mcp.config import Settings
from samsung_tv_mcp.encrypted import EncryptedRemote, load_credentials, save_credentials
from samsung_tv_mcp.legacy import AuthPending
from samsung_tv_mcp.tv import TV


@pytest.fixture(autouse=True)
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMSUNG_TV_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("SAMSUNG_TV_TOKEN", raising=False)
    monkeypatch.delenv("SAMSUNG_TV_SESSION_ID", raising=False)


def test_credentials_roundtrip():
    assert load_credentials("1.2.3.4") is None
    save_credentials("1.2.3.4", "00ff", "1")
    assert load_credentials("1.2.3.4") == ("00ff", "1")


def test_unpaired_send_explains_pairing():
    with pytest.raises(AuthPending, match="samsung-tv pair"):
        EncryptedRemote("127.0.0.1", port=1).send_key("KEY_MUTE")


def test_send_keys_uses_library(monkeypatch):
    sent = {}

    class FakeRemote:
        def __init__(self, host, **kw):
            sent["init"] = (host, kw["token"], kw["session_id"], kw["port"])

        async def start_listening(self):
            pass

        async def send_commands(self, commands):
            sent["keys"] = [c.body["param3"] for c in commands]

        async def close(self):
            sent["closed"] = True

    from samsungtvws.encrypted.remote import SendRemoteKey
    import aiohttp

    monkeypatch.setattr(encrypted, "_imports", lambda: (aiohttp, None, FakeRemote, SendRemoteKey))
    server = socket.create_server(("127.0.0.1", 0))
    port = server.getsockname()[1]
    save_credentials("127.0.0.1", "00" * 16, "7")
    try:
        assert EncryptedRemote("127.0.0.1", port=port).send_keys(["mute", "KEY_VOLUP"], 0) == ["KEY_MUTE", "KEY_VOLUP"]
    finally:
        server.close()
    assert sent == {"init": ("127.0.0.1", "00" * 16, "7", port), "keys": ["KEY_MUTE", "KEY_VOLUP"], "closed": True}


def test_library_encrypts_commands():
    from samsungtvws.encrypted.remote import SendRemoteKey
    from samsungtvws.encrypted.session import SamsungTVEncryptedSession

    payload = SamsungTVEncryptedSession("00" * 16, "7").encrypt_command(SendRemoteKey.click("KEY_MUTE"))
    assert payload.startswith('5::/com.samsung.companion:{"name":"callCommon","args":[{"Session_Id":7,')


def _settings(**kw):
    base = dict(host="127.0.0.1", port=1, mac=None, client_name="t", client_id="t", use_cec=False,
                timeout=1, rendering_control_url=None, dial_url=None)
    return Settings(**{**base, **kw})


def test_remote_selection():
    tv = TV(_settings())
    assert tv.remote is tv.legacy  # nothing reachable, not paired
    save_credentials("127.0.0.1", "00" * 16, "1")
    assert tv.remote is tv.encrypted
    assert TV(_settings(method="legacy")).remote.__class__.__name__ == "LegacyRemote"


def test_pin_validation():
    with pytest.raises(ValueError):
        encrypted.EncryptedPairing("127.0.0.1").finish("12a4")
