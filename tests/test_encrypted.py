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


class FakeLibRemote:
    instances = []
    fail_next_send = False

    def __init__(self, host, **kw):
        self.args = (host, kw["token"], kw["session_id"], kw["port"])
        self.keys = []
        self.alive = False
        self.closed = False
        FakeLibRemote.instances.append(self)

    async def start_listening(self):
        self.alive = True

    def is_alive(self):
        return self.alive

    async def send_commands(self, commands, key_press_delay=None):
        if FakeLibRemote.fail_next_send:
            FakeLibRemote.fail_next_send = False
            self.alive = False
            raise ConnectionError("dropped")
        self.keys += [c.body["param3"] for c in commands]

    async def close(self):
        self.closed = True
        self.alive = False


@pytest.fixture
def fake_lib(monkeypatch):
    from samsungtvws.encrypted.remote import SendRemoteKey
    import aiohttp

    FakeLibRemote.instances = []
    FakeLibRemote.fail_next_send = False
    monkeypatch.setattr(encrypted, "_imports", lambda: (aiohttp, None, FakeLibRemote, SendRemoteKey))
    save_credentials("127.0.0.1", "00" * 16, "7")
    return FakeLibRemote


def test_send_keys_reuses_one_connection(fake_lib):
    remote = EncryptedRemote("127.0.0.1", port=1234)
    assert remote.send_keys(["mute", "KEY_VOLUP"], 0) == ["KEY_MUTE", "KEY_VOLUP"]
    remote.send_keys(["KEY_UP"], 0)
    remote.send_keys(["KEY_DOWN"], 0)
    assert len(fake_lib.instances) == 1
    conn = fake_lib.instances[0]
    assert conn.args == ("127.0.0.1", "00" * 16, "7", 1234)
    assert conn.keys == ["KEY_MUTE", "KEY_VOLUP", "KEY_UP", "KEY_DOWN"]
    assert remote.is_reachable()


def test_reconnects_when_tv_drops_the_session(fake_lib):
    remote = EncryptedRemote("127.0.0.1", port=1234)
    remote.send_keys(["KEY_UP"], 0)
    fake_lib.fail_next_send = True
    remote.send_keys(["KEY_DOWN"], 0)
    assert len(fake_lib.instances) == 2
    assert fake_lib.instances[0].closed
    assert fake_lib.instances[1].keys == ["KEY_DOWN"]


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


def test_reconnects_after_idle(fake_lib, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(encrypted.time, "monotonic", lambda: clock[0])
    remote = EncryptedRemote("127.0.0.1", port=1234)
    remote.send_keys(["KEY_UP"], 0)
    clock[0] += 10
    remote.send_keys(["KEY_UP"], 0)
    assert len(fake_lib.instances) == 1
    clock[0] += 100
    remote.send_keys(["KEY_UP"], 0)
    assert len(fake_lib.instances) == 2


def test_close_shuts_the_kept_connection(fake_lib):
    remote = EncryptedRemote("127.0.0.1", port=1234)
    remote.send_keys(["KEY_UP"], 0)
    remote.close()
    assert fake_lib.instances[0].closed and remote._remote is None
