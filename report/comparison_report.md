# Module 2 Assignment — Protocol Comparison Report

**Student Name:** Sheikh Fraz Alam
**Student ID:**   101044142
**Date:**         2026-05-28

> **Scope note.** Per the assignment brief, the **AMQP tasks were ignored**; this
> report therefore compares **MQTT** and **CoAP** in depth and treats AMQP only
> where the spec template requires a placeholder. All MQTT and CoAP figures are
> real measurements from this implementation (`tests/mqtt/test_qos_loss.py`, a
> CoAP CON/NON latency probe, and the captures in `captures/`).

---

## 5.1 QoS Comparison Results Table

Measured on the macOS loopback interface (a near-lossless link). MQTT figures
are from `pytest tests/mqtt/test_qos_loss.py -s` (100 msgs/level); CoAP figures
are from a 50-request CON/NON latency probe against the Task 2 server.

| Protocol / QoS | Sent | Received | Lost (%) | Duplicates | Avg Latency (ms) |
|----------------|------|----------|----------|------------|-----------------|
| MQTT QoS 0 | 100 | 100 | 0.0 % | 0 | 0.6 |
| MQTT QoS 1 | 100 | 100 | 0.0 % | 0 | 0.7 |
| MQTT QoS 2 | 100 | 100 | 0.0 % | 0 | 1.1 |
| CoAP NON | 50 | 50 | 0.0 % | 0 | 1.42 |
| CoAP CON | 50 | 50 | 0.0 % | 0 | 1.60 |
| AMQP (confirms off) | — | — | — | — | omitted (AMQP ignored) |

**Analysis Questions:**

1. **Why does QoS 0 lose messages while QoS 1 and 2 do not?**

   > QoS 0 is "fire-and-forget": the publisher sends a single PUBLISH and keeps no
   > state, so if that datagram/segment is dropped the message is gone with no
   > retransmission. QoS 1 keeps the message in an in-flight store until it sees a
   > PUBACK, and QoS 2 uses the 4-way PUBLISH/PUBREC/PUBREL/PUBCOMP handshake;
   > both retransmit on timeout, so under loss they still achieve delivery. On the
   > loopback link here there was no real loss, so all three delivered 100 % — but
   > the *mechanism* that protects QoS 1/2 (acknowledged, retransmitted state) is
   > exactly what QoS 0 lacks, which is why QoS 0 is the level that degrades first
   > on any lossy network.

2. **QoS 1 may show duplicates. Under what circumstances does this happen, and is it a problem for sensor telemetry?**

   > A duplicate occurs when the PUBACK is lost or delayed: the publisher's timer
   > fires, it re-sends the PUBLISH with the DUP flag set, and the broker delivers
   > the message twice (QoS 1 guarantees *at-least-once*, not exactly-once). For
   > sensor telemetry this is usually harmless — each reading carries a `seq` and
   > `timestamp`, so a consumer can de-duplicate, and a repeated temperature sample
   > is not dangerous. It only matters for non-idempotent actions (e.g. "increment
   > a counter" or "actuate"), where QoS 2 is preferable.

3. **QoS 2 has higher latency than QoS 1. What causes this, and when is the trade-off worth it?**

   > QoS 2 completes a four-message handshake (PUBLISH → PUBREC → PUBREL → PUBCOMP)
   > versus QoS 1's two messages (PUBLISH → PUBACK), adding a full extra round trip
   > and broker-side state to guarantee exactly-once. The measured cost here was
   > ~1.1 ms vs ~0.7 ms (~55 % higher). The trade-off is worth it only when a
   > duplicate would cause incorrect behaviour — safety-critical commands, billing,
   > or state transitions — and is wasteful for high-frequency, idempotent
   > telemetry where QoS 0/1 suffice.

---

## 5.2 CoAP–HTTP Proxy Mapping

The `tests/coap/test_proxy.py` harness referenced in the brief was **not present
in the starter kit**, and aiocoap's bundled proxy is CoAP-to-CoAP (no HTTP
frontend), so a live HTTP capture could not be produced here. The table below
documents the canonical CoAP-option → HTTP-header mapping (RFC 8075 *Guidelines
for HTTP-CoAP Mapping* and RFC 7252 §10) using the **actual option values my
Task 2 server emits** (verified in `captures/coap.pcap`).

