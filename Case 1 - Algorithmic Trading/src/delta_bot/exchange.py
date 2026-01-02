"""Gateway + scorekeeper adapters for the Notre Dame Delta Exchange."""

from __future__ import annotations

import asyncio
import itertools
import logging
import os
import struct
import time
from typing import Callable, Dict, List, Optional

import httpx
from exchange_sdk import ExchangeClient as BaseGatewayClient
from exchange_sdk.client import GatewayConfig, MarketDataConfig, ORDER_FMT

from . import config
from .models import (
    MarketLevel,
    MarketSnapshot,
    OrderBook,
    OrderInfo,
    OrderLevel,
    Side,
)

_LOGGER = logging.getLogger(__name__)


class StreamingGatewayClient(BaseGatewayClient):
    """Extends the SDK client so we can surface fills to strategy code."""

    RESPONSE_SIZE = 64

    def __init__(self, *args, fill_callback: Callable[[dict], None] | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._fill_callbacks: List[Callable[[dict], None]] = []
        if fill_callback:
            self._fill_callbacks.append(fill_callback)

    def add_fill_callback(self, callback: Callable[[dict], None]) -> None:
        self._fill_callbacks.append(callback)

    async def _read_responses(self) -> None:  # type: ignore[override]
        if not self._tcp_reader:
            _LOGGER.warning("Gateway reader missing when response loop started")
            return
        try:
            while True:
                try:
                    frame = await self._tcp_reader.readexactly(self.RESPONSE_SIZE)
                    self._handle_response_frame(frame)
                except asyncio.IncompleteReadError as exc:
                    if len(exc.partial) == 0:
                        _LOGGER.info("Gateway closed connection")
                        break
                    _LOGGER.warning(
                        "incomplete response frame: received %s bytes", len(exc.partial)
                    )
        except (ConnectionResetError, EOFError) as exc:
            _LOGGER.info("gateway connection closed: %s", exc.__class__.__name__)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # pragma: no cover - defensive logging
            _LOGGER.error("gateway response loop error: %s", exc)

    def _handle_response_frame(self, frame: bytes) -> None:
        if not self._fill_callbacks:
            return
        try:
            unpacked = struct.unpack(ORDER_FMT, frame)
        except struct.error as exc:
            _LOGGER.debug("response unpack failed: %s", exc)
            return
        msg_type = unpacked[6]
        if msg_type != 2:  # 2 == fill/execute
            return
        payload = {
            "client_id": unpacked[0],
            "order_id": unpacked[1],
            "symbol_id": unpacked[2],
            "side": unpacked[3],
            "price_ticks": unpacked[7],
            "quantity": abs(unpacked[8]),
        }
        for callback in list(self._fill_callbacks):
            try:
                callback(payload)
            except Exception:  # pragma: no cover - defensive logging
                _LOGGER.exception("fill callback failed")


class ExchangeClient:
    """Bridges the competition gateway SDK with our strategy interface."""

    def __init__(self, team_token: Optional[str] = None) -> None:
        token = team_token or os.getenv(config.TEAM_TOKEN_ENV) or config.DEFAULT_TEAM_TOKEN
        if not token:
            raise RuntimeError(
                "Team token is required. Set DELTA_TOKEN or pass team_token explicitly."
            )

        gateway_cfg = GatewayConfig(host=config.EXCHANGE_HOST, port=config.GATEWAY_PORT)
        market_cfg = MarketDataConfig(host=config.EXCHANGE_HOST, port=config.MARKET_DATA_PORT)

        self._fill_handlers: list[Callable[[str, Side, int, float], None]] = []
        self._gateway = StreamingGatewayClient(
            team_token=token,
            gateway=gateway_cfg,
            market_data=market_cfg,
            fill_callback=self._on_gateway_fill,
        )
        self._http = httpx.AsyncClient(
            base_url=config.SCOREKEEPER_BASE_URL,
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )
        self._client_ids = itertools.count(1)
        self._order_client_map: Dict[int, int] = {}
        self._order_symbol_map: Dict[int, int] = {}

    async def __aenter__(self) -> "ExchangeClient":
        await self._gateway.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        await self._gateway.close()
        await self._http.aclose()

    async def get_order_book(self, symbol: str, depth: int = 10) -> MarketSnapshot:
        response = await self._http.get(f"/orderbook/{symbol}", params={"depth": depth})
        response.raise_for_status()
        data = response.json()
        order_book = OrderBook(
            bids=[self._to_level(entry) for entry in data.get("bids", [])[:depth]],
            asks=[self._to_level(entry) for entry in data.get("asks", [])[:depth]],
        )
        return MarketSnapshot(symbol=symbol, order_book=order_book, timestamp=time.time())

    async def place_order(self, level: OrderLevel) -> OrderInfo:
        client_id = next(self._client_ids)
        symbol_id = config.SYMBOL_IDS[level.symbol]
        price_ticks = self._price_to_ticks(level.price)
        side = 0 if level.side is Side.BID else 1
        order_id = await self._gateway.send_new_async(
            client_id=client_id,
            symbol_id=symbol_id,
            side=side,
            price_ticks=price_ticks,
            quantity=level.size,
        )
        self._order_client_map[order_id] = client_id
        self._order_symbol_map[order_id] = symbol_id
        return OrderInfo(
            symbol=level.symbol,
            side=level.side,
            level_index=level.level_index,
            price=level.price,
            size=level.size,
            order_id=str(order_id),
        )

    async def cancel_order(self, order_id: str) -> None:
        order_int = int(order_id)
        client_id = self._order_client_map.get(order_int, order_int)
        symbol_id = self._order_symbol_map.get(order_int, config.SYMBOL_IDS[config.ETF_SYMBOL])
        await self._gateway.cancel_order_async(
            client_id=client_id,
            order_id=order_int,
            symbol_id=symbol_id,
        )
        self._order_client_map.pop(order_int, None)
        self._order_symbol_map.pop(order_int, None)

    async def replace_order(self, order_id: str, level: OrderLevel) -> OrderInfo:
        await self.cancel_order(order_id)
        return await self.place_order(level)

    def register_fill_handler(self, handler: Callable[[str, Side, int, float], None]) -> None:
        self._fill_handlers.append(handler)

    def _to_level(self, entry: dict) -> MarketLevel:
        price = float(entry.get("price", entry.get("p", 0.0)))
        size_value = entry.get("quantity") or entry.get("qty") or entry.get("size") or 0
        size = int(size_value)
        return MarketLevel(price=price, size=size)

    def _price_to_ticks(self, price: float) -> int:
        return int(round(price * config.ORDER_PRICE_SCALE))

    def _on_gateway_fill(self, payload: dict) -> None:
        symbol = config.ID_TO_SYMBOL.get(payload.get("symbol_id"))
        if symbol is None:
            return
        quantity = int(payload.get("quantity", 0))
        if quantity <= 0:
            return
        side = Side.BID if int(payload.get("side", 0)) == 0 else Side.ASK
        price_ticks = int(payload.get("price_ticks", 0))
        price = price_ticks / config.ORDER_PRICE_SCALE
        for handler in list(self._fill_handlers):
            try:
                handler(symbol, side, quantity, price)
            except Exception:  # pragma: no cover - defensive logging
                _LOGGER.exception("fill handler failed")

__all__ = ["ExchangeClient"]
