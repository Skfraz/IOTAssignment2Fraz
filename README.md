# Module 1 Assignment — SmartFactory IoT Protocol Integration

**Real-Time Data Analytics for IoT** · Graduate Course · Module 1

---

## Quick Start

```bash
# 1. Install dependencies and start Docker services
bash setup.sh

# 2. Read the full assignment specification
open Module1_Assignment.docx

# 3. Work through the tasks in order:
#    Task 1 → src/mqtt/publisher.py  + src/mqtt/subscriber.py
#    Task 2 → src/coap/server.py     + src/coap/observer.py
#    Task 3 → src/amqp/topology.py   + src/amqp/producer.py   + src/amqp/consumer.py
#    Task 4 → bash scripts/capture.sh → annotate report/packet_analysis.md
#    Task 5 → report/comparison_report.md

# 4. Run all tests before submitting
pytest tests/ -v --tb=short
```

---

## Repository Structure

```
module1-assignment/
├── src/
│   ├── mqtt/
│   │   ├── publisher.py      ← Task 1.1  Fill in all TODO sections
│   │   └── subscriber.py     ← Task 1.2  Fill in all TODO sections
│   ├── coap/
│   │   ├── server.py         ← Task 2.1  Fill in all TODO sections
│   │   └── observer.py       ← Task 2.2  Fill in all TODO sections
│   └── amqp/
│       ├── topology.py       ← Task 3.1  Fill in all TODO sections
│       ├── producer.py       ← Task 3.2  Fill in all TODO sections
│       └── consumer.py       ← Task 3.3  Fill in all TODO sections
│
├── tests/
│   ├── mqtt/
│   │   ├── test_publisher.py   ← Do not modify
│   │   └── test_qos_loss.py    ← Do not modify (run with -s for output table)
│   ├── coap/
│   │   └── test_server.py      ← Do not modify
│   └── amqp/
│       └── test_topology.py    ← Do not modify
│
├── report/
│   ├── packet_analysis.md    ← Task 4  Fill in the annotation tables
│   └── comparison_report.md  ← Task 5  Write your analysis here
│
├── captures/                 ← Task 4  pcap files go here (git-ignored)
├── scripts/
│   └── capture.sh            ← Task 4  Run to capture traffic
├── config/
│   └── mosquitto.conf        ← Mosquitto broker configuration
├── docker-compose.yml        ← Infrastructure: Mosquitto + RabbitMQ + InfluxDB
├── requirements.txt
├── pytest.ini
└── setup.sh                  ← Run this first
```

---

## Running Individual Components

```bash
# Task 1 — MQTT
python -m src.mqtt.publisher       # Terminal 1
python -m src.mqtt.subscriber      # Terminal 2

# Task 2 — CoAP
python -m src.coap.server          # Terminal 1
python -m src.coap.observer        # Terminal 2

# Task 3 — AMQP (run in order)
python -m src.amqp.topology        # Once — sets up RabbitMQ topology
python -m src.amqp.producer        # Terminal 1
python -m src.amqp.consumer        # Terminal 2

# Task 4 — Packet capture (with publisher/server running)
bash scripts/capture.sh
```

---

## Running Tests

```bash
# All tests
pytest tests/ -v

# Individual task tests
pytest tests/mqtt/ -v
pytest tests/coap/ -v
pytest tests/amqp/ -v

# QoS experiment with output table (Task 1.3)
pytest tests/mqtt/test_qos_loss.py -v -s
```

---

## Infrastructure

| Service | Port | URL |
|---------|------|-----|
| Mosquitto MQTT | 1883 | mqtt://localhost:1883 |
| RabbitMQ AMQP | 5672 | amqp://localhost:5672 |
| RabbitMQ Management | 15672 | http://localhost:15672 (guest/guest) |
| CoAP server (Python) | 5683 | coap://localhost:5683 |
| InfluxDB (optional) | 8086 | http://localhost:8086 |

```bash
# Start all services
docker compose up -d

# Stop all services
docker compose down

# View logs
docker compose logs -f mosquitto
docker compose logs -f rabbitmq
```

---

## Submission Checklist

Before zipping and submitting:

- [ ] All 7 source files have TODO sections completed
- [ ] `pytest tests/ -v` passes (or partial passes documented)
- [ ] `captures/` contains mqtt.pcap, coap.pcap, amqp.pcap
- [ ] `report/packet_analysis.md` — all annotation tables filled in
- [ ] `report/comparison_report.md` — all sections written (1500–2000 words total)
- [ ] README.md updated with your name and any notes for the marker

---

## Notes for the Marker

**Scope.** Per the assignment brief, the **AMQP tasks (Task 3 and Task 4.4) were
ignored**. The completed work covers **Task 1 (MQTT)**, **Task 2 (CoAP)**,
**Task 4.2/4.3 (MQTT + CoAP packet analysis)** and **Task 5 (report)**. The AMQP
skeletons are left untouched, and `pytest.ini` excludes `tests/amqp` from
collection (those tests need `pika` + a running RabbitMQ broker).

**Python version.** This environment's `python3` was upgraded to 3.14 by Homebrew
mid-setup, which orphaned the installed packages. Everything was verified with
**`python3.13`** (paho-mqtt **1.6.1**, aiocoap 0.4.17, pytest **7.4.4** +
pytest-asyncio **0.21.2** — paho 1.x and that pytest-asyncio are required for the
unmodified test files to pass). Use `python3.13` to reproduce:

```bash
# 1. Start an MQTT broker on 127.0.0.1:1883
/opt/homebrew/sbin/mosquitto -c config/mosquitto.conf &

# 2. Run the in-scope test suite (MQTT + CoAP)  → 22 passed
python3.13 -m pytest tests/ -v

# 3. QoS experiment table (Task 1.3 / report §5.1)
python3.13 -m pytest tests/mqtt/test_qos_loss.py -v -s

# 4. Packet capture (Task 4) — no root needed, see below
python3.13 scripts/capture_pcap.py both
python3.13 scripts/analyze_pcap.py both       # decodes the captured bytes
```

**Packet capture method.** macOS blocks loopback capture without root (BPF) and
`tshark` was unavailable, so `scripts/capture_pcap.py` captures the **real**
MQTT/CoAP bytes by relaying the live client↔broker / client↔server exchange
through a userspace recording proxy and writing valid `.pcap` files (open them in
Wireshark). `scripts/analyze_pcap.py` decodes those pcaps into the field-by-field
breakdown used in `report/packet_analysis.md`. A raw decode is saved in
`captures/analysis_output.txt`.

**Components (manual run):**
```bash
python3.13 -m src.mqtt.publisher      # + python3.13 -m src.mqtt.subscriber
python3.13 -m src.coap.server         # + python3.13 -m src.coap.observer
```

---

*Graduate Course: Real-Time Data Analytics for IoT · Module 1*
