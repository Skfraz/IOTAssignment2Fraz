"""
Module 1 Assignment — Task 3.2
AMQP Producer with Publisher Confirms

Complete all TODO sections.
"""

import json
import logging
import random
import ssl
import time
from datetime import datetime, timezone

import pika
import pika.exceptions

from src.amqp.topology import (
    EXCHANGE_TELEMETRY, QUEUE_TEMPERATURE,
    get_connection_params
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
log = logging.getLogger(__name__)

CRITICAL_THRESHOLD = 85.0

SENSOR_CONFIG = {
    "temperature": {"unit": "C",    "base": 70.0, "noise": 3.0,  "persistent": True},
    "vibration":   {"unit": "mm/s", "base": 1.2,  "noise": 0.3,  "persistent": False},
    "power":       {"unit": "kW",   "base": 45.0, "noise": 5.0,  "persistent": True},
}
LINES = ["line1", "line2"]


class SmartFactoryProducer:

    def __init__(self):
        self._connection = None
        self._channel    = None
        self._published  = 0
        self._confirmed  = 0
        self._unconfirmed: set[int] = set()

    # ── Connection ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """
        Connect to RabbitMQ and enable Publisher Confirms on the channel.

        pika's BlockingConnection implements confirms synchronously: after
        confirm_delivery(), each basic_publish blocks until the broker returns a
        Basic.Ack (returns normally) or a Basic.Nack / unroutable-return (raises),
        rather than via async ack/nack callbacks. We also register a return
        callback so mandatory, unroutable messages are surfaced.
        """
        self._connection = pika.BlockingConnection(get_connection_params())
        self._channel = self._connection.channel()
        self._channel.confirm_delivery()                 # enable Publisher Confirms
        self._channel.add_on_return_callback(self.on_return)
        log.info("Producer connected; Publisher Confirms enabled")

    def disconnect(self) -> None:
        if self._connection and not self._connection.is_closed:
            self._connection.close()
        log.info("Producer stats — published: %d  confirmed: %d  unconfirmed: %d",
                 self._published, self._confirmed, len(self._unconfirmed))

    # ── Callbacks ──────────────────────────────────────────────────────────────

    def on_delivery_confirmed(self, method_frame) -> None:
        """
        Record a broker confirm (Basic.Ack / Basic.Nack) by delivery tag.

        With the blocking adapter the confirm is observed inline in
        publish_reading(); this helper centralises the bookkeeping/logging so the
        same logic could also serve an asynchronous (SelectConnection) adapter.
        """
        tag = getattr(getattr(method_frame, "method", method_frame), "delivery_tag", None)
        is_ack = isinstance(getattr(method_frame, "method", method_frame), pika.spec.Basic.Ack) \
            if hasattr(method_frame, "method") else True
        if is_ack:
            log.info("CONFIRM ack delivery_tag=%s", tag)
            self._confirmed += 1
            self._unconfirmed.discard(tag)
        else:
            log.warning("CONFIRM nack (LOST) delivery_tag=%s", tag)

    def on_return(self, channel, method, properties, body) -> None:
        """Mandatory message with no matching queue was returned by the broker."""
        log.warning("RETURNED (no route): routing_key=%s reply=%s",
                    method.routing_key, method.reply_text)

    # ── Routing Key ────────────────────────────────────────────────────────────

    def _routing_key(self, line: str, sensor: str, value: float) -> str:
        """
        Build the AMQP routing key, appending '.critical' for hot temperatures.
        """
        key = f"factory.{line}.{sensor}"
        if sensor == "temperature" and value > CRITICAL_THRESHOLD:
            key += ".critical"
        return key

    # ── Publishing ─────────────────────────────────────────────────────────────

    def publish_reading(self, line: str, sensor: str) -> dict:
        """
        Simulate and publish a sensor reading with Publisher Confirms.
        """
        cfg   = SENSOR_CONFIG[sensor]
        value = round(cfg["base"] + random.gauss(0, cfg["noise"]), 3)
        mode  = 2 if cfg["persistent"] else 1
        key   = self._routing_key(line, sensor, value)

        # per-(line,sensor) sequence counter
        if not hasattr(self, "_seqs"):
            self._seqs = {}
        skey = f"{line}/{sensor}"
        self._seqs[skey] = self._seqs.get(skey, 0) + 1

        payload = {
            "value": value, "unit": cfg["unit"], "line": line, "sensor": sensor,
            "timestamp": datetime.now(timezone.utc).isoformat(), "seq": self._seqs[skey],
        }
        props = pika.BasicProperties(
            delivery_mode=mode,
            expiration="60000",                 # 60 s message TTL
            content_type="application/json",
            timestamp=int(time.time()),
        )

        tag = self._published + 1               # broker assigns confirm tags sequentially
        self._unconfirmed.add(tag)
        self._published += 1
        try:
            self._channel.basic_publish(
                exchange=EXCHANGE_TELEMETRY, routing_key=key,
                body=json.dumps(payload).encode(), properties=props, mandatory=True,
            )
            # Returned normally → broker confirmed (Basic.Ack).
            self._confirmed += 1
            self._unconfirmed.discard(tag)
            log.info("[%s]  val=%.2f %s  delivery_mode=%d  (confirmed tag=%d)",
                     key, value, cfg["unit"], mode, tag)
        except pika.exceptions.UnroutableError:
            log.warning("[%s] UNROUTABLE (returned) tag=%d", key, tag)
        except pika.exceptions.NackError:
            log.warning("CONFIRM nack (LOST) delivery_tag=%d", tag)
        return payload

    # ── Main Loop ──────────────────────────────────────────────────────────────

    def run(self, interval_s: float = 1.0) -> None:
        self.connect()
        seq = 0
        try:
            while True:
                seq += 1
                for line in LINES:
                    for sensor in SENSOR_CONFIG:
                        self.publish_reading(line, sensor)
                self._channel.connection.process_data_events()  # flush confirms
                time.sleep(interval_s)
        except KeyboardInterrupt:
            log.info("Shutting down…")
        finally:
            self.disconnect()


if __name__ == "__main__":
    producer = SmartFactoryProducer()
    producer.run()
