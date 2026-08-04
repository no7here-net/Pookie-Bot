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

# Where the 4 types of embeds are defined
# Uses emojis and colours fetched by helpers.py

import discord

from utilities.helpers import get_emoji, get_colour

class Embeds:
    @staticmethod
    def success(description: str) -> discord.Embed:
        return discord.Embed(description=f"{get_emoji("success")} {description}", color=get_colour("success"))

    @staticmethod
    def warning(description: str) -> discord.Embed:
        return discord.Embed(description=f"{get_emoji("warning")} {description}", color=get_colour("warning"))

    @staticmethod
    def error(description: str) -> discord.Embed:
        return discord.Embed(description=f"{get_emoji("error")} {description}", color=get_colour("error"))

    @staticmethod
    def info(description: str) -> discord.Embed:
        return discord.Embed(description=f"{get_emoji("info")} {description}", color=get_colour("info"))
