#!/usr/bin/env bash
# setup.sh — Module 1 Assignment Environment Setup
# Run once before starting the assignment: bash setup.sh

set -e
echo "=================================================="
echo " SmartFactory IoT Assignment — Environment Setup"
echo "=================================================="
echo ""

# ── Python dependencies ────────────────────────────────────────────────────────
echo "[1/4] Installing Python dependencies..."
pip install --quiet \
    paho-mqtt>=1.6.1 \
    aiocoap[all]>=0.4.7 \
    pika>=1.3.2 \
    influxdb-client>=1.38.0 \
    pytest>=7.4.0 \
    pytest-asyncio>=0.21.0 \
    pytest-timeout>=2.1.0

echo "      Python packages installed."

# ── Docker services ────────────────────────────────────────────────────────────
echo ""
echo "[2/4] Starting Docker services (Mosquitto + RabbitMQ)..."
if command -v docker &>/dev/null && docker compose version &>/dev/null 2>&1; then
    docker compose up -d mosquitto rabbitmq
    echo "      Waiting for services to be ready..."
    sleep 4

    # Verify Mosquitto
    if docker compose exec -T mosquitto mosquitto_sub -h localhost -p 1883 -t '$SYS/broker/version' -C 1 -W 3 &>/dev/null 2>&1; then
        echo "      Mosquitto MQTT broker: READY on port 1883"
    else
        echo "      Mosquitto MQTT broker: starting (may take a moment)..."
    fi

    # Verify RabbitMQ
    if docker compose exec -T rabbitmq rabbitmq-diagnostics ping &>/dev/null 2>&1; then
        echo "      RabbitMQ AMQP broker:  READY on port 5672"
        echo "      RabbitMQ Management:   http://localhost:15672  (guest/guest)"
    else
        echo "      RabbitMQ:              starting (may take ~30 s on first run)..."
    fi
else
    echo "      Docker not found. Install Docker and re-run, or start brokers manually."
    echo "      Manual setup:"
    echo "        Mosquitto: mosquitto -c config/mosquitto.conf"
    echo "        RabbitMQ:  rabbitmq-server"
fi

# ── Python path ────────────────────────────────────────────────────────────────
echo ""
echo "[3/4] Checking Python path..."
if [ ! -f "src/__init__.py" ]; then
    touch src/__init__.py
    touch src/mqtt/__init__.py
    touch src/coap/__init__.py
    touch src/amqp/__init__.py
    touch tests/__init__.py
    touch tests/mqtt/__init__.py
    touch tests/coap/__init__.py
    touch tests/amqp/__init__.py
fi
echo "      __init__.py files created."

# ── Sanity check ───────────────────────────────────────────────────────────────
echo ""
echo "[4/4] Running sanity checks..."
python -c "import paho.mqtt.client; print('      paho-mqtt:', paho.mqtt.client.__file__.split('site-packages/')[-1])"
python -c "import aiocoap; print('      aiocoap:  ', aiocoap.__version__)"
python -c "import pika; print('      pika:     ', pika.__version__)"

echo ""
echo "=================================================="
echo " Setup complete!"
echo ""
echo " Next steps:"
echo "   1. Read the assignment document (Module1_Assignment.docx)"
echo "   2. Complete src/mqtt/publisher.py  (Task 1.1)"
echo "   3. Complete src/mqtt/subscriber.py  (Task 1.2)"
echo "   4. Run tests:  pytest tests/ -v"
echo ""
echo " Useful URLs:"
echo "   RabbitMQ Management: http://localhost:15672  (guest/guest)"
echo "   InfluxDB (optional): http://localhost:8086   (start: docker compose --profile optional up -d)"
echo "=================================================="
