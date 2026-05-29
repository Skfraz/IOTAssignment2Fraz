"""
Module 1 Assignment — Task 2.2
CoAP Observer Client

Complete all TODO sections.

Run with:  python -m src.coap.observer
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

import aiocoap
from aiocoap import Message, Code

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
log = logging.getLogger(__name__)

SERVER_BASE = "coap://localhost"
OBSERVE_DURATION = 60   # seconds before clean deregister


class FactoryObserver:
    """Observes CoAP sensor resources and reassembles Block2 transfers."""

    def __init__(self):
        self._ctx = None
        self._last_seq: dict[str, int] = {}     # uri -> last observe sequence number
        self._stale_count: dict[str, int] = {}  # uri -> stale notification count

    # ── Setup ──────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Create the aiocoap client context."""
        self._ctx = await aiocoap.Context.create_client_context()

    async def stop(self) -> None:
        """Clean up the context."""
        if self._ctx:
            await self._ctx.shutdown()

    # ── Observation ────────────────────────────────────────────────────────────

    async def observe_resource(self, uri: str) -> None:
        """
        Subscribe to a single observable CoAP resource for OBSERVE_DURATION seconds,
        then deregister cleanly.
        """
        self._last_seq.setdefault(uri, -1)
        self._stale_count.setdefault(uri, 0)

        request = Message(code=Code.GET, uri=uri, observe=0)   # observe=0 -> register
        pr = self._ctx.request(request)

        # First (initial) response carries the current state.
        first = await pr.response
        self._handle_notification(uri, first)
        log.info("Registered Observe on %s", uri)

        async def _consume() -> None:
            async for response in pr.observation:
                self._handle_notification(uri, response)

        try:
            # Run the notification stream for OBSERVE_DURATION, then stop.
            await asyncio.wait_for(_consume(), timeout=OBSERVE_DURATION)
        except asyncio.TimeoutError:
            pass
        finally:
            pr.observation.cancel()                            # Observe = 1 (deregister)
            log.info("Deregistered from %s", uri)

    def _handle_notification(self, uri: str, response: Message) -> None:
        """
        Process a single Observe notification, detecting stale (re-ordered) ones.
        """
        seq  = response.opt.observe
        last = self._last_seq.get(uri, -1)

        # RFC 7641 ordering: a notification is fresh if its 24-bit sequence number
        # is "newer" than the last seen one (with wrap-around at 2^24).
        if seq is not None and last >= 0 and not self._is_newer(seq, last):
            self._stale_count[uri] = self._stale_count.get(uri, 0) + 1
            log.warning("STALE notification on %s: seq=%s <= last=%s", uri, seq, last)
            return

        if seq is not None:
            self._last_seq[uri] = seq

        try:
            data = json.loads(response.payload)
            value, unit, ts = data.get("value"), data.get("unit", ""), data.get("ts", "")
        except (ValueError, TypeError):
            value, unit, ts = response.payload, "", ""

        arrival = datetime.now(timezone.utc).isoformat()
        log.info("[OBSERVE] %s  seq=%s  val=%s %s  @ %s (arrived %s)",
                 uri, seq, value, unit, ts, arrival)

    @staticmethod
    def _is_newer(seq: int, last: int) -> bool:
        """RFC 7641 §3.4 freshness test over the 24-bit Observe sequence space."""
        return (last < seq <= last + 0x800000) or (seq < last - 0x800000)

    # ── Block2 Transfer ────────────────────────────────────────────────────────

    async def fetch_manifest(self) -> None:
        """
        GET /factory/manifest and report the reassembled Block2 transfer.
        """
        request  = Message(code=Code.GET, uri=f"{SERVER_BASE}/factory/manifest")
        response = await self._ctx.request(request).response

        total = len(response.payload)
        log.info("Manifest received: %d bytes", total)

        try:
            data = json.loads(response.payload)
            if isinstance(data, dict):
                entries = data.get("entries", data)
                count = len(entries) if isinstance(entries, (list, dict)) else len(data)
            else:
                count = len(data)
        except (ValueError, TypeError):
            count = 0
        log.info("Firmware entries in manifest: %d", count)

        # Estimate block count from the negotiated Block2 size (SZX -> 2^(SZX+4) bytes).
        block2 = response.opt.block2
        if block2 is not None:
            block_size = block2.size
            n_blocks   = -(-total // block_size)   # ceil division
            log.info("Block2 size=%d B → %d blocks received", block_size, n_blocks)
        log.info("Block2 transfer complete")

    # ── Run ────────────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """
        TODO 4: Run all observations concurrently, then fetch the manifest.
        Requirements:
          - Start observe_resource for both:
              coap://localhost/factory/line1/temperature
              coap://localhost/factory/line2/temperature
          - Run them concurrently using asyncio.gather
          - After both complete (OBSERVE_DURATION seconds), call fetch_manifest
          - Print a final summary: stale notification counts per URI
        """
        await self.start()
        try:
            await asyncio.gather(
                self.observe_resource(f"{SERVER_BASE}/factory/line1/temperature"),
                self.observe_resource(f"{SERVER_BASE}/factory/line2/temperature"),
            )
            await self.fetch_manifest()

            print("\n── Observation Summary ──────────────────")
            for uri, count in self._stale_count.items():
                print(f"{uri:<48}  stale notifications: {count}")
            print("─────────────────────────────────────────")
        finally:
            await self.stop()


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    observer = FactoryObserver()
    asyncio.run(observer.run())
