"""
Module 1 Assignment — Task 1.1
MQTT Sensor Publisher

Complete all TODO sections. Do not modify the function signatures
or the SensorReading dataclass — the tests depend on them.
"""

import json
import logging
import random
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

import paho.mqtt.client as mqtt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
BROKER_HOST = "localhost"
BROKER_PORT = 1883
CLIENT_ID   = "smartfactory-publisher-001"

LINES   = ["line1", "line2"]
SENSORS = {
    "temperature": {"unit": "C",    "base": 70.0, "noise": 3.0,  "qos": 1},
    "vibration":   {"unit": "mm/s", "base": 1.2,  "noise": 0.3,  "qos": 0},
    "power":       {"unit": "kW",   "base": 45.0, "noise": 5.0,  "qos": 2},
}

CRITICAL_TEMP_THRESHOLD = 85.0


@dataclass
class SensorReading:
    line:      str
    sensor:    str
    value:     float
    unit:      str
    timestamp: str
    seq:       int


class SmartFactoryPublisher:
    """Publishes simulated sensor data for the SmartFactory assignment."""

    def __init__(self, broker_host: str = BROKER_HOST, broker_port: int = BROKER_PORT):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self._seq: dict[str, int] = {}          # per-topic sequence counter
        self._client: Optional[mqtt.Client] = None

    # ── Connection ─────────────────────────────────────────────────────────────

    def _build_client(self) -> mqtt.Client:
        """
        Create and configure the MQTT client with a persistent session and LWT.
          - Use CLIENT_ID as the client identifier
          - clean_session=False for a persistent session (Clean Session = 0)
          - Register on_connect / on_publish callbacks
          - Last Will and Testament: factory/line1/status -> "offline", QoS 1, retain
            (paho supports one LWT per client; tests verify line1)
        """
        client = mqtt.Client(client_id=CLIENT_ID, clean_session=False)
        client.on_connect = self.on_connect
        client.on_publish = self.on_publish
        # Last Will and Testament — broker publishes this if we disconnect ungracefully.
        client.will_set(f"factory/{LINES[0]}/status", payload="offline", qos=1, retain=True)
        return client

    def connect(self) -> None:
        """
        Connect to the broker, start the network loop, and announce 'online'.
          - Start the network loop (loop_start)
          - Wait up to 5 seconds for the connection to establish
          - Publish a retained 'online' message to factory/{line}/status (QoS 1)
        """
        self._client = self._build_client()
        self._client.connect(self.broker_host, self.broker_port, keepalive=60)
        self._client.loop_start()

        # Wait up to 5 s for the CONNACK before publishing the online status.
        deadline = time.time() + 5.0
        while not self._client.is_connected() and time.time() < deadline:
            time.sleep(0.05)
        if not self._client.is_connected():
            log.warning("Connection not confirmed within 5 s; publishing anyway")

        for line in LINES:
            self._client.publish(f"factory/{line}/status", "online", qos=1, retain=True)
            log.info("[%s/status] online (retained)", line)

    def disconnect(self) -> None:
        """Cleanly disconnect: publish 'offline' retained for each line, then stop."""
        if self._client is None:
            return
        for line in LINES:
            self._client.publish(f"factory/{line}/status", "offline", qos=1, retain=True)
        self._client.loop_stop()
        self._client.disconnect()
        log.info("Disconnected cleanly")

    # ── Callbacks ──────────────────────────────────────────────────────────────

    def on_connect(self, client, userdata, flags, rc: int) -> None:
        """
        On-connect callback: log success or refusal.
        """
        if rc == 0:
            log.info("Connected (rc=%s)", rc)
        else:
            log.error("Connection refused: %s", rc)

    def on_publish(self, client, userdata, mid: int) -> None:
        """On-publish callback: a PUBACK/PUBCOMP was received for this mid."""
        log.debug("PUBACK received for mid=%s", mid)

    # ── Sensor Simulation ──────────────────────────────────────────────────────

    def _simulate_reading(self, line: str, sensor: str) -> SensorReading:
        """Generate a realistic simulated sensor reading with Gaussian noise."""
        cfg   = SENSORS[sensor]
        value = round(cfg["base"] + random.gauss(0, cfg["noise"]), 3)
        key   = f"{line}/{sensor}"
        self._seq[key] = self._seq.get(key, 0) + 1
        return SensorReading(
            line=line,
            sensor=sensor,
            value=value,
            unit=cfg["unit"],
            timestamp=datetime.now(timezone.utc).isoformat(),
            seq=self._seq[key],
        )

    def _topic(self, line: str, sensor: str) -> str:
        """
        Return the MQTT topic for a (line, sensor): factory/{line}/{sensor}.
        """
        return f"factory/{line}/{sensor}"

    # ── Publishing ─────────────────────────────────────────────────────────────

    def publish_reading(self, line: str, sensor: str) -> SensorReading:
        """
        Simulate a reading and publish it at the sensor's configured QoS level.
        Returns the SensorReading (used by the tests).
        """
        reading = self._simulate_reading(line, sensor)
        topic   = self._topic(line, sensor)
        qos     = SENSORS[sensor]["qos"]
        payload = json.dumps(asdict(reading))

        self._client.publish(topic, payload, qos=qos, retain=False)
        log.info(
            "[%s/%s] value=%s %s  QoS=%s  seq=%s",
            line, sensor, reading.value, reading.unit, qos, reading.seq,
        )
        return reading

    # ── Main Loop ──────────────────────────────────────────────────────────────

    def run(self, interval_s: float = 1.0) -> None:
        """Continuously publish all sensors until interrupted."""
        self.connect()
        log.info("Publishing started (Ctrl-C to stop)")
        try:
            while True:
                for line in LINES:
                    for sensor in SENSORS:
                        self.publish_reading(line, sensor)
                time.sleep(interval_s)
        except KeyboardInterrupt:
            log.info("Shutting down…")
        finally:
            self.disconnect()


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    pub = SmartFactoryPublisher()
    pub.run()
