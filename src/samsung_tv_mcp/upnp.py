"""SSDP discovery, UPnP RenderingControl (absolute volume / mute) and DIAL (app launch)."""

from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urljoin
from xml.sax.saxutils import escape

from .legacy import TVError

SSDP_ADDR = ("239.255.255.250", 1900)
RENDERING_CONTROL = "urn:schemas-upnp-org:service:RenderingControl:1"
DIAL_ST = "urn:dial-multiscreen-org:service:dial:1"


def ssdp_search(st: str, host: str, timeout: float = 3.0) -> list[dict[str, str]]:
    """M-SEARCH for `st` and return the response headers sent by `host`."""
    msg = (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_ADDR[0]}:{SSDP_ADDR[1]}\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 2\r\n"
        f"ST: {st}\r\n\r\n"
    ).encode()
    results: list[dict[str, str]] = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(0.5)
        for target in (SSDP_ADDR, (host, 1900)):
            try:
                sock.sendto(msg, target)
            except OSError:
                pass
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, addr = sock.recvfrom(65507)
            except socket.timeout:
                continue
            except OSError:
                break
            if addr[0] != host:
                continue
            headers = parse_http_headers(data.decode("utf-8", "replace"))
            if headers.get("st", "").lower() == st.lower() and headers not in results:
                results.append(headers)
    return results


def parse_http_headers(text: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in text.split("\r\n")[1:]:
        if ":" in line:
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()
    return headers


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def find_control_url(description_xml: str, location: str, service_type: str) -> str | None:
    """Find a service's absolute controlURL in a UPnP device description."""
    root = ET.fromstring(description_xml)
    base = location
    for el in root.iter():
        if _local(el.tag) == "URLBase" and el.text:
            base = el.text.strip()
    for service in root.iter():
        if _local(service.tag) != "service":
            continue
        fields = {_local(c.tag): (c.text or "").strip() for c in service}
        if fields.get("serviceType", "").lower() == service_type.lower() and fields.get("controlURL"):
            return urljoin(base, fields["controlURL"])
    return None


def _http(url: str, method: str = "GET", body: bytes | None = None,
          headers: dict[str, str] | None = None, timeout: float = 5.0) -> tuple[int, dict[str, str], str]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as exc:
        raise TVError(f"HTTP {method} {url} failed: {exc}") from exc


class RenderingControl:
    def __init__(self, host: str, control_url: str | None = None, timeout: float = 5.0):
        self.host = host
        self.control_url = control_url
        self.timeout = timeout

    def _url(self) -> str:
        if self.control_url:
            return self.control_url
        for hit in ssdp_search(RENDERING_CONTROL, self.host):
            location = hit.get("location")
            if not location:
                continue
            _, _, xml = _http(location, timeout=self.timeout)
            url = find_control_url(xml, location, RENDERING_CONTROL)
            if url:
                self.control_url = url
                return url
        raise TVError(
            "The TV did not answer UPnP discovery for volume control. Make sure the TV is on and "
            "'AllShare / DLNA' is enabled, or set SAMSUNG_TV_RENDERING_CONTROL_URL."
        )

    def _call(self, action: str, args: dict[str, str | int]) -> str:
        arg_xml = "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in args.items())
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            f'<u:{action} xmlns:u="{RENDERING_CONTROL}">{arg_xml}</u:{action}>'
            "</s:Body></s:Envelope>"
        ).encode()
        status, _, text = _http(
            self._url(), "POST", body,
            {"Content-Type": 'text/xml; charset="utf-8"', "SOAPACTION": f'"{RENDERING_CONTROL}#{action}"'},
            self.timeout,
        )
        if status != 200:
            self.control_url = None if status == 404 else self.control_url
            raise TVError(f"UPnP {action} failed with HTTP {status}: {text[:200]}")
        return text

    @staticmethod
    def _extract(text: str, name: str) -> str:
        for el in ET.fromstring(text).iter():
            if _local(el.tag) == name:
                return (el.text or "").strip()
        raise TVError(f"No {name} in UPnP response")

    def get_volume(self) -> int:
        return int(self._extract(self._call("GetVolume", {"InstanceID": 0, "Channel": "Master"}), "CurrentVolume"))

    def set_volume(self, level: int) -> None:
        self._call("SetVolume", {"InstanceID": 0, "Channel": "Master", "DesiredVolume": level})

    def get_mute(self) -> bool:
        return self._extract(self._call("GetMute", {"InstanceID": 0, "Channel": "Master"}), "CurrentMute") in {"1", "true"}

    def set_mute(self, mute: bool) -> None:
        self._call("SetMute", {"InstanceID": 0, "Channel": "Master", "DesiredMute": int(mute)})


class Dial:
    """DIAL ("DIscovery And Launch") — what phones use to cast YouTube to the TV."""

    def __init__(self, host: str, app_url: str | None = None, timeout: float = 5.0):
        self.host = host
        self.app_url = app_url
        self.timeout = timeout

    def _base(self) -> str:
        if self.app_url:
            return self.app_url
        for hit in ssdp_search(DIAL_ST, self.host):
            location = hit.get("location")
            if not location:
                continue
            _, headers, _ = _http(location, timeout=self.timeout)
            url = headers.get("application-url")
            if url:
                self.app_url = url
                return url
        raise TVError(
            "The TV did not answer DIAL discovery, so apps cannot be launched directly. Make sure the "
            "TV is on, or set SAMSUNG_TV_DIAL_URL."
        )

    def _app(self, name: str) -> str:
        return self._base().rstrip("/") + "/" + name

    def status(self, name: str) -> str:
        """'running', 'stopped', 'hidden', or 'not available'."""
        code, _, text = _http(self._app(name), timeout=self.timeout)
        if code != 200:
            return "not available"
        try:
            for el in ET.fromstring(text).iter():
                if _local(el.tag) == "state":
                    return (el.text or "unknown").strip()
        except ET.ParseError:
            pass
        return "unknown"

    def launch(self, name: str, params: str = "") -> int:
        code, _, text = _http(
            self._app(name), "POST", params.encode("utf-8"),
            {"Content-Type": "text/plain; charset=utf-8"}, self.timeout,
        )
        if code == 404:
            raise TVError(f"The TV does not offer '{name}' over DIAL (it may not be installed).")
        if code not in (200, 201):
            raise TVError(f"Launching '{name}' failed with HTTP {code}: {text[:200]}")
        return code

    def stop(self, name: str) -> None:
        _http(self._app(name) + "/run", "DELETE", timeout=self.timeout)
