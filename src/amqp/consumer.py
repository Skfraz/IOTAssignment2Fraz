"""
Module 1 Assignment — Task 3.3
AMQP Consumer with Manual ACK and DLX Inspection

Complete all TODO sections.
"""

import json
import logging
import random
import time
from datetime import datetime, timezone

import pika
import pika.exceptions

from src.amqp.topology import (
    QUEUE_ALL, QUEUE_DLX,
    EXCHANGE_TELEMETRY, EXCHANGE_DLX,
    get_connection_params
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
log = logging.getLogger(__name__)

PREFETCH_COUNT   = 5
FAILURE_RATE     = 0.10          # 10% random processing failures
DLX_POLL_EVERY   = 30            # seconds between DLX queue polls


class SmartFactoryConsumer:

    def __init__(self):
        self._connection    = None
        self._channel       = None
        self._processed     = 0
        self._failed        = 0
        self._alerts_seen   = 0
        self._last_dlx_poll = time.time()

    # ── Connection ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """
        Connect to RabbitMQ, set prefetch, and register the QUEUE_ALL consumer.
        """
        self._connection = pika.BlockingConnection(get_connection_params())
        self._channel = self._connection.channel()
        self._channel.basic_qos(prefetch_count=PREFETCH_COUNT, global_qos=False)
        self._channel.basic_consume(QUEUE_ALL, on_message_callback=self.on_message,
                                    auto_ack=False)
        log.info("Consumer connected; prefetch=%d on %s", PREFETCH_COUNT, QUEUE_ALL)

    # ── Message Handler ────────────────────────────────────────────────────────

    def on_message(
        self,
        channel: pika.adapters.blocking_connection.BlockingChannel,
        method:  pika.spec.Basic.Deliver,
        props:   pika.spec.BasicProperties,
        body:    bytes,
    ) -> None:
        """
        Main message handler: alert, process (with simulated failures), and ACK/NACK.
        """
        tag = method.delivery_tag
        key = method.routing_key

        try:
            payload = json.loads(body)
        except (ValueError, TypeError):
            log.warning("Malformed message tag=%s — NACK to DLX", tag)
            channel.basic_nack(delivery_tag=tag, requeue=False)
            self._failed += 1
            return

        # Critical alerts are always processed and ACKed.
        if key.endswith(".critical"):
            self._print_critical_alert(key, payload)
            self._alerts_seen += 1
            channel.basic_ack(delivery_tag=tag)
        elif random.random() < FAILURE_RATE:
            # Simulated processing failure → dead-letter (requeue=False).
            log.warning("NACK (simulated failure) tag=%s key=%s", tag, key)
            channel.basic_nack(delivery_tag=tag, requeue=False)
            self._failed += 1
        else:
            log.info("[PROCESSED] %s  val=%s  tag=%s", key, payload.get("value"), tag)
            channel.basic_ack(delivery_tag=tag)
            self._processed += 1

        if time.time() - self._last_dlx_poll >= DLX_POLL_EVERY:
            self._poll_dlx()
            self._last_dlx_poll = time.time()

    def _print_critical_alert(self, routing_key: str, payload: dict) -> None:
        """
        Print a formatted critical temperature alert.
        """
        print("╔══════════════════════════════════════╗")
        print(f"║  ⚠ CRITICAL ALERT — {routing_key}")
        print(f"║  Temperature: {payload.get('value')}°C")
        print(f"║  Timestamp:   {payload.get('timestamp')}")
        print("╚══════════════════════════════════════╝")

    # ── DLX Inspector ─────────────────────────────────────────────────────────

    def _poll_dlx(self) -> None:
        """
        Drain and inspect all messages currently in the dead-letter-queue.
        """
        n = 0
        while True:
            method, props, body = self._channel.basic_get(QUEUE_DLX, auto_ack=True)
            if method is None:
                break
            n += 1
            try:
                payload = json.loads(body)
            except (ValueError, TypeError):
                payload = {}
            headers = (props.headers or {}) if props else {}
            xdeath = headers.get("x-death", [{}])
            first = xdeath[0] if xdeath else {}
            print(f"[DEAD LETTER] routing_key={method.routing_key}")
            print(f"  Original queue: {first.get('queue')}")
            print(f"  Death reason:   {first.get('reason')}")
            print(f"  Death count:    {first.get('count')}")
            print(f"  Value:          {payload.get('value', '?')}")
        log.info("DLX poll complete — %d dead-lettered messages inspected", n)

    # ── Run ────────────────────────────────────────────────────────────────────

    def run(self) -> None:
        self.connect()
        log.info("Consumer ready. Consuming from %s (prefetch=%d)", QUEUE_ALL, PREFETCH_COUNT)
        try:
            self._channel.start_consuming()
        except KeyboardInterrupt:
            self._channel.stop_consuming()
        finally:
            if self._connection and not self._connection.is_closed:
                self._connection.close()
            log.info("Final stats — processed: %d  failed(DLX): %d  alerts: %d",
                     self._processed, self._failed, self._alerts_seen)


if __name__ == "__main__":
    consumer = SmartFactoryConsumer()
    consumer.run()
