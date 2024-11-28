import asyncio

async def trade_with_timeout(trade_state):
    """Handles trading logic with a 5-minute timeout."""

    start_time = asyncio.get_event_loop().time()
    trade_duration = 300  # 5 minutes in seconds

    while trade_state['running'] and asyncio.get_event_loop().time() - start_time < trade_duration:
        # Simulate trading logic (replace this with your actual logic)
        print("Trading cycle...")
        await asyncio.sleep(1)  # Simulates a trading cycle delay

    print("Trade completed or stopped manually")
    trade_state['running'] = False
