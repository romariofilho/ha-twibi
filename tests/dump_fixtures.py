"""Le todos os GETs do Twibi real e grava em tests/fixtures (bin cru + json decodificado)."""
import asyncio, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "custom_components", "twibi"))
from lib import client as c  # noqa: E402

GETS = {
    "basic_info": (c.REQ_BASIC_INFO, "UcMSystem.proto_sys_common_ack"),
    "nodes": (c.REQ_NODES, None), "hosts": (c.REQ_HOSTS, None), "remarks": (c.REQ_REMARKS, None),
    "wan_status": (c.REQ_WAN_STATUS, None), "wan_cfg": (c.REQ_WAN_CFG, None),
    "wan_line": (c.REQ_WAN_LINE, None), "wan_rate": (c.REQ_WAN_RATE, None),
    "wlan": (c.REQ_WLAN, None), "guest": (c.REQ_GUEST, None), "macfilter": (c.REQ_MACFILTER, None),
    "automaint": (c.REQ_AUTOMAINT, None), "dhcp": (c.REQ_DHCP, None),
    "roaming": (c.REQ_ROAMING, None),
}

async def main():
    pw = os.environ["TWIBI_PASSWORD"]
    async with c.TwibiClient(os.environ.get("TWIBI_HOST", "10.1.1.1"), pw) as t:
        for name, (rt, msg) in GETS.items():
            async with t._lock:
                st, raw = await t._request(rt)
            open(os.path.join(HERE, "fixtures", f"{name}.bin"), "wb").write(raw)
            msg = msg or c.RESPONSE_MSG[rt]
            dec = None
            for cand in (raw, raw[4:]):  # mesma resposta crua (nao consultar de novo)
                try:
                    dec = c.decode(msg, cand)
                    break
                except c.DecodeError:
                    continue
            txt = json.dumps(dec, ensure_ascii=False, indent=1, default=lambda b: b.hex())
            open(os.path.join(HERE, "fixtures", f"{name}.json"), "w").write(txt)
            print(f"{name:11} 0x{rt:04x} st={st} {'ok' if dec is not None else 'ERRO'}")
    print("ATENCAO: anonimize as fixtures (MACs, nomes, SSID, senhas, seriais) antes de versionar.")


asyncio.run(main())
