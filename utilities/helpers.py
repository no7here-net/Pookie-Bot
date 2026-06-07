import asyncio
import json
import os

from mcrcon import MCRcon

def load_config():
    with open("config.json", "r") as f:
        return json.load(f)

config = load_config()

# Check for if user is a bot admin
def is_admin(user_id: int) -> bool:
    return user_id in config.get("admins", [])

# Fetch emoji ID by name
def get_emoji(name: str) -> str:
    return config.get("customisation", {}).get("emojis", {}).get(name, "")

# Fetch HEX colours and convert to integers for discord.py
def get_colour(name: str) -> int:
    return int(config.get("customisation", {}).get("colours", {}).get(name, "2fbffd"), 16)

# Internal ping helper function
async def _ping_host(host: str, port: int) -> bool:
    try:
        # Creates a background process: ping -c 1 <host>
        process = await asyncio.create_subprocess_exec(
            "ping", "-c", "4", host,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await process.wait()
        return process.returncode == 0
    except Exception:
        return False

# Check Cloudflare DNS & Google DNS for internet connectivity
async def check_internet() -> bool:
    results = await asyncio.gather(
        _ping_host("1.1.1.1", 53),
        _ping_host("8.8.8.8", 53)
    )

    # Return true if at least one is true
    return any(results)

# async def check_host() -> bool:
#     ssh_configs = config.get("auth", {}).get("ssh", [])

#     for server in ssh_configs:
#         process = await asyncio.create_subprocess_exec("ping", param, "1", host, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)

#         await process.wait()

#         return process.returncode == 0
