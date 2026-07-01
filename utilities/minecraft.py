import asyncio
import os

from mcrcon import MCRcon
from utilities.helpers import config

# Internal RCON helper function
def _sync_check_rcon(host: str, port: int, password: str) -> bool:
    try:
        with MCRcon(host, password, port=port) as mcr:
            return True
    except Exception:
        return False

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
