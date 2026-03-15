"""
Liquidation data from Coinglass API.
Liquidation stats, heatmap zones, open interest, long/short ratio.
"""
import aiohttp
import asyncio
from config import COINGLASS_API_KEY

BASE_URL = "https://open-api-v3.coinglass.com/api"
HEADERS = {
    "accept": "application/json",
    "CG-API-KEY": COINGLASS_API_KEY,
}


def _run_async(coro):
    """Run async coroutine synchronously."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


async def _fetch(endpoint: str, params: dict = None) -> dict:
    """Fetch data from Coinglass API."""
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{BASE_URL}{endpoint}",
            headers=HEADERS,
            params=params or {},
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("data", data)
            return {"error": f"HTTP {resp.status}", "body": await resp.text()}


def get_liquidations(symbol: str) -> dict:
    """Recent liquidation stats: long/short amounts."""
    symbol_clean = symbol.replace("USDT", "")

    async def _get():
        data = await _fetch("/futures/liquidation/detail", {"symbol": symbol_clean, "timeType": "1"})
        return data

    result = _run_async(_get())
    if isinstance(result, dict) and "error" in result:
        return {"symbol": symbol, "error": result["error"], "available": False}

    return {
        "symbol": symbol,
        "data": result,
        "available": True,
    }


def get_open_interest(symbol: str) -> dict:
    """Open interest current value and changes."""
    symbol_clean = symbol.replace("USDT", "")

    async def _get():
        return await _fetch("/futures/openInterest/ohlc-history", {"symbol": symbol_clean, "interval": "1h", "limit": 24})

    result = _run_async(_get())
    if isinstance(result, dict) and "error" in result:
        return {"symbol": symbol, "error": result["error"], "available": False}

    return {
        "symbol": symbol,
        "data": result,
        "available": True,
    }


def get_long_short_ratio(symbol: str) -> dict:
    """Long/short account ratio."""
    symbol_clean = symbol.replace("USDT", "")

    async def _get():
        return await _fetch("/futures/globalLongShortAccountRatio/history", {"symbol": symbol_clean, "interval": "1h", "limit": 24})

    result = _run_async(_get())
    if isinstance(result, dict) and "error" in result:
        return {"symbol": symbol, "error": result["error"], "available": False}

    return {
        "symbol": symbol,
        "data": result,
        "available": True,
    }


def get_liquidation_heatmap(symbol: str) -> dict:
    """Liquidation heatmap — concentration zones above/below price."""
    symbol_clean = symbol.replace("USDT", "")

    async def _get():
        return await _fetch("/futures/liquidation/heatmap", {"symbol": symbol_clean, "interval": "4h"})

    result = _run_async(_get())
    if isinstance(result, dict) and "error" in result:
        return {"symbol": symbol, "error": result["error"], "available": False}

    return {
        "symbol": symbol,
        "data": result,
        "available": True,
    }
