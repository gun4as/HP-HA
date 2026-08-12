"""Shared test machinery.

Two things happen here. The HA-free modules are imported straight from their
files, because `custom_components/netviz/__init__.py` pulls in all of Home
Assistant and the point of `snmp.py` is that it does not need it. And the
recorded snapshots are wrapped so a real `SnmpClient` can run against them with
only its two network primitives replaced - everything above `walk()` and
`get_many()` is the production code path.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NETVIZ = ROOT / "custom_components" / "netviz"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"netviz_{name}", NETVIZ / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    # dataclasses look their own module up in sys.modules while the class body
    # executes, so it has to be registered before exec_module
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# profiles first, and registered under the bare name too: snmp.py falls back to
# `import profiles` when it is not inside a package, and loading it twice would
# give the tests a different Profile object than the client holds.
profiles = _load("profiles")
sys.modules["profiles"] = profiles
snmp = _load("snmp")
model = _load("model")


class Snapshot:
    """A recorded device, addressed the way SnmpClient addresses a real one."""

    def __init__(self, path: Path) -> None:
        self.name = path.stem
        self.data = json.loads(path.read_text(encoding="utf-8"))
        self._b64 = set(self.data.get("walks_raw_b64", []))
        self.gap = float(self.data.get("counter_gap_seconds", 8.0))

    def walk(self, base: str, second: bool = False) -> dict:
        table = self.data["walks"].get(base, {})
        if second:
            table = self.data.get("counters_t1", {}).get(base, table)
        if base in self._b64:
            return {k: base64.b64decode(v) for k, v in table.items()}
        return dict(table)

    def get(self, oids: list[str]) -> dict:
        out = {}
        for oid in oids:
            rec = self.data.get("get", {}).get(oid)
            if rec and rec.get("value") is not None:
                out[oid] = rec["value"]
        return out

    def physical_ports(self) -> list[dict]:
        """Ports discovered by ifType=6, which is how any vendor can be read."""
        types = self.walk("1.3.6.1.2.1.2.2.1.3")
        names = self.walk("1.3.6.1.2.1.31.1.1.1.1")
        out = []
        for index in sorted((i for i, t in types.items() if t == "6"), key=int):
            out.append({
                "id": names.get(index, index),
                "ifname": names.get(index, index),
                "ifindex": int(index),
            })
        return out


class _StubEngine:
    def close_dispatcher(self) -> None:
        pass


class FixtureClient(snmp.SnmpClient):
    """Real SnmpClient, fake wire."""

    def __init__(self, snapshot: Snapshot) -> None:
        super().__init__(snmp.SnmpCredentials(host="192.0.2.10"))
        self.snapshot = snapshot
        self.second_sample = False
        self.walked: list[str] = []

    async def walk(self, base: str, raw_bytes: bool = False) -> dict:
        self.walked.append(base)
        return self.snapshot.walk(base, second=self.second_sample)

    async def get_many(self, oids: list[str]) -> dict:
        return self.snapshot.get(oids)

    def advance(self, seconds: float) -> None:
        """Rewind the previous sample so the next poll sees `seconds` of gap."""
        if self._prev is not None:
            self._prev.ts -= seconds
        self.second_sample = True


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No test may open a socket. Both are replaced before any client is built."""
    monkeypatch.setattr(snmp, "SnmpEngine", _StubEngine)
    monkeypatch.setattr(snmp, "_auth_data", lambda creds: object())


@pytest.fixture
def aruba() -> Snapshot:
    """Aruba 2540-48G-PoE+-4SFP+: 52 ports, six PoE loads, eight VLANs."""
    return Snapshot(FIXTURES / "jl357a.json")


@pytest.fixture
def rb2011() -> Snapshot:
    """MikroTik RB2011: 11 ports, empty Q-BRIDGE, a bogus entPhysicalSerialNum."""
    return Snapshot(FIXTURES / "rb2011.json")


@pytest.fixture
def crs309() -> Snapshot:
    """MikroTik CRS309-1G-8S+: a switch, all SFP+, no PoE, no radios."""
    return Snapshot(FIXTURES / "crs309.json")


@pytest.fixture
def rb951() -> Snapshot:
    """MikroTik RB951G: a standalone AP, radio up, one client registered."""
    return Snapshot(FIXTURES / "rb951.json")


@pytest.fixture
def capsman() -> Snapshot:
    """MikroTik hAP ac3 acting as CAPsMAN controller: 48 client registrations."""
    return Snapshot(FIXTURES / "capsman.json")


@pytest.fixture
def capac() -> Snapshot:
    """MikroTik cAP ac provisioned by a controller.

    Six radio interfaces up, but only two rows in mtxrWlAp and both describing
    the local configuration nobody is served by: default SSID, zero clients.
    Its real clients are on the controller, under interfaces named after this
    access point. The device that made netviz stop reporting a managed radio's
    client count as zero.
    """
    return Snapshot(FIXTURES / "capac.json")
