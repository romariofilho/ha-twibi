"""Cliente assincrono do protocolo local do Twibi Giga (Tenda Nova), TCP 9000.

Engenharia reversa do app Wi-Fi Control Home 1.0.7.3 + captura do trafego real.
Sem criptografia na LAN. Uma conexao por "sessao" (login a cada conexao).

Header (16 bytes, big-endian):
  [0x24][compress<<4|encrypt][origem: app=7, roteador=6][id]
  [msgType u16 = 213][bodyLen u16][reqType u16][respCode u16][pad u32]
Corpo: protobuf. Mensagens com campo `timestamp` levam antes 8 bytes LE com o ms.
Resposta: status int32 LE (0 ok, -1 falha) + protobuf (as vezes + 4 bytes de padding).
"""
from __future__ import annotations

import asyncio
import logging
import struct
import time
import zlib
from typing import Any

from .codec import DecodeError, decode, encode

_LOGGER = logging.getLogger(__name__)

PORT = 9000
DIRECT_INFO = 213
SRC_APP = 7

# reqType -> (descricao, mensagem da resposta)
REQ_BASIC_INFO = 0x0100
REQ_LOGIN = 0x1801
REQ_NODES = 0x1100
REQ_REBOOT = 0x0103          # reinicia o sistema mesh inteiro
REQ_FACTORY_RESET = 0x0102   # NUNCA enviar -- bloqueado em _request()
REQ_NODE_LED = 0x1104        # Node.NodeLedStatus {serialNum, lev 0/1}
REQ_HOSTS = 0x1400
REQ_SET_REMARKS = 0x1401
REQ_REMARKS = 0x1402
REQ_STATIC_IP = 0x1404
REQ_WAN_STATUS = 0x1200
REQ_WAN_CFG = 0x1202
REQ_WAN_LINE = 0x1207
REQ_WAN_RATE = 0x1208
REQ_WLAN = 0x1301
REQ_SET_GUEST = 0x1302
REQ_GUEST = 0x1303
REQ_MACFILTER = 0x1500
REQ_SET_MACFILTER = 0x1501
REQ_AUTOMAINT = 0x1704
REQ_SET_AUTOMAINT = 0x1705
REQ_DHCP = 0x1706

RESPONSE_MSG = {
    REQ_NODES: "Node.MeshNodeList",
    REQ_HOSTS: "Onhosts.hostLists",
    REQ_REMARKS: "Onhosts.DeviceMarkList",
    REQ_WAN_STATUS: "Wan.WanStatus",
    REQ_WAN_CFG: "Wan.WanCfg",
    REQ_WAN_LINE: "Wan.WanPortPower",
    REQ_WAN_RATE: "Wan.WanRate",
    REQ_WLAN: "Wlan.WlanCfgAll",
    REQ_GUEST: "Wlan.WlanCfgAll",
    REQ_MACFILTER: "Macfilter.mf_lists",
    REQ_AUTOMAINT: "Advance.AutoMaint",
    REQ_DHCP: "Advance.DhcpCfg",
}


class TwibiError(Exception):
    """Erro generico de comunicacao com o Twibi."""


class TwibiAuthError(TwibiError):
    """Senha de admin recusada."""


class TwibiCommandError(TwibiError):
    """O Twibi respondeu com status de falha."""


def _ts() -> int:
    return int(time.time() * 1000)


