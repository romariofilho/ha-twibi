"""Testes do codec/cliente contra respostas gravadas do Twibi Giga real (fw 1.1.9).

Roda sem HA: python3 -m unittest discover -s tests -v
"""
import asyncio
import json
import os
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "custom_components", "twibi"))

from lib import client as C  # noqa: E402
from lib.codec import decode, encode  # noqa: E402

FIX = os.path.join(HERE, "fixtures")


def fixture(name: str) -> bytes:
    with open(os.path.join(FIX, f"{name}.bin"), "rb") as f:
        return f.read()


def expected(name: str):
    with open(os.path.join(FIX, f"{name}.json")) as f:
        return json.load(f)


def strip_status(raw: bytes, msg: str):
    for cand in (raw, raw[4:]):
        try:
            return decode(msg, cand)
        except Exception:
            continue
    raise AssertionError("nao decodificou")


class TestDecodeFixtures(unittest.TestCase):
    """Cada resposta gravada decodifica igual ao JSON de referencia."""

    def check(self, name, req, msg=None):
        msg = msg or C.RESPONSE_MSG[req]
        raw = fixture(name)
        got = decode(msg, raw) if req < 0x1000 else strip_status(raw, msg)
        self.assertEqual(json.loads(json.dumps(got, default=lambda b: b.hex())), expected(name))
        return got

    def test_basic_info(self):
        got = self.check("basic_info", C.REQ_BASIC_INFO, "UcMSystem.proto_sys_common_ack")
        self.assertEqual(got["basic"]["sn"], "TWIBISN000001")

    def test_nodes(self):
        nodes = self.check("nodes", C.REQ_NODES)["node"]
        self.assertEqual({n["role"] for n in nodes}, {0, 1})
        self.assertTrue(all(n["serialNum"] for n in nodes))

    def test_hosts(self):
        hosts = self.check("hosts", C.REQ_HOSTS)["hosts"]
        self.assertGreater(len(hosts), 30)
        self.assertTrue(any(h.get("dhcp_static") for h in hosts))
        for h in hosts:
            self.assertRegex(h["ethaddr"], r"^[0-9A-F:]{17}$")

    def test_remarks(self):
        marks = self.check("remarks", C.REQ_REMARKS)["marks"]
        self.assertTrue(any(m["remark"] == "aparelho26_aparelho" for m in marks))

    def test_others(self):
        for name, req in (("wan_status", C.REQ_WAN_STATUS), ("wan_cfg", C.REQ_WAN_CFG), ("wan_line", C.REQ_WAN_LINE),
                          ("wan_rate", C.REQ_WAN_RATE), ("wlan", C.REQ_WLAN), ("guest", C.REQ_GUEST),
                          ("macfilter", C.REQ_MACFILTER), ("automaint", C.REQ_AUTOMAINT), ("dhcp", C.REQ_DHCP),
                          ("roaming", C.REQ_ROAMING), ("mesh_priority", C.REQ_MESH_PRIORITY)):
            with self.subTest(name=name):
                self.check(name, req)


class TestEncode(unittest.TestCase):
    def test_static_ip_matches_app_capture(self):
        # bytes exatos que o app enviou ao reservar a TV Sala (captura 2026-10-16)
        app = bytes.fromhex("0a0931302e312e312e3839121130323a30303a30303a30303a30303a34381a0931302e312e312e38392001")
        mine = encode("Onhosts.StaticIpInfo", {"ipaddr": "10.1.1.89", "ethaddr": "02:00:00:00:00:48",
                                               "dhcp_static": "10.1.1.89", "enable": 1})
        self.assertTrue(mine.startswith(app))

    def test_login(self):
        self.assertEqual(encode("Device.LoginMsg", {"account": "admin", "qrmsg": ""}).hex(), "0a0561646d696e1200")

    def test_roundtrip(self):
        data = {"mode": 0, "rules": [{"ethaddr": "AA:BB:CC:DD:EE:FF", "name": "x"}], "timestamp": 123}
        self.assertEqual(decode("Macfilter.mf_lists", encode("Macfilter.mf_lists", data)), data)

    def test_negative_int(self):
        data = {"band": 0, "ssid": "a", "left": -1, "timeout": -1}
        self.assertEqual(decode("Wlan.WlanCfg", encode("Wlan.WlanCfg", data))["left"], -1)


