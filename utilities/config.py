# Pookie Bot - Discord bot for GYATatouille
# Copyright (C) 2026 no7here
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

# ========================================================================

# Handles loading & reading config.json
# - Config loader & reloader
# - Guild config finder
# - Emoji finder
# - HEX converter (for embed colours)
# - Startup check that required emojis are present

# Imports nothing from the project except the logger, to avoid circular import issues.

import json
import os

from utilities.output import Logger

# Load static config
def load_config():
    path = os.environ.get("POOKIE_CONFIG", "config.json")
    with open(path) as f:
        return json.load(f)

config = load_config()

# Add a function to reload config
def reload_config():
    try:
        # Load the new config into a temporary variable first
        new_config = load_config()

        # Check if the new config is empty (e.g., if the file was totally blank)
        if not new_config:
            Logger.warning("Config reload aborted: config.json is empty.")
            return False

        # Update config after passing check
        config.clear()
        config.update(new_config)

        return True

    except (FileNotFoundError, json.JSONDecodeError) as e:
        # Catch missing files or broken JSON formatting, keeping the old config safe
        Logger.error("Failed to reload config.json. The previous config has been kept until reboot. Check log.", str(e))
        return False

# Fetch server configs
def get_guild_config(guild_id: int) -> dict:
    return next((s for s in config.get("servers") or [] if s.get("guild_id") == guild_id), {}) or {}

# Fetch emoji ID by name
def get_emoji(name: str) -> str:
    customisation = config.get("customisation") or {}
    emojis = customisation.get("emojis") or {}
    return emojis.get(name)

# Fetch HEX colours and convert to integers for discord.py
def get_colour(name: str) -> int:
    customisation = config.get("customisation") or {}
    colours = customisation.get("colours") or {}
    value = colours.get(name)
    return int(value if value else "2fbffd", 16)

# Verify emojis are present and working
for name in ["success", "warning", "error", "info"]:
    customisation = config.get("customisation") or {}
    emojis = customisation.get("emojis") or {}

    if not emojis.get(name):
        Logger.error(f"Failed to find emoji \"{name}\" in config.json.")
        raise SystemExit(1)
