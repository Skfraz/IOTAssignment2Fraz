# Module 2 Assignment — Packet Analysis
## Task 4: Wire-Level Protocol Annotation

> **Capture method.** macOS does not grant loopback packet capture (BPF) without
> root, and `tshark` was not available, so the traffic was captured at the byte
> level by relaying the real client↔broker / client↔server exchange through a
> small userspace recording proxy (`scripts/capture_pcap.py`). The bytes below
> are the genuine on-the-wire protocol messages; the resulting `captures/mqtt.pcap`
> and `captures/coap.pcap` are valid pcap files that open in Wireshark. All hex
> values were decoded by `scripts/analyze_pcap.py` directly from the capture.
>
> **AMQP (Section 4.4) is intentionally omitted** per the assignment instruction
> to ignore the AMQP tasks.

---

## 4.2 MQTT Packet Annotations

Source packet (CONNECT, full hex):
`10 45 00 04 4D 51 54 54 04 2C 00 3C 00 1A 73 6D 61 72 74 66 61 63 74 6F 72 79 2D 70 75 62 6C 69 73 68 65 72 2D 30 30 31 …`

### CONNECT Packet

| Field | Offset (bytes) | Raw Hex | Decoded Value |
|-------|---------------|---------|---------------|
| Frame type + flags (byte 1) | 0 | `10` | Type=CONNECT (0001), flags=0000 |
| Remaining length (byte 2) | 1 | `45` | 69 bytes |
| Protocol name length | 2–3 | `00 04` | 4 |
| Protocol name | 4–7 | `4D 51 54 54` | "MQTT" |
| Protocol version | 8 | `04` | 4 (MQTT 3.1.1) |
| Connect flags | 9 | `2C` | See breakdown below |
| Keep-alive | 10–11 | `00 3C` | 60 seconds |
| Client ID length | 12–13 | `00 1A` | 26 |
| Client ID | 14–… | `73 6D 61 72 74 …` | "smartfactory-publisher-001" |

**Connect Flags byte breakdown:** `0x2C = 0010 1100`

| Bit | Name | Value | Meaning |
|-----|------|-------|---------|
| 7 | Username flag | 0 | No username |
| 6 | Password flag | 0 | No password |
| 5 | Will retain | 1 | LWT published with retain=true |
| 4–3 | Will QoS | 01 | LWT QoS = 1 |
| 2 | Will flag | 1 | Last Will & Testament present |
| 1 | Clean session | 0 | **Persistent session (Clean Session = 0)** |
| 0 | Reserved | 0 | — |

---

### QoS 1 PUBLISH Packet  (topic `factory/line1/temperature`)

Source hex:
`32 A0 01 00 19 66 61 63 74 6F 72 79 2F 6C 69 6E 65 31 2F 74 65 6D 70 65 72 61 74 75 72 65 00 03 7B 22 6C 69 6E 65 22 …`

| Field | Offset (bytes) | Raw Hex | Decoded Value |
|-------|---------------|---------|---------------|
| Fixed header byte 1 | 0 | `32` | Type=PUBLISH(0011), DUP=0, QoS=1, RETAIN=0 |
| Remaining length | 1–2 | `A0 01` | 160 bytes (2-byte varint: 0x20 + 0x01·128) |
| Topic length | 3–4 | `00 19` | 25 |
| Topic string | 5–29 | `66 61 63 74 6F 72 79 …` | "factory/line1/temperature" |
| Packet Identifier | 30–31 | `00 03` | 3 |
| Payload | 32–… | `7B 22 6C 69 6E 65 …` | `{"line":"line1","sensor":"temperature","value":72.606,…}` (131 B) |

**Fixed header byte 1 bit expansion:** `0x32 = 0011 0010`

| Bits 7–4 (packet type) | Bit 3 (DUP) | Bits 2–1 (QoS) | Bit 0 (RETAIN) |
|------------------------|-------------|----------------|----------------|
| `0011` = PUBLISH (3)  | `0` = not a redelivery | `01` = QoS 1 | `0` = not retained |

---

### PUBACK Packet

Source hex: `40 02 00 03`

| Field | Offset | Raw Hex | Decoded Value |
|-------|--------|---------|---------------|
| Fixed header | 0 | `40` | Type=PUBACK (0100) |
| Remaining length | 1 | `02` | 2 bytes |
| Packet Identifier | 2–3 | `00 03` | 3 |

