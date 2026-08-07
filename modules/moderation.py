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

import discord

from discord import app_commands
from discord.ext import commands

from utilities.embeds import Embeds
from utilities.output import Logger
from utilities.config import get_colour
from utilities.helpers import is_admin

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="echo", description="Echoes a message as Pookie Bot.")
    @app_commands.describe(message="What message you want Pookie Bot to send.", channel="Which channel you want Pookie Bot to send it in.", embed="Whether you want Pookie Bot to place it in an embed.")
    @app_commands.rename(enable_embed="embed")
    async def echo(self, interaction: discord.Interaction, message: str, channel: discord.TextChannel, enable_embed: bool = True):
        # Require bot admin / server admin perms to run echo command
        if not (interaction.user.guild_permissions.administrator or is_admin(interaction.user.id)):
            Logger.warning(f"\"{interaction.user.name}\" (ID: {interaction.user.id}) tried to send an echo but was blocked as they do not have permission.")
            embed = Embeds.error("You don't have permission to do that.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        # Defer response so Discord gives us more time to respond
        await interaction.response.defer(ephemeral=True)
        try:
            if enable_embed:
                embed = discord.Embed(description=message, color=get_colour("info"))
                await channel.send(embed=embed)
            else:
                await channel.send(message)
            embed = Embeds.success(f"Message sent to <#{channel.id}>.")
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception:
            try:
                Logger.warning(f"\"{interaction.user.name}\" (ID: {interaction.user.id}) tried to send an echo but an exception occurred whilst processing.")
                embed = Embeds.error(f"Failed to send message to <#{channel.id}>.")
                await interaction.followup.send(embed=embed, ephemeral=True)
            except Exception:
                Logger.warning(f"\"{interaction.user.name}\" (ID: {interaction.user.id}) tried to send an echo but an exception occurred whilst processing and failed to respond.")
        return

async def setup(bot):
    await bot.add_cog(Moderation(bot))
