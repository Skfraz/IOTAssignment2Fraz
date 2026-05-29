#!/usr/bin/env python3
"""
analyze_pcap.py — decode the captured MQTT / CoAP packets into the exact
wire-level fields required for report/packet_analysis.md (Task 4).

Reads captures/*.pcap, extracts the transport payloads, and prints a
byte-by-byte breakdown of the key packets.

Usage:
    python3 scripts/analyze_pcap.py mqtt
    python3 scripts/analyze_pcap.py coap
    python3 scripts/analyze_pcap.py            # both
"""
import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(THIS_DIR)
CAP = os.path.join(ROOT, "captures")

from scapy.all import rdpcap, TCP, UDP, Raw   # noqa: E402

CON, NON, ACK, RST = 0, 1, 2, 3
COAP_TYPE = {0: "CON", 1: "NON", 2: "ACK", 3: "RST"}


def hx(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


def bits(byte: int) -> str:
    return format(byte, "08b")


# ─────────────────────────────────────────────────────────────────────────────
# MQTT
# ─────────────────────────────────────────────────────────────────────────────

MQTT_TYPES = {1: "CONNECT", 2: "CONNACK", 3: "PUBLISH", 4: "PUBACK",
              5: "PUBREC", 6: "PUBREL", 7: "PUBCOMP", 8: "SUBSCRIBE",
              9: "SUBACK", 12: "PINGREQ", 13: "PINGRESP", 14: "DISCONNECT"}


def mqtt_segments(pkts):
    """Yield each MQTT control packet (handles multiple per TCP segment)."""
    for p in pkts:
        if TCP in p and Raw in p:
            data = bytes(p[Raw].load)
            off = 0
            while off < len(data):
                if off + 2 > len(data):
                    break
                b1 = data[off]
                # decode remaining length (varint)
                rl = 0; mult = 1; i = off + 1; consumed = 0
                while i < len(data):
                    enc = data[i]; rl += (enc & 0x7F) * mult
                    consumed += 1; i += 1
                    if enc & 0x80 == 0:
                        break
                    mult *= 128
                total = 1 + consumed + rl
                seg = data[off:off + total]
                yield b1, rl, seg
                off += total if total > 0 else len(data)


def analyze_mqtt():
    path = os.path.join(CAP, "mqtt.pcap")
    if not os.path.exists(path):
        print("!! captures/mqtt.pcap not found — run capture_pcap.py mqtt first")
        return
    pkts = rdpcap(path)
    print("=" * 70)
    print("MQTT PACKET ANALYSIS  (", len(pkts), "frames )")
    print("=" * 70)

    connect = None
    q1_publishes = []          # all QoS-1 PUBLISH segments
    pubacks = {}               # packet id -> segment
    for b1, rl, seg in mqtt_segments(pkts):
        ptype = b1 >> 4
        if ptype == 1 and connect is None:
            connect = seg
        elif ptype == 3 and ((b1 >> 1) & 0x3) == 1:
            q1_publishes.append(seg)
        elif ptype == 4:
            pid = (seg[2] << 8) | seg[3]
            pubacks.setdefault(pid, seg)

    def vh_start(seg):
        """Index where the variable header begins (past fixed byte + RL varint)."""
        i = 1
        while seg[i] & 0x80:
            i += 1
        return i + 1

    # Prefer a temperature reading PUBLISH (the spec's example) over the status msg.
    def pub_topic(seg):
        v = vh_start(seg)
        tl = (seg[v] << 8) | seg[v + 1]
        return seg[v + 2:v + 2 + tl].decode(errors="replace")

    publish_q1 = next((s for s in q1_publishes if "temperature" in pub_topic(s)), None) \
        or (q1_publishes[0] if q1_publishes else None)

    puback = None
    if publish_q1:
        v = vh_start(publish_q1)
        tl = (publish_q1[v] << 8) | publish_q1[v + 1]
        pid = (publish_q1[v + 2 + tl] << 8) | publish_q1[v + 2 + tl + 1]
        puback = pubacks.get(pid)

    # ── CONNECT ──
    if connect:
        print("\n--- CONNECT ---")
        print("raw:", hx(connect))
        b1 = connect[0]
        print(f"byte0 = 0x{b1:02X}  type={b1>>4} ({MQTT_TYPES.get(b1>>4)})  flags={b1&0xF:04b}")
        print(f"remaining length byte = 0x{connect[1]:02X} = {connect[1]}")
        pnl = (connect[2] << 8) | connect[3]
        print(f"protocol name length = {connect[2]:02X} {connect[3]:02X} = {pnl}")
        name = connect[4:4 + pnl]
        print(f"protocol name = {hx(name)} = {name.decode()!r}")
        ver = connect[4 + pnl]
        print(f"protocol version = 0x{ver:02X} = {ver} (MQTT {'3.1.1' if ver==4 else ver})")
        cflags = connect[5 + pnl]
        print(f"connect flags = 0x{cflags:02X} = {bits(cflags)}")
        print(f"    bit7 username   = {(cflags>>7)&1}")
        print(f"    bit6 password   = {(cflags>>6)&1}")
        print(f"    bit5 will retain= {(cflags>>5)&1}")
        print(f"    bit4-3 will QoS = {(cflags>>3)&3}")
        print(f"    bit2 will flag  = {(cflags>>2)&1}")
        print(f"    bit1 clean sess = {(cflags>>1)&1}")
        print(f"    bit0 reserved   = {cflags&1}")
        ka = (connect[6 + pnl] << 8) | connect[7 + pnl]
        print(f"keep-alive = {connect[6+pnl]:02X} {connect[7+pnl]:02X} = {ka} s")
        cidl = (connect[8 + pnl] << 8) | connect[9 + pnl]
        cid = connect[10 + pnl:10 + pnl + cidl]
        print(f"client id length = {cidl}")
        print(f"client id = {cid.decode(errors='replace')!r}")

    # ── PUBLISH QoS 1 ──
    if publish_q1:
        print("\n--- PUBLISH (QoS 1) ---")
        print("raw:", hx(publish_q1[:40]), "...")
        b1 = publish_q1[0]
        print(f"byte0 = 0x{b1:02X} = {bits(b1)}")
        print(f"    type bits7-4 = {b1>>4:04b} = PUBLISH(3)")
        print(f"    DUP  bit3    = {(b1>>3)&1}")
        print(f"    QoS  bit2-1  = {(b1>>1)&3:02b} = QoS {(b1>>1)&3}")
        print(f"    RETAIN bit0  = {b1&1}")
        v = vh_start(publish_q1)
        rl_bytes = publish_q1[1:v]
        print(f"remaining length = {hx(rl_bytes)} (varint, {v-1} byte(s))")
        tl = (publish_q1[v] << 8) | publish_q1[v + 1]
        topic = publish_q1[v + 2:v + 2 + tl]
        print(f"topic length = {publish_q1[v]:02X} {publish_q1[v+1]:02X} = {tl}")
        print(f"topic = {topic.decode()!r}")
        pid_off = v + 2 + tl
        pid = (publish_q1[pid_off] << 8) | publish_q1[pid_off + 1]
        print(f"packet identifier = {publish_q1[pid_off]:02X} {publish_q1[pid_off+1]:02X} = {pid}")
        payload = publish_q1[pid_off + 2:]
        print(f"payload ({len(payload)} B) = {payload.decode(errors='replace')!r}")

    # ── PUBACK ──
    if puback:
        print("\n--- PUBACK ---")
        print("raw:", hx(puback))
        print(f"byte0 = 0x{puback[0]:02X}  type={puback[0]>>4} (PUBACK)")
        print(f"remaining length = {puback[1]}")
        pid = (puback[2] << 8) | puback[3]
        print(f"packet identifier = {puback[2]:02X} {puback[3]:02X} = {pid}")


# ─────────────────────────────────────────────────────────────────────────────
# CoAP
# ─────────────────────────────────────────────────────────────────────────────

def decode_coap(data: bytes) -> dict:
    b0 = data[0]
    ver = b0 >> 6
    typ = (b0 >> 4) & 0x3
    tkl = b0 & 0xF
    code = data[1]
    mid = (data[2] << 8) | data[3]
    token = data[4:4 + tkl]
    off = 4 + tkl
    opts = []
    last_num = 0
    payload = b""
    while off < len(data):
        if data[off] == 0xFF:
            payload = data[off + 1:]
            break
        delta = data[off] >> 4
        length = data[off] & 0xF
        off += 1
        if delta == 13:
            delta = data[off] + 13; off += 1
        if length == 13:
            length = data[off] + 13; off += 1
        num = last_num + delta
        val = data[off:off + length]
        off += length
        last_num = num
        opts.append((num, delta, length, val))
    return dict(ver=ver, typ=typ, tkl=tkl, code=code, mid=mid,
               token=token, opts=opts, payload=payload, raw=data)


COAP_OPT = {1: "If-Match", 3: "Uri-Host", 4: "ETag", 5: "If-None-Match",
            6: "Observe", 7: "Uri-Port", 8: "Location-Path", 11: "Uri-Path",
            12: "Content-Format", 14: "Max-Age", 15: "Uri-Query",
            17: "Accept", 20: "Location-Query", 35: "Proxy-Uri",
            23: "Block2", 27: "Block1", 60: "Size1"}


def code_str(code: int) -> str:
    return f"{code >> 5}.{code & 0x1F:02d}"


def analyze_coap():
    path = os.path.join(CAP, "coap.pcap")
    if not os.path.exists(path):
        print("!! captures/coap.pcap not found — run capture_pcap.py coap first")
        return
    pkts = rdpcap(path)
    msgs = []
    for p in pkts:
        if UDP in p and Raw in p:
            msgs.append(decode_coap(bytes(p[Raw].load)))

    print("\n" + "=" * 70)
    print("CoAP PACKET ANALYSIS  (", len(msgs), "datagrams )")
    print("=" * 70)

    con_get = next((m for m in msgs if m["typ"] == CON and m["code"] == 0x01), None)
    ack_content = next((m for m in msgs if m["typ"] == ACK and m["code"] == 0x45), None)
    notify = next((m for m in msgs if any(o[0] == 6 for o in m["opts"])
                   and m["code"] == 0x45 and m is not ack_content), None)
    if notify is None:
        notify = next((m for m in msgs if any(o[0] == 6 for o in m["opts"]) and m["code"] == 0x45), None)

    def dump(title, m):
        if not m:
            print(f"\n--- {title}: NOT FOUND ---")
            return
        print(f"\n--- {title} ---")
        print("raw:", hx(m["raw"][:48]), ("..." if len(m["raw"]) > 48 else ""))
        b0 = m["raw"][0]
        print(f"byte0 = 0x{b0:02X} = {bits(b0)}")
        print(f"    Ver  bits7-6 = {b0>>6:02b} = {m['ver']}")
        print(f"    Type bits5-4 = {(b0>>4)&3:02b} = {COAP_TYPE[m['typ']]}")
        print(f"    TKL  bits3-0 = {b0&0xF:04b} = {m['tkl']}")
        print(f"byte1 code = 0x{m['code']:02X} = {code_str(m['code'])}")
        print(f"message id = {m['raw'][2]:02X} {m['raw'][3]:02X} = {m['mid']}")
        print(f"token = {hx(m['token']) or '(none)'}  (len {m['tkl']})")
        for num, delta, length, val in m["opts"]:
            name = COAP_OPT.get(num, f"#{num}")
            shown = val.decode(errors="replace") if name in ("Uri-Path", "Uri-Host", "Location-Path") else hx(val)
            extra = ""
            if num == 6:
                extra = f"  (Observe seq = {int.from_bytes(val,'big') if val else 0})"
            if num == 12:
                extra = f"  (Content-Format = {int.from_bytes(val,'big') if val else 0})"
            print(f"option #{num} {name}: delta={delta} len={length} value={shown}{extra}")
        if m["payload"]:
            pl = m["payload"]
            print(f"payload marker 0xFF, payload ({len(pl)} B) = {pl[:60].decode(errors='replace')!r}")

    dump("CON GET request", con_get)
    dump("ACK 2.05 Content response", ack_content)
    dump("Observe notification", notify)

    if con_get and ack_content:
        print("\nToken match (request vs response):",
              con_get["token"] == ack_content["token"],
              f"({hx(con_get['token'])} vs {hx(ack_content['token'])})")
        print("Message-ID match:", con_get["mid"] == ack_content["mid"],
              f"({con_get['mid']} vs {ack_content['mid']})")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    if which in ("mqtt", "both"):
        analyze_mqtt()
    if which in ("coap", "both"):
        analyze_coap()