class TwibiClient:
    """Uma sessao autenticada com o Twibi principal."""

    def __init__(self, host: str, password: str, port: int = PORT, timeout: float = 10.0) -> None:
        self.host = host
        self.port = port
        self._password = password
        self._timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._mid = 0x80
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "TwibiClient":
        await self.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def connect(self) -> None:
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), self._timeout
            )
        except (OSError, asyncio.TimeoutError) as err:
            raise TwibiError(f"sem conexao com {self.host}:{self.port}: {err}") from err
        login = encode("Device.LoginMsg", {"account": "admin", "qrmsg": self._password})
        status, _ = await self._request(REQ_LOGIN, login)
        if status != 0:
            await self.close()
            raise TwibiAuthError("senha de admin recusada pelo Twibi")

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except OSError:
                pass
        self._reader = self._writer = None

    async def _recv(self) -> tuple[dict[str, int], bytes]:
        assert self._reader is not None
        raw = await asyncio.wait_for(self._reader.readexactly(16), self._timeout)
        _v, ce, _src, mid, _mt, blen, rtype, rcode, _pad = struct.unpack(">BBBBHHHHI", raw)
        body = await asyncio.wait_for(self._reader.readexactly(blen), self._timeout) if blen else b""
        if ce >> 4:
            body = zlib.decompress(body)
        return {"id": mid, "req_type": rtype, "resp": rcode}, body

    async def _request(self, req_type: int, body: bytes = b"") -> tuple[int, bytes]:
        if req_type == REQ_FACTORY_RESET:
            raise TwibiError("reset de fabrica bloqueado nesta biblioteca")
        if self._writer is None:
            raise TwibiError("nao conectado")
        self._mid = self._mid + 1 if self._mid < 0xFF else 0x80
        hdr = struct.pack(">BBBBHHHHI", 0x24, 0, SRC_APP, self._mid, DIRECT_INFO, len(body), req_type, 0, 0)
        try:
            self._writer.write(hdr + body)
            await self._writer.drain()
            while True:  # descarta respostas/pushes de outros ids
                h, data = await self._recv()
                if h["id"] == self._mid and h["req_type"] == req_type:
                    break
        except (OSError, asyncio.IncompleteReadError, asyncio.TimeoutError) as err:
            await self.close()
            raise TwibiError(f"falha no comando 0x{req_type:04x}: {err!r}") from err
        if req_type < 0x1000:
            # comandos "legados" (mensagens UcM*): sem prefixo, err_code vai no protobuf
            return 0, data
        status = struct.unpack("<i", data[:4])[0] if len(data) >= 4 else 0
        return status, data[4:]

    async def request(self, req_type: int, body: bytes = b"", msg: str | None = None) -> Any:
        """Envia um comando e devolve a resposta decodificada (ou bytes crus)."""
        async with self._lock:
            status, payload = await self._request(req_type, body)
        if status != 0:
            raise TwibiCommandError(f"Twibi recusou 0x{req_type:04x} (status {status})")
        msg = msg or RESPONSE_MSG.get(req_type)
        if not msg:
            return payload
        for cand in (payload, payload[4:]):
            try:
                return decode(msg, cand)
            except DecodeError:
                continue
        raise TwibiError(f"resposta de 0x{req_type:04x} nao bate com {msg}: {payload[:32].hex()}")

    async def command(self, req_type: int, msg: str, data: dict[str, Any]) -> None:
        """Comando de escrita: timestamp (8 bytes LE) + protobuf com timestamp."""
        ts = _ts()
        if any(f[0] == "timestamp" for f in _fields(msg)):
            data = {**data, "timestamp": ts}
        body = struct.pack("<Q", ts) + encode(msg, data)
        await self.request(req_type, body, msg="")

    # ---- leituras -------------------------------------------------------
    async def basic_info(self) -> dict[str, Any]:
        """SN, modelo, firmware, MAC do Twibi principal."""
        ack = await self.request(REQ_BASIC_INFO, msg="UcMSystem.proto_sys_common_ack")
        return ack.get("basic", {})

    async def nodes(self) -> list[dict[str, Any]]:
        return (await self.request(REQ_NODES)).get("node", [])

    async def hosts(self) -> list[dict[str, Any]]:
        return (await self.request(REQ_HOSTS)).get("hosts", [])

    async def remarks(self) -> dict[str, str]:
        marks = (await self.request(REQ_REMARKS)).get("marks", [])
        return {m["ethaddr"].upper(): m.get("remark", "") for m in marks}

    async def wan_status(self) -> dict[str, Any]:
        return await self.request(REQ_WAN_STATUS)

    async def wan_rate(self) -> dict[str, Any]:
        return await self.request(REQ_WAN_RATE)

    async def guest(self) -> dict[str, Any]:
        return await self.request(REQ_GUEST)

    async def macfilter(self) -> dict[str, Any]:
        return await self.request(REQ_MACFILTER)

    async def automaint(self) -> dict[str, Any]:
        return await self.request(REQ_AUTOMAINT)

    # ---- escritas -------------------------------------------------------
    async def set_remarks(self, marks: dict[str, str]) -> None:
        """Apelidos {mac: nome}. Nao reinicia o Wi-Fi."""
        await self.command(REQ_SET_REMARKS, "Onhosts.DeviceMarkList",
                           {"marks": [{"ethaddr": m.upper(), "remark": n} for m, n in marks.items()]})

    async def set_static_ip(self, mac: str, ip: str, enable: bool = True) -> None:
        """Reserva (ou remove) IP fixo. ATENCAO: o Twibi reinicia o Wi-Fi (~30 s)."""
        mac = mac.upper()
        host = next((h for h in await self.hosts() if h.get("ethaddr", "").upper() == mac), None)
        if host is None:
            raise TwibiError(f"{mac} nao esta na lista de aparelhos do Twibi (precisa estar online)")
        await self.command(REQ_STATIC_IP, "Onhosts.StaticIpInfo", {
            "ipaddr": host.get("ipaddr", ""), "ethaddr": mac,
            "dhcp_static": ip if enable else host.get("ipaddr", ""), "enable": 1 if enable else 0,
        })


    async def set_led(self, serial: str, on: bool) -> None:
        """Liga/desliga o LED de um no do mesh (sem reiniciar nada)."""
        await self.command(REQ_NODE_LED, "Node.NodeLedStatus", {"serialNum": serial, "lev": 1 if on else 0})

    async def set_guest(self, enable: bool) -> None:
        """Liga/desliga a rede de convidados mantendo SSID/senha/limites atuais."""
        cur = await self.guest()
        keep = ("band", "ssid", "passwd", "up_limit", "limite", "timeout")
        wlan = [{k: w[k] for k in keep if k in w} for w in cur.get("wlan", [])]
        data = {"wlan": wlan, "enable": enable, "from_app": True}
        if cur.get("timeout"):
            data["timeout"] = cur["timeout"]
        await self.command(REQ_SET_GUEST, "Wlan.WlanCfgAll", data)

    async def blocked(self) -> dict[str, str]:
        """Aparelhos na lista negra {mac: nome}."""
        mf = await self.macfilter()
        return {r["ethaddr"].upper(): r.get("name", "") for r in mf.get("rules", [])}

    async def set_blocked(self, mac: str, blocked: bool, name: str = "") -> None:
        """Bloqueia/desbloqueia um aparelho (lista negra, mode 0, como o app)."""
        mac = mac.upper()
        rules = {m: n for m, n in (await self.blocked()).items() if m != mac}
        if blocked:
            rules = {mac: name or mac, **rules}
        await self.command(REQ_SET_MACFILTER, "Macfilter.mf_lists",
                           {"mode": 0, "rules": [{"ethaddr": m, "name": n} for m, n in rules.items()]})

    async def set_automaint(self, enable: bool | None = None, time_hhmm: str | None = None) -> None:
        """Reinicio automatico diario (manutencao). Mantem o que nao for passado."""
        cur = await self.automaint()
        data = {k: cur[k] for k in ("status", "time", "freq", "delay") if k in cur}
        if enable is not None:
            data["status"] = enable
        if time_hhmm is not None:
            data["time"] = time_hhmm
        await self.command(REQ_SET_AUTOMAINT, "Advance.AutoMaint", data)

    async def reboot(self) -> None:
        """Reinicia todo o sistema mesh (internet cai ~1-2 min)."""
        async with self._lock:
            await self._request(REQ_REBOOT)


def _fields(msg: str):
    from .schema import SCHEMA
    return SCHEMA[msg].values()
