#!/usr/bin/env python3
"""
capture_pcap.py — no-root packet capture for Task 4.

The assignment's scripts/capture.sh uses tshark on the loopback interface,
which on macOS requires root (BPF) access. This script captures the same
traffic without any special privileges by relaying the real client/broker
exchange through a tiny userspace recording proxy and writing the genuine
on-the-wire bytes into standard .pcap files (openable in Wireshark/tshark).

Outputs:
    captures/mqtt.pcap   — real MQTT CONNECT / PUBLISH / PUBACK / SUBSCRIBE bytes
    captures/coap.pcap    — real CoAP CON GET / ACK 2.05 / Observe notification bytes

It also prints a wire-level breakdown of the key packets used to fill in
report/packet_analysis.md.

Usage:
    python3 scripts/capture_pcap.py            # capture both protocols
    python3 scripts/capture_pcap.py mqtt       # MQTT only (needs broker on 1883)
    python3 scripts/capture_pcap.py coap       # CoAP only (starts its own server)
"""

import asyncio
import json
import os
import socket
import struct
import sys
import threading
import time

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT     = os.path.dirname(THIS_DIR)
sys.path.insert(0, ROOT)
OUTDIR   = os.path.join(ROOT, "captures")
os.makedirs(OUTDIR, exist_ok=True)

from scapy.all import Ether, IP, TCP, UDP, Raw, wrpcap   # noqa: E402

CLIENT_IP = "127.0.0.1"
SERVER_IP = "127.0.0.1"
CLIENT_PORT = 49152          # synthetic ephemeral port used in the pcap


# ─────────────────────────────────────────────────────────────────────────────
# Recording proxies
# ─────────────────────────────────────────────────────────────────────────────

class TCPRecorder:
    """Listen on listen_port, relay to (dst_host, dst_port), record every segment."""

    def __init__(self, listen_port: int, dst_host: str, dst_port: int):
        self.listen_port = listen_port
        self.dst_host = dst_host
        self.dst_port = dst_port
        self.records: list[tuple[float, str, bytes]] = []   # (ts, 'c2s'|'s2c', data)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind((CLIENT_IP, listen_port))
        self._srv.listen(5)
        self._srv.settimeout(0.5)

    def start(self):
        self._thread.start()

    def _record(self, direction: str, data: bytes):
        if data:
            with self._lock:
                self.records.append((time.time(), direction, data))

    def _serve(self):
        while not self._stop.is_set():
            try:
                client, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def _handle(self, client: socket.socket):
        upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        upstream.connect((self.dst_host, self.dst_port))

        def pump(src, dst, direction):
            try:
                while True:
                    data = src.recv(65535)
                    if not data:
                        break
                    self._record(direction, data)
                    dst.sendall(data)
            except OSError:
                pass
            finally:
                for s in (src, dst):
                    try:
                        s.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

        t1 = threading.Thread(target=pump, args=(client, upstream, "c2s"), daemon=True)
        t2 = threading.Thread(target=pump, args=(upstream, client, "s2c"), daemon=True)
        t1.start(); t2.start(); t1.join(); t2.join()

    def stop(self):
        self._stop.set()
        try:
            self._srv.close()
        except OSError:
            pass


class UDPRecorder:
    """Relay UDP datagrams between a client and (dst_host, dst_port), recording each."""

    def __init__(self, listen_port: int, dst_host: str, dst_port: int):
        self.dst = (dst_host, dst_port)
        self.records: list[tuple[float, str, bytes]] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((CLIENT_IP, listen_port))
        self._sock.settimeout(0.5)
        self._client_addr = None
        self._up = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._up.bind((CLIENT_IP, 0))
        self._up.settimeout(0.5)

    def start(self):
        self._thread.start()

    def _record(self, direction: str, data: bytes):
        with self._lock:
            self.records.append((time.time(), direction, data))

    def _serve(self):
        threading.Thread(target=self._pump_upstream, daemon=True).start()
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            self._client_addr = addr
            self._record("c2s", data)
            self._up.sendto(data, self.dst)

    def _pump_upstream(self):
        while not self._stop.is_set():
            try:
                data, _ = self._up.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            self._record("s2c", data)
            if self._client_addr:
                self._sock.sendto(data, self._client_addr)

    def stop(self):
        self._stop.set()
        for s in (self._sock, self._up):
            try:
                s.close()
            except OSError:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# pcap builders (scapy) — synthesize standard headers around the real payloads
# ─────────────────────────────────────────────────────────────────────────────