| HTTP Header | CoAP Option | Your Observed Value |
|-------------|-------------|---------------------|
| Content-Type | Content-Format (option #12) | `application/json` (CoAP CF `0x32` = 50, seen in the ACK 2.05) |
| Cache-Control: max-age | Max-Age (option #14) | `max-age=60` (CoAP default Max-Age = 60 s when the option is absent) |
| ETag | ETag (option #4) | opaque validator copied verbatim, e.g. `"54c3"` (CoAP ETag bytes → quoted HTTP ETag) |
| Location | Location-Path (#8) / Location-Query (#20) | `/actuator/line1/fan` (segments of the Location-Path options joined with `/`) |

Notes: the proxy maps the CoAP response code to the HTTP status (2.05 Content →
`200 OK`, 2.04 Changed → `204 No Content`, 4.04 → `404`), strips the CoAP
Payload Marker (`0xFF`) and forwards the raw body, and translates the numeric
Content-Format into the matching IANA media type for `Content-Type`.

---

## 5.3 Protocol Selection Recommendation

### Data Path Recommendations

| Data Path | Recommended Protocol | Justification |
|-----------|---------------------|---------------|
| Sensor → Cloud (high frequency, <100 ms latency) | **MQTT QoS 0/1** | Lowest per-message latency (0.6–0.7 ms measured); tiny fixed header; persistent broker connection avoids per-message setup. |
| Actuator commands (safety-critical, exactly-once) | **MQTT QoS 2** (or CoAP CON to the actuator) | Only QoS 2 gives exactly-once; the 4-way handshake's extra ~0.4 ms is acceptable for rare commands. |
| Backend service-to-service routing | **AMQP** (out of scope here) → otherwise **MQTT topic wildcards** | Broker-side topic/exchange routing decouples producers and consumers. |
| OTA firmware delivery to constrained MCU (Class 2) | **CoAP Block-wise (Block2)** | UDP-based, no TCP/TLS RAM cost; Block2 streams a large manifest in bounded chunks — measured 12 098 B manifest in 12 × 1024 B blocks. |

### Detailed Justification

**Sensor → Cloud (high frequency, <100 ms).** For continuous, high-rate telemetry
the dominant costs are per-message latency and header overhead. MQTT wins on both.
The packet capture shows a temperature PUBLISH is a compact binary frame — a
1-byte fixed header, a 2-byte remaining-length varint, the topic string, and the
JSON payload — over a connection that was established **once** at startup
(the CONNECT in `captures/mqtt.pcap` carries `Clean Session = 0`, so the session
and subscriptions survive across the run). Because the TCP/MQTT session is
persistent, each subsequent reading pays no connection-setup cost, which is why
QoS 0/1 measured **0.6–0.7 ms** end-to-end. At this data path I would run
temperature and power at **QoS 1** (so the cloud reliably sees each sample under
real loss) and high-rate vibration at **QoS 0**, exactly as the publisher is
configured. The `seq`/`timestamp` fields in each payload let the cloud detect the
rare QoS-1 duplicate, so at-least-once is effectively exactly-once for analytics.

**Actuator commands (safety-critical, exactly-once).** Turning a cooling fan ON
twice is benign, but a command stream that includes state transitions or
interlocks must not duplicate or drop. **MQTT QoS 2** is the only level that
guarantees exactly-once, via the PUBLISH/PUBREC/PUBREL/PUBCOMP exchange; my
measurement put QoS 2 at ~1.1 ms versus ~0.7 ms for QoS 1 — a ~0.4 ms premium
that is irrelevant for commands issued seconds or minutes apart. A strong
alternative for a *local* actuator is a **CoAP CON PUT** directly to
`/actuator/line1/fan`: the confirmable message is retransmitted until the server
returns `2.04 Changed`, giving reliable, low-RAM request/response without a broker
in the path (measured CoAP CON round-trip 1.60 ms). I recommend MQTT QoS 2 when
the command flows through the central broker, and CoAP CON for direct
controller-to-actuator links.

**Backend service-to-service routing.** This is AMQP's home turf (durable queues,
topic/header exchanges, dead-lettering) and was out of scope for this submission.
Where AMQP is unavailable, MQTT's hierarchical topics with `+`/`#` wildcards plus
shared subscriptions provide adequate fan-out routing; my subscriber demonstrates
this by binding `factory/#` for everything and a separate `factory/+/temperature`
at QoS 2 for the critical path. The key technical point is that broker-mediated
routing (MQTT or AMQP) decouples producers from consumers far better than CoAP's
point-to-point request/response, which has no native server-side routing fabric.

**OTA firmware delivery to a constrained Class-2 MCU.** A Class-2 device
(~50 KiB RAM) cannot comfortably hold a TLS/TCP stack and large buffers, which
disfavours MQTT-over-TLS for big transfers. **CoAP over UDP with Block-wise
transfer (Block2)** is purpose-built for this: the device requests the resource
and the stack streams it in fixed, individually-acknowledged blocks so peak
memory stays at one block. My `/factory/manifest` resource produced a **12 098-byte**
JSON manifest that the observer reassembled as **12 blocks of 1024 bytes** — exactly
the bounded-memory behaviour a constrained node needs, with the option to resume
per block. CoAP's 4-byte header also minimises per-block overhead. MQTT, by
contrast, has no native fragmentation and would require an application-level
chunking scheme on top of a heavier transport.

---

## 5.4 Reflection

### Technical Challenge

> The hardest practical problem was packet capture on macOS. `tshark` was not
> available and loopback capture via `tcpdump` requires root BPF access, which I
> could not obtain non-interactively. Rather than fake the data, I wrote a small
> userspace **recording proxy** (`scripts/capture_pcap.py`): the MQTT publisher
> and CoAP client connect through a local relay that forwards every byte to the
> real broker/server and logs both directions, then I wrap those genuine payloads
> in synthesised Ethernet/IP/TCP(/UDP) headers with scapy to emit valid `.pcap`
> files. A second subtle bug surfaced here: aiocoap on macOS bound the server to
> IPv6 `::1` while my proxy forwarded to IPv4 `127.0.0.1`, so requests timed out
> until I made `build_server()` accept an explicit IPv4 bind. The annotation
> tables in `packet_analysis.md` are decoded straight from these real captures.

### Most Surprising Protocol Difference

> The starkest contrast in the captures was **header weight and connection model**.
> A CoAP CON GET for `/factory/line1/temperature` is just **4 header bytes + a
> 2-byte token + Uri-Path options** in a single UDP datagram with no setup — yet
> it still carries reliability (CON/ACK) and a built-in cache lifetime (Max-Age).
> MQTT, to deliver one QoS-1 reading, first spends a 71-byte CONNECT plus CONNACK
> to stand up a persistent TCP session, after which each PUBLISH is cheap. So CoAP
> is dramatically lighter *per isolated transaction*, while MQTT amortises its
> setup over a long-lived stream — the capture made that architectural trade-off
> visible at the byte level.

### Most Complex Protocol to Implement

> **CoAP** was the most complex to get right. MQTT with paho is largely
> declarative — set `clean_session`, `will_set`, publish at a QoS — whereas CoAP
> required reasoning about the asyncio observation lifecycle (registering with
> `observe=0`, consuming an async iterator, and deregistering cleanly so the
> server stops pushing), about Observe **sequence-number wrap-around** at 2^24 to
> detect stale notifications (RFC 7641 §3.4), and about Block2 reassembly and
> content-format negotiation. The aiocoap transport selection on macOS (UDP vs
> the WebSocket fallback, and the IPv4/IPv6 bind issue above) added another layer
> that MQTT simply never presented.

---

*Module 2 Assignment — Real-Time Data Analytics for IoT*
