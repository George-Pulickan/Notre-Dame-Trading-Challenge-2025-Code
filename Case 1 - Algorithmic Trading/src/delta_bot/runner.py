"""Entrypoint for launching the Delta Exchange bot."""

from __future__ import annotations

import asyncio
import logging

from .exchange import ExchangeClient
from .strategy import Strategy


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    async with ExchangeClient() as client:
        strategy = Strategy(client)
        await strategy.run()


def cli() -> None:
    asyncio.run(main())


if __name__ == "__main__":  # pragma: no cover
    cli()
