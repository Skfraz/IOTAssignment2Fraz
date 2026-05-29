"""
Module 1 Assignment — AMQP Tests (Task 3)
Do not modify this file.

Requires a running RabbitMQ instance on localhost:5672.
Start with: docker compose up -d rabbitmq
"""
import json
import time
import pytest
import pika
import pika.exceptions

from src.amqp.topology import (
    declare_topology, get_connection_params,
    EXCHANGE_TELEMETRY, EXCHANGE_DLX,
    QUEUE_ALERTS, QUEUE_TEMPERATURE, QUEUE_ALL, QUEUE_DLX, QUEUE_LINE1,
)


def rabbit_available() -> bool:
    try:
        conn = pika.BlockingConnection(get_connection_params())
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def channel():
    if not rabbit_available():
        pytest.skip("RabbitMQ not available — start with: docker compose up -d")
    conn = pika.BlockingConnection(get_connection_params())
    ch = conn.channel()
    # Clean slate — delete any leftover queues/exchanges from previous runs
    for q in [QUEUE_ALERTS, QUEUE_TEMPERATURE, QUEUE_ALL, QUEUE_DLX, QUEUE_LINE1]:
        try: ch.queue_delete(q)
        except: pass
    for ex in [EXCHANGE_TELEMETRY, EXCHANGE_DLX]:
        try: ch.exchange_delete(ex)
        except: pass
    try:
        declare_topology(ch)
    except NotImplementedError:
        pytest.skip("Topology not yet implemented (NotImplementedError)")
    yield ch
    conn.close()


class TestTopologyDeclaration:

    def test_telemetry_exchange_exists(self, channel):
        """iot.telemetry exchange must exist and be type topic."""
        # exchange_declare with passive=True raises if exchange doesn't exist
        channel.exchange_declare(EXCHANGE_TELEMETRY, exchange_type="topic",
                                 durable=True, passive=True)

    def test_dlx_exchange_exists(self, channel):
        """iot.dlx exchange must exist and be type direct."""
        channel.exchange_declare(EXCHANGE_DLX, exchange_type="direct",
                                 durable=True, passive=True)

    def test_all_queues_exist(self, channel):
        """All five queues must be declared."""
        for q in [QUEUE_ALERTS, QUEUE_TEMPERATURE, QUEUE_ALL, QUEUE_DLX, QUEUE_LINE1]:
            result = channel.queue_declare(q, passive=True)
            assert result is not None, f"Queue {q} does not exist"

    def test_alerts_queue_routing(self, channel):
        """Messages with routing key ending in .critical must reach alerts-queue."""
        channel.queue_purge(QUEUE_ALERTS)
        payload = json.dumps({"value": 91.0, "test": True}).encode()
        channel.basic_publish(
            exchange=EXCHANGE_TELEMETRY,
            routing_key="factory.line1.temperature.critical",
            body=payload,
        )
        time.sleep(0.3)
        result = channel.queue_declare(QUEUE_ALERTS, passive=True)
        assert result.method.message_count >= 1, \
            "Critical message did not reach alerts-queue"
        channel.queue_purge(QUEUE_ALERTS)

    def test_temperature_queue_routing(self, channel):
        """Messages with key *.*.temperature must reach temperature-queue."""
        channel.queue_purge(QUEUE_TEMPERATURE)
        payload = json.dumps({"value": 72.0}).encode()
        channel.basic_publish(
            exchange=EXCHANGE_TELEMETRY,
            routing_key="factory.line1.temperature",
            body=payload,
        )
        time.sleep(0.3)
        result = channel.queue_declare(QUEUE_TEMPERATURE, passive=True)
        assert result.method.message_count >= 1, \
            "Temperature message did not reach temperature-queue"
        channel.queue_purge(QUEUE_TEMPERATURE)

    def test_line1_queue_routing(self, channel):
        """Messages with key factory.line1.* must reach line1-queue."""
        channel.queue_purge(QUEUE_LINE1)
        payload = json.dumps({"value": 1.2}).encode()
        channel.basic_publish(
            exchange=EXCHANGE_TELEMETRY,
            routing_key="factory.line1.vibration",
            body=payload,
        )
        time.sleep(0.3)
        result = channel.queue_declare(QUEUE_LINE1, passive=True)
        assert result.method.message_count >= 1, \
            "Line1 message did not reach line1-queue"
        channel.queue_purge(QUEUE_LINE1)

    def test_line2_messages_not_in_line1_queue(self, channel):
        """Messages with key factory.line2.* must NOT reach line1-queue."""
        channel.queue_purge(QUEUE_LINE1)
        payload = json.dumps({"value": 68.0}).encode()
        channel.basic_publish(
            exchange=EXCHANGE_TELEMETRY,
            routing_key="factory.line2.temperature",
            body=payload,
        )
        time.sleep(0.3)
        result = channel.queue_declare(QUEUE_LINE1, passive=True)
        assert result.method.message_count == 0, \
            "Line2 message should NOT be in line1-queue"

    def test_dlx_routing(self, channel):
        """NACKed messages (requeue=False) must reach dead-letter-queue."""
        channel.queue_purge(QUEUE_ALL)
        channel.queue_purge(QUEUE_DLX)

        payload = json.dumps({"value": 72.0, "test_dlx": True}).encode()
        channel.basic_publish(
            exchange=EXCHANGE_TELEMETRY,
            routing_key="factory.line1.temperature",
            body=payload,
            properties=pika.BasicProperties(delivery_mode=2),
        )
        time.sleep(0.3)

        # Consume and NACK with requeue=False
        method, props, body = channel.basic_get(QUEUE_ALL, auto_ack=False)
        if method is None:
            pytest.skip("No message in all-telemetry-queue to test DLX routing")
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        time.sleep(0.5)

        dlx_result = channel.queue_declare(QUEUE_DLX, passive=True)
        assert dlx_result.method.message_count >= 1, \
            "NACKed message (requeue=False) should be in dead-letter-queue"
        channel.queue_purge(QUEUE_DLX)