class FakeTwibi:
    """Servidor TCP falso que responde com as fixtures (testa o framing do cliente)."""

    def __init__(self, password="segredo"):
        self.password = password
        self.received = []

    async def handle(self, reader, writer):
        try:
            while True:
                hdr = await reader.readexactly(16)
                _v, _ce, src, mid, mt, blen, rt, _rc, _p = struct.unpack(">BBBBHHHHI", hdr)
                body = await reader.readexactly(blen) if blen else b""
                self.received.append((src, rt, body))
                if rt == C.REQ_LOGIN:
                    ok = decode("Device.LoginMsg", body).get("qrmsg") == self.password
                    resp = struct.pack("<i", 0 if ok else -1)
                else:
                    names = {v: k for k, v in {
                        "basic_info": C.REQ_BASIC_INFO, "nodes": C.REQ_NODES, "hosts": C.REQ_HOSTS,
                        "remarks": C.REQ_REMARKS, "guest": C.REQ_GUEST, "macfilter": C.REQ_MACFILTER,
                        "automaint": C.REQ_AUTOMAINT, "roaming": C.REQ_ROAMING,
                        "mesh_priority": C.REQ_MESH_PRIORITY}.items()}
                    if rt in names:
                        # fixtures foram gravadas sem o prefixo de status (comandos mesh 0x1xxx)
                        resp = fixture(names[rt]) if rt < 0x1000 else struct.pack("<i", 0) + fixture(names[rt])
                    else:
                        resp = struct.pack("<i", 0)
                # resposta "atrasada" de outro id antes da certa: o cliente deve ignorar
                junk = struct.pack(">BBBBHHHHI", 0x24, 0, 6, (mid + 50) & 0xFF, 213, 4, 0x9999, 0, 0) + b"\0" * 4
                out = struct.pack(">BBBBHHHHI", 0x24, 0, 6, mid, 213, len(resp), rt, 0, 0) + resp
                writer.write(junk + out)
                await writer.drain()
        except asyncio.IncompleteReadError:
            writer.close()


class TestClient(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fake = FakeTwibi()
        self.server = await asyncio.start_server(self.fake.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()

    async def test_login_and_reads(self):
        async with C.TwibiClient("127.0.0.1", "segredo", port=self.port) as t:
            self.assertEqual((await t.basic_info())["sn"], "TWIBISN000001")
            self.assertGreater(len(await t.hosts()), 30)
            self.assertIn("02:00:00:00:00:65", await t.remarks())
        self.assertEqual(self.fake.received[0][0], 7)  # origem = app (7)

    async def test_bad_password(self):
        with self.assertRaises(C.TwibiAuthError):
            async with C.TwibiClient("127.0.0.1", "errada", port=self.port):
                pass

    async def test_factory_reset_blocked(self):
        async with C.TwibiClient("127.0.0.1", "segredo", port=self.port) as t:
            with self.assertRaises(C.TwibiError):
                await t.request(C.REQ_FACTORY_RESET)
        self.assertNotIn(C.REQ_FACTORY_RESET, [r[1] for r in self.fake.received])

    async def test_write_has_timestamp_prefix(self):
        async with C.TwibiClient("127.0.0.1", "segredo", port=self.port) as t:
            await t.set_remarks({"aa:bb:cc:dd:ee:ff": "Teste"})
        src, rt, body = self.fake.received[-1]
        self.assertEqual(rt, C.REQ_SET_REMARKS)
        ts = struct.unpack("<Q", body[:8])[0]
        dec = decode("Onhosts.DeviceMarkList", body[8:])
        self.assertEqual(dec["timestamp"], ts)
        self.assertEqual(dec["marks"], [{"ethaddr": "AA:BB:CC:DD:EE:FF", "remark": "Teste"}])

    async def test_block_keeps_other_rules(self):
        async with C.TwibiClient("127.0.0.1", "segredo", port=self.port) as t:
            await t.set_blocked("11:22:33:44:55:66", True, "X")
        dec = decode("Macfilter.mf_lists", self.fake.received[-1][2][8:])
        self.assertEqual(dec["mode"], 0)
        self.assertEqual(dec["rules"], [{"ethaddr": "11:22:33:44:55:66", "name": "X"}])

    async def test_roaming(self):
        async with C.TwibiClient("127.0.0.1", "segredo", port=self.port) as t:
            self.assertTrue((await t.roaming())["enable"])
            await t.set_roaming(False)
        src, rt, body = self.fake.received[-1]
        self.assertEqual(rt, C.REQ_SET_ROAMING)
        dec = decode("Wlan.WlanRoaming", body[8:])
        self.assertEqual(dec, {"enable": False, "timestamp": struct.unpack("<Q", body[:8])[0]})

    async def test_mesh_priority(self):
        async with C.TwibiClient("127.0.0.1", "segredo", port=self.port) as t:
            self.assertTrue((await t.mesh_priority())["limit_5Gdevice_switch"])
            await t.set_mesh_priority(False)
        src, rt, body = self.fake.received[-1]
        self.assertEqual(rt, C.REQ_SET_MESH_PRIORITY)
        dec = decode("Wlan.DeviceSet", body[8:])
        self.assertEqual(dec, {"limit_5Gdevice_switch": False, "timestamp": struct.unpack("<Q", body[:8])[0]})


if __name__ == "__main__":
    unittest.main()