**Packet Identifier match:** PUBLISH PKT ID = **3** ; PUBACK PKT ID = **3** ; **Match? ✅ YES**

---

## 4.3 CoAP Packet Annotations

### CON GET Request  (`/factory/line1/temperature`)

```
Bytes: 42 01 7A 04  54 C3  B7 66 61 63 74 6F 72 79 ...
       [  Header  ] [Token] [Options: Uri-Path ...]
```
Source hex:
`42 01 7A 04 54 C3 B7 66 61 63 74 6F 72 79 05 6C 69 6E 65 31 0B 74 65 6D 70 65 72 61 74 75 72 65`

| Field | Bits/Bytes | Raw Value | Decoded Value |
|-------|-----------|-----------|---------------|
| Version (bits 7–6) | 2 bits | `01` | 1 (always 1) |
| Type (bits 5–4) | 2 bits | `00` | 0 = CON |
| TKL (bits 3–0) | 4 bits | `0010` | Token length = 2 |
| Code (byte 1) | 8 bits | `01` | 0.01 = GET |
| Message ID (bytes 2–3) | 16 bits | `7A 04` | 31236 |
| Token (bytes 4–5) | 2 bytes | `54 C3` | 0x54C3 |
| Option Delta | 4 bits | `B` | Delta = 11, Option# = 11 (Uri-Path) |
| Option Length | 4 bits | `7` | 7 → value "factory" |
| Option Value | 7 bytes | `66 61 63 74 6F 72 79` | "factory" (Uri-Path) |
| 2nd Uri-Path | — | delta `0`, len `5` | "line1" |
| 3rd Uri-Path | — | delta `0`, len `B`=11 | "temperature" |

**Byte 0 full expansion:** `0x42 = 0100 0010`

| Bit 7 | Bit 6 | Bit 5 | Bit 4 | Bit 3 | Bit 2 | Bit 1 | Bit 0 |
|-------|-------|-------|-------|-------|-------|-------|-------|
| Ver   | Ver   | T     | T     | TKL   | TKL   | TKL   | TKL   |
| `0`   | `1`   | `0`   | `0`   | `0`   | `0`   | `1`   | `0`   |

(Ver = `01` = 1, Type = `00` = CON, TKL = `0010` = 2.)

---

### ACK 2.05 Content Response

Source hex:
`62 45 7A 04 54 C3 C1 32 FF 7B 22 76 61 6C 75 65 22 3A 20 37 36 2E 31 31 36 …`

| Field | Bytes | Raw Hex | Decoded Value |
|-------|-------|---------|---------------|
| Fixed header byte 0 | 0 | `62` | Ver=01, T=10 (ACK), TKL=2 |
| Code byte 1 | 1 | `45` | 2.05 = Content |
| Message ID | 2–3 | `7A 04` | 31236 (matches request? **YES**) |
| Token | 4–5 | `54 C3` | 0x54C3 (matches request? **YES**) |
| Option: Content-Format | 6–7 | `C1 32` | Option# = 12 (delta `C`=12, len `1`), Value = `0x32` = 50 (application/json) |
| Payload Marker | 8 | `FF` | 0xFF |
| Payload | 9–… | `7B 22 76 61 …` | `{"value": 76.116, "unit": "C", "ts": "…"}` (72 B) |

---

### Observe Notification

Source hex:
`62 45 7A 05 54 C4 60 61 32 FF 7B 22 76 61 6C 75 65 22 …`
(first notification shown; a subsequent notification carried Observe seq = 1)

| Field | Value |
|-------|-------|
| Observe option number | **6** |
| Observe sequence value | 0 (first notification), incrementing 1, 2, … on each 5 s push |
| Message type | ACK (initial), NON for later server-initiated pushes |
| Response code | 2.05 Content |

The Observe option (`#6`) appears before Content-Format (`#12`); in the hex its
nibble is `60` → delta 6 (option 6), length 0 (empty value ⇒ sequence 0).

---

## 4.4 AMQP Frame Annotations

**Omitted — the AMQP tasks were marked “IGNORE” in the assignment brief.**

---

*Module 2 Assignment — Real-Time Data Analytics for IoT*
