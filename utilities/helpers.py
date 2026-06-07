import asyncio
import json
import os

from mcrcon import MCRcon

def load_config():
    with open("config.json", "r") as f:
        return json.load(f)

config = load_config()

# ===============
# COMMAND HELPERS
# ===============

# Check for if user is a bot admin
def is_admin(user_id: int) -> bool:
    return user_id in config.get("admins", [])

# Fetch emoji ID by name
def get_emoji(name: str) -> str:
    return config.get("customisation", {}).get("emojis", {}).get(name, "")

# Fetch HEX colours and convert to integers for discord.py
def get_colour(name: str) -> int:
    return int(config.get("customisation", {}).get("colours", {}).get(name, "2fbffd"), 16)

# ===============
# STATUS CHECKERS
# ===============

# Check Cloudflare DNS & Google DNS for internet connectivity
async def check_internet() -> bool:
    results = await asyncio.gather(
        _ping_host("1.1.1.1", 53),
        _ping_host("8.8.8.8", 53)
    )

    # Return true if at least one is true
    return any(results)

# Check hosts by checking SSH list in config
async def check_host() -> dict:
    # Create a list of host IP/domain of each server
    hostnames = [server.get("host") for server in config.get("auth", {}).get("ssh", []) if server.get("host")]

    # If there are no servers, return nothing
    if not hostnames:
        return {}

    # Ping servers at same time
    ping_tasks = [_ping_host(host) for host in hostnames]
    results = await asyncio.gather(*ping_tasks)

    # Create KV dictionary of hostnames and results
    return dict(zip(hostnames, results))

# Check Minecraft host(s)
async def check_rcon() -> dict:
    # Fetch Minecraft server list from config
    mc_servers = config.get("minecraft", {}).get("servers", {})

    # If there are no servers, return nothing
    if not mc_servers:
        return {}

    # Create dictionary for status to be added to
    rcon_tasks = []

    # Iterates through all servers in config
    for name, info in mc.servers.items():
        server_names.append(name)

        # Fetch password from environment variable
        password = os.environ.get(details.get("rcon_password"))

        # Queue a background task using internal rcon function
        rcon_tasks.append(asyncio.to_thread(_sync_check_rcon, info.get("address"), info.get("rcon_port"), password))

    # Run RCON connections simultaneously
    return = await asyncio.gather(*rcon_tasks)

    # Return a KV dictionary
    return dict(zip(server_names, results))

# ================
# INTERNAL HELPERS
# ================

# Internal ping helper function
async def _ping_host(host: str) -> bool:
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

# Internal RCON helper function
def _sync_check_rcon(host: str, port: int, password: str) -> bool:
    try:
        with MCRcon(host, password, port=port) as mcr:
            return True
    except Exception:
        return False
