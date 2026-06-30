# Where the 4 types of embeds are defined
# Uses emojis and colours fetched by helpers.py

import discord

from utilities.helpers import get_emoji, get_colour

class Embeds:
    @staticmethod
    def success(description: str) -> discord.Embed:
        return discord.Embed(description=f"{get_emoji("success")} {description}", color=get_color("success"))

    @staticmethod
    def warning(description: str) -> discord.Embed:
        return discord.Embed(description=f"{get_emoji("warning")} {description}", color=get_color("warning"))

    @staticmethod
    def error(description: str) -> discord.Embed:
        return discord.Embed(description=f"{get_emoji("error")} {description}", color=get_color("error"))

    @staticmethod
    def info(description: str) -> discord.Embed:
        return discord.Embed(description=f"{get_emoji("info")} {description}", color=get_color("info"))
