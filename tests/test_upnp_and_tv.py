import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from samsung_tv_mcp.config import Settings
from samsung_tv_mcp.power import magic_packet
from samsung_tv_mcp.tv import TV, parse_youtube
from samsung_tv_mcp.upnp import Dial, RenderingControl, find_control_url, parse_http_headers

DESCRIPTION = """<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0"><device><serviceList>
<service><serviceType>urn:schemas-upnp-org:service:ConnectionManager:1</serviceType><controlURL>/cm</controlURL></service>
<service><serviceType>urn:schemas-upnp-org:service:RenderingControl:1</serviceType><controlURL>/smp_17_</controlURL></service>
</serviceList></device></root>"""


@pytest.mark.parametrize(
    "value,expected",
    [
        ("dQw4w9WgXcQ", ("dQw4w9WgXcQ", None)),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42", ("dQw4w9WgXcQ", 42)),
        ("youtu.be/dQw4w9WgXcQ?t=1m30s", ("dQw4w9WgXcQ", 90)),
        ("https://m.youtube.com/shorts/dQw4w9WgXcQ", ("dQw4w9WgXcQ", None)),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", ("dQw4w9WgXcQ", None)),
    ],
)
def test_parse_youtube(value, expected):
    assert parse_youtube(value) == expected


def test_parse_youtube_rejects_garbage():
    with pytest.raises(ValueError):
        parse_youtube("https://example.com/watch?v=nope")


def test_find_control_url():
    assert find_control_url(DESCRIPTION, "http://10.0.1.13:7676/smp_15_", "urn:schemas-upnp-org:service:RenderingControl:1") == "http://10.0.1.13:7676/smp_17_"


def test_ssdp_headers():
    h = parse_http_headers("HTTP/1.1 200 OK\r\nLOCATION: http://x/y\r\nST: foo\r\n\r\n")
    assert h == {"location": "http://x/y", "st": "foo"}


def test_magic_packet():
    pkt = magic_packet("aa:bb:cc:dd:ee:ff")
    assert len(pkt) == 102 and pkt[:6] == b"\xff" * 6 and pkt[6:12] == bytes.fromhex("aabbccddeeff")


class FakeTVHttp(BaseHTTPRequestHandler):
    requests = []
    volume = 12

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        FakeTVHttp.requests.append((self.path, self.headers.get("SOAPACTION"), body))
        if self.path == "/apps/YouTube":
            self.send_response(201)
            self.end_headers()
        elif self.path == "/rc":
            action = self.headers["SOAPACTION"].split("#")[1].strip('"')
            if action == "SetVolume":
                FakeTVHttp.volume = int(body.split("<DesiredVolume>")[1].split("<")[0])
                reply = ""
            else:
                reply = f"<CurrentVolume>{FakeTVHttp.volume}</CurrentVolume><CurrentMute>0</CurrentMute>"
            data = f'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body><u:R xmlns:u="x">{reply}</u:R></s:Body></s:Envelope>'.encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        if self.path == "/apps/YouTube":
            data = b'<service xmlns="urn:dial-multiscreen-org:schemas:dial"><name>YouTube</name><state>stopped</state></service>'
            self.send_response(200)
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture
def http_tv():
    server = HTTPServer(("127.0.0.1", 0), FakeTVHttp)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    FakeTVHttp.requests = []
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def _tv(base):
    return TV(Settings(host="127.0.0.1", port=1, mac=None, client_name="t", client_id="t", use_cec=False,
                       timeout=2, rendering_control_url=base + "/rc", dial_url=base + "/apps"))


def test_volume_via_upnp(http_tv):
    rc = RenderingControl("127.0.0.1", http_tv + "/rc")
    rc.set_volume(25)
    assert rc.get_volume() == 25
    assert "RenderingControl:1#SetVolume" in FakeTVHttp.requests[0][1]


def test_play_youtube_via_dial(http_tv):
    assert "dQw4w9WgXcQ" in _tv(http_tv).play_youtube("https://youtu.be/dQw4w9WgXcQ?t=10")
    assert FakeTVHttp.requests[-1] == ("/apps/YouTube", None, "v=dQw4w9WgXcQ&t=10")


def test_dial_status_and_missing_app(http_tv):
    dial = Dial("127.0.0.1", http_tv + "/apps")
    assert dial.status("YouTube") == "stopped"
    assert dial.status("Nope") == "not available"


def test_power_on_without_options_explains():
    tv = _tv("http://127.0.0.1:1")
    assert "network off in standby" in tv.power_on()


class SamsungDialHttp(BaseHTTPRequestHandler):
    """Advertised base is /ws/app/, but apps answer under /ws/apps/; Slow hangs then runs."""

    launched = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path == "/ws/apps/YouTube":
            SamsungDialHttp.launched.append(self.path)
            self.send_response(201)
            self.end_headers()
        elif self.path == "/ws/app/Slow":
            import time
            SamsungDialHttp.launched.append(self.path)
            time.sleep(2)
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        if self.path == "/ws/app/Slow" and SamsungDialHttp.launched:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<service><state>running</state></service>")
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture
def samsung_dial():
    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer(("127.0.0.1", 0), SamsungDialHttp)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    SamsungDialHttp.launched = []
    yield f"http://127.0.0.1:{server.server_port}/ws/app/"
    server.shutdown()


def test_dial_falls_back_to_ws_apps(samsung_dial):
    dial = Dial("127.0.0.1", samsung_dial)
    assert dial.launch("YouTube", "v=dQw4w9WgXcQ").endswith("/ws/apps/YouTube")
    assert len(dial.probe("YouTube")) == 2


def test_dial_launch_timeout_but_running(samsung_dial, monkeypatch):
    dial = Dial("127.0.0.1", samsung_dial, timeout=0.5)
    monkeypatch.setattr(Dial, "LAUNCH_TIMEOUT", 0.5)
    assert dial.launch("Slow").endswith("/ws/app/Slow")
