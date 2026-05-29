"""
Module 1 Assignment — Task 3.1
AMQP Broker Topology Declaration

Complete all TODO sections. Run this module once to set up the
RabbitMQ topology before running producer or consumer.

Run with:  python -m src.amqp.topology
"""

import logging
import ssl
import pika

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
log = logging.getLogger(__name__)

# ── Connection parameters ─────────────────────────────────────────────────────
BROKER_HOST   = "localhost"
BROKER_PORT   = 5672          # plain AMQP (use 5671 for TLS in Tasks 3.2/3.3)
VHOST         = "/"
CREDENTIALS   = pika.PlainCredentials("guest", "guest")


def get_connection_params(host=BROKER_HOST, port=BROKER_PORT) -> pika.ConnectionParameters:
    return pika.ConnectionParameters(
        host=host, port=port,
        virtual_host=VHOST,
        credentials=CREDENTIALS,
        heartbeat=60,
    )


# ── Exchange names ─────────────────────────────────────────────────────────────
EXCHANGE_TELEMETRY = "iot.telemetry"   # main topic exchange
EXCHANGE_DLX       = "iot.dlx"         # dead letter exchange

# ── Queue names ────────────────────────────────────────────────────────────────
QUEUE_ALERTS      = "alerts-queue"
QUEUE_TEMPERATURE = "temperature-queue"
QUEUE_ALL         = "all-telemetry-queue"
QUEUE_DLX         = "dead-letter-queue"
QUEUE_LINE1       = "line1-queue"


def declare_topology(channel: pika.adapters.blocking_connection.BlockingChannel) -> None:
    """
    Declare all exchanges, queues, and bindings for the SmartFactory topology.
    This function is idempotent — safe to call multiple times.
    """

    # ── Exchanges ─────────────────────────────────────────────────────────────

    # Main topic exchange for all sensor telemetry.
    channel.exchange_declare(EXCHANGE_TELEMETRY, exchange_type="topic", durable=True)

    # Dead Letter Exchange (direct) — failed / expired / overflowed messages land here.
    channel.exchange_declare(EXCHANGE_DLX, exchange_type="direct", durable=True)

    # ── Dead Letter Queue (declare before queues that reference it) ────────────

    channel.queue_declare(QUEUE_DLX, durable=True)
    channel.queue_bind(QUEUE_DLX, EXCHANGE_DLX, routing_key="dead")

    # ── Application Queues ────────────────────────────────────────────────────

    # alerts-queue — every critical reading (routing key ending in .critical).
    channel.queue_declare(QUEUE_ALERTS, durable=True)
    channel.queue_bind(QUEUE_ALERTS, EXCHANGE_TELEMETRY, routing_key="#.critical")

    # temperature-queue — all temperature readings; 60 s TTL, dead-letters to iot.dlx.
    channel.queue_declare(
        QUEUE_TEMPERATURE, durable=True,
        arguments={
            "x-message-ttl": 60000,
            "x-dead-letter-exchange": EXCHANGE_DLX,
            "x-dead-letter-routing-key": "dead",
        },
    )
    channel.queue_bind(QUEUE_TEMPERATURE, EXCHANGE_TELEMETRY, routing_key="*.*.temperature")

    # all-telemetry-queue — everything under factory.*; bounded to 10000 msgs,
    # overflow + rejected messages dead-letter to iot.dlx with routing key "dead".
    channel.queue_declare(
        QUEUE_ALL, durable=True,
        arguments={
            "x-max-length": 10000,
            "x-overflow": "dead-letter",
            "x-dead-letter-exchange": EXCHANGE_DLX,
            "x-dead-letter-routing-key": "dead",
        },
    )
    channel.queue_bind(QUEUE_ALL, EXCHANGE_TELEMETRY, routing_key="factory.#")

    # line1-queue — only line1 telemetry.
    channel.queue_declare(QUEUE_LINE1, durable=True)
    channel.queue_bind(QUEUE_LINE1, EXCHANGE_TELEMETRY, routing_key="factory.line1.#")

    log.info("Topology declared successfully")


def setup() -> None:
    """Connect to RabbitMQ and declare the full topology."""
    params = get_connection_params()
    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    try:
        declare_topology(channel)
    finally:
        connection.close()
    log.info("Topology setup complete. Check: http://localhost:15672")


if __name__ == "__main__":
    setup()