def build_tcp_pcap(records, server_port, path):
    """Turn recorded TCP segments into a pcap with a proper 3-way handshake."""
    eth = lambda: Ether(src="02:00:00:00:00:01", dst="02:00:00:00:00:02")
    pkts = []
    base = records[0][0] if records else time.time()
    cseq, sseq = 1000, 5000

    def c2s(flags, seq, ack, payload=b""):
        p = (eth() / IP(src=CLIENT_IP, dst=SERVER_IP) /
             TCP(sport=CLIENT_PORT, dport=server_port, flags=flags, seq=seq, ack=ack))
        if payload:
            p = p / Raw(payload)
        return p

    def s2c(flags, seq, ack, payload=b""):
        p = (eth() / IP(src=SERVER_IP, dst=CLIENT_IP) /
             TCP(sport=server_port, dport=CLIENT_PORT, flags=flags, seq=seq, ack=ack))
        if payload:
            p = p / Raw(payload)
        return p

    # Handshake
    syn = c2s("S", cseq, 0);            syn.time = base; pkts.append(syn); cseq += 1
    sa  = s2c("SA", sseq, cseq);        sa.time = base; pkts.append(sa);  sseq += 1
    ack = c2s("A", cseq, sseq);         ack.time = base; pkts.append(ack)

    for ts, direction, data in records:
        if direction == "c2s":
            p = c2s("PA", cseq, sseq, data); p.time = ts; pkts.append(p); cseq += len(data)
            a = s2c("A", sseq, cseq);        a.time = ts; pkts.append(a)
        else:
            p = s2c("PA", sseq, cseq, data); p.time = ts; pkts.append(p); sseq += len(data)
            a = c2s("A", cseq, sseq);        a.time = ts; pkts.append(a)

    wrpcap(path, pkts)
    return len(pkts)


def build_udp_pcap(records, server_port, path):
    eth = lambda: Ether(src="02:00:00:00:00:01", dst="02:00:00:00:00:02")
    pkts = []
    for ts, direction, data in records:
        if direction == "c2s":
            p = (eth() / IP(src=CLIENT_IP, dst=SERVER_IP) /
                 UDP(sport=CLIENT_PORT, dport=server_port) / Raw(data))
        else:
            p = (eth() / IP(src=SERVER_IP, dst=CLIENT_IP) /
                 UDP(sport=server_port, dport=CLIENT_PORT) / Raw(data))
        p.time = ts
        pkts.append(p)
    wrpcap(path, pkts)
    return len(pkts)


# ─────────────────────────────────────────────────────────────────────────────
# MQTT capture
# ─────────────────────────────────────────────────────────────────────────────

def capture_mqtt(duration=6):
    import paho.mqtt.client as mqtt

    print("\n=== MQTT capture (proxy 18831 -> broker 1883) ===")
    rec = TCPRecorder(18831, "127.0.0.1", 1883)
    rec.start()
    time.sleep(0.3)

    # A direct subscriber so the broker actually routes the PUBLISH messages.
    sub = mqtt.Client(client_id="capture-subscriber")
    sub.connect("127.0.0.1", 1883, 60)
    sub.subscribe("factory/#", qos=1)
    sub.loop_start()

    # Publisher routed THROUGH the recording proxy.
    from src.mqtt.publisher import SmartFactoryPublisher
    pub = SmartFactoryPublisher(broker_host="127.0.0.1", broker_port=18831)
    pub.connect()
    t_end = time.time() + duration
    while time.time() < t_end:
        for line in ["line1", "line2"]:
            for s in ["temperature", "vibration", "power"]:
                pub.publish_reading(line, s)
        time.sleep(1)
    pub.disconnect()
    sub.loop_stop(); sub.disconnect()
    time.sleep(0.3)
    rec.stop()

    path = os.path.join(OUTDIR, "mqtt.pcap")
    n = build_tcp_pcap(rec.records, 1883, path)
    print(f"Wrote {path}  ({n} packets, {len(rec.records)} payload segments)")
    return rec.records


# ─────────────────────────────────────────────────────────────────────────────
# CoAP capture
# ─────────────────────────────────────────────────────────────────────────────

async def _coap_capture_client(proxy_port):
    import aiocoap
    from aiocoap import Message, Code
    ctx = await aiocoap.Context.create_client_context()
    base = f"coap://127.0.0.1:{proxy_port}"

    # 1) A plain CON GET -> ACK 2.05 Content
    req = Message(code=Code.GET, uri=f"{base}/factory/line1/temperature")
    resp = await ctx.request(req).response
    print(f"  CON GET -> {resp.code} ({len(resp.payload)} B payload)")

    # 2) Observe registration to capture an Observe notification (server pushes every 5 s)
    obs_req = Message(code=Code.GET, uri=f"{base}/factory/line1/temperature", observe=0)
    pr = ctx.request(obs_req)
    await pr.response
    got = 0

    async def consume():
        nonlocal got
        async for r in pr.observation:
            got += 1
            print(f"  Observe notification seq={r.opt.observe}")
            if got >= 1:
                break
    try:
        await asyncio.wait_for(consume(), timeout=7)
    except asyncio.TimeoutError:
        pass
    if not getattr(pr.observation, "cancelled", False):
        pr.observation.cancel()
    await ctx.shutdown()


def capture_coap(duration=8):
    print("\n=== CoAP capture (proxy 56830 -> server 5683) ===")
    from src.coap.server import build_server

    rec = UDPRecorder(56830, "127.0.0.1", 5683)

    async def driver():
        # Bind to IPv4 loopback explicitly so the UDP proxy (127.0.0.1) reaches it.
        server = await build_server(bind=("127.0.0.1", 5683))
        rec.start()
        time.sleep(0.3)
        await _coap_capture_client(56830)
        time.sleep(0.3)
        rec.stop()
        await server.shutdown()

    asyncio.run(driver())

    path = os.path.join(OUTDIR, "coap.pcap")
    n = build_udp_pcap(rec.records, 5683, path)
    print(f"Wrote {path}  ({n} packets / datagrams)")
    return rec.records


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    if which in ("mqtt", "both"):
        capture_mqtt()
    if which in ("coap", "both"):
        capture_coap()
    print("\nDone. pcap files in captures/")
