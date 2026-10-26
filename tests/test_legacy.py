import base64
import socket
import struct
import threading

import pytest

from samsung_tv_mcp.legacy import (
    AUTH_DENIED,
    AUTH_GRANTED,
    AuthDenied,
    LegacyRemote,
    TVUnreachable,
    build_auth_packet,
    build_key_packet,
    normalize_key,
    read_message,
)


def _frame(app: bytes, payload: bytes) -> bytes:
    return b"\x00" + struct.pack("<H", len(app)) + app + struct.pack("<H", len(payload)) + payload


def _parse_fields(payload: bytes, offset: int) -> list[bytes]:
    out = []
    while offset < len(payload):
        (n,) = struct.unpack_from("<H", payload, offset)
        out.append(base64.b64decode(payload[offset + 2 : offset + 2 + n]))
        offset += 2 + n
    return out


class FakeTV:
    """Speaks just enough of the port-55 protocol to record what the client sends."""

    def __init__(self, auth_reply=AUTH_GRANTED, pending_first=False):
        self.auth_reply = auth_reply
        self.pending_first = pending_first
        self.server = socket.create_server(("127.0.0.1", 0))
        self.port = self.server.getsockname()[1]
        self.auth = None
        self.keys = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        conn, _ = self.server.accept()
        with conn:
            self.auth = _parse_fields(read_message(conn), 2)
            if self.pending_first:
                conn.sendall(_frame(b"iapp.samsung", b"\x0a\x00\x02\x00\x00\x00"))
            conn.sendall(_frame(b"iapp.samsung", self.auth_reply))
            try:
                while True:
                    self.keys.append(_parse_fields(read_message(conn), 3)[0].decode())
                    conn.sendall(_frame(b"iapp.samsung", b"\x00\x04\x00\x00\x00\x00"))
            except Exception:
                pass


def test_packet_framing():
    pkt = build_key_packet("KEY_MUTE")
    assert pkt[0] == 0
    (app_len,) = struct.unpack_from("<H", pkt, 1)
    payload = pkt[3 + app_len + 2 :]
    assert struct.unpack_from("<H", pkt, 3 + app_len)[0] == len(payload)
    assert _parse_fields(payload, 3) == [b"KEY_MUTE"]

    auth = build_auth_packet("10.0.1.5", "aa-bb", "Claude")
    (app_len,) = struct.unpack_from("<H", auth, 1)
    assert _parse_fields(auth[3 + app_len + 2 :], 2) == [b"10.0.1.5", b"aa-bb", b"Claude"]


def test_normalize_key():
    assert normalize_key("mute") == "KEY_MUTE"
    assert normalize_key("KEY_VOLUP") == "KEY_VOLUP"
    with pytest.raises(ValueError):
        normalize_key("KEY_; rm -rf")


@pytest.mark.parametrize("pending", [False, True])
def test_send_keys_after_auth(pending):
    tv = FakeTV(pending_first=pending)
    remote = LegacyRemote("127.0.0.1", "id-1", "Claude Test", port=tv.port, timeout=2)
    assert remote.send_keys(["volup", "KEY_VOLDOWN"], delay=0) == ["KEY_VOLUP", "KEY_VOLDOWN"]
    assert tv.auth[1:] == [b"id-1", b"Claude Test"]
    for _ in range(50):
        if len(tv.keys) == 2:
            break
        threading.Event().wait(0.02)
    assert tv.keys == ["KEY_VOLUP", "KEY_VOLDOWN"]


def test_auth_denied():
    tv = FakeTV(auth_reply=AUTH_DENIED)
    with pytest.raises(AuthDenied):
        LegacyRemote("127.0.0.1", "x", "y", port=tv.port, timeout=2).send_key("KEY_MUTE")


def test_unreachable():
    s = socket.create_server(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    remote = LegacyRemote("127.0.0.1", "x", "y", port=port, timeout=1)
    assert not remote.is_reachable()
    with pytest.raises(TVUnreachable):
        remote.send_key("KEY_MUTE")
