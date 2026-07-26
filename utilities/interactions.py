# Handles interactions like buttons
# Manages Accept / Ban buttons for invite system

import discord

from utilities.embeds import Embeds
from utilities.output import Logger
from utilities.helpers import get_emoji, is_admin, config, get_guild_config
from utilities.invites import process_verification, process_ban

class VerificationView(discord.ui.View):
    def __init__(self):
        # Disables timeout, required for persistent view
        super().__init__(timeout=None)

        # Dynamically evaluate and assign the emojis when the view is instantiated
        for child in self.children:
            if child.custom_id == "persistent_view:verify":
                child.emoji = discord.PartialEmoji.from_str(get_emoji("success"))
            elif child.custom_id == "persistent_view:ban":
                child.emoji = discord.PartialEmoji.from_str(get_emoji("error"))

    # Verify button
    @discord.ui.button(
        style=discord.ButtonStyle.gray,
        emoji=discord.PartialEmoji.from_str(get_emoji("success")),
        custom_id="persistent_view:verify"
    )
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Grab verified role ID from config and check if the user has a role matching that ID
        server_config = get_guild_config(interaction.guild.id)
        verified_role_id = (server_config.get("roles") or {}).get("verified")

        # Block if they aren't verified or a bot admin
        if not (any(role.id == verified_role_id for role in interaction.user.roles) or is_admin(interaction.user.id)):
            Logger.warning(f"\"{interaction.user.name}\" (ID: {interaction.user.id}) tried to verify the member in a message but failed permission checks (Message ID: {interaction.message.id}).")
            embed = Embeds.error("You don't have permission to do that.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Prevent Discord timing out
        await interaction.response.defer(ephemeral=True)

        Logger.info(f"\"{interaction.user.name}\" (ID: {interaction.user.id}) is attempting to verify a member (Message ID: {interaction.message.id}).")

        # Pass message ID to backend
        user_id, username = await process_verification(interaction.client, interaction.guild, interaction.message.id)

        if user_id:
            Logger.info(f"\"{interaction.user.name}\" (ID: {interaction.user.id}) verified \"{username}\" (ID: {user_id}).")

            # Overwrite original embed & remove buttons
            embed = Embeds.info(f"<@{user_id}> was verified by <@{interaction.user.id}>.")
            await interaction.message.edit(embed=embed, view=None)

            # Respond to ephemeral thinking
            embed = Embeds.success(f"<@{user_id}> has been verified.")
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            Logger.warning(f"\"{interaction.user.name}\" (ID: {interaction.user.id}) failed to verify a member (Message ID: {interaction.message.id}).")
            embed = Embeds.error("Failed to verify the user.")
            await interaction.followup.send(embed=embed, ephemeral=True)

    # Ban button
    @discord.ui.button(
        style=discord.ButtonStyle.gray,
        emoji=discord.PartialEmoji.from_str(get_emoji("error")),
        custom_id="persistent_view:ban"
    )
    async def ban_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Require bot admin / user ban perms to run ban action
        if not (interaction.user.guild_permissions.ban_members or is_admin(interaction.user.id)):
            Logger.warning(f"\"{interaction.user.name}\" (ID: {interaction.user.id}) tried to ban the member in a message but failed permission checks (Message ID: {interaction.message.id}).")
            embed = Embeds.error("You don't have permission to do that.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Prevent Discord timing out
        await interaction.response.defer(ephemeral=True)

        reason = f"Gatekeeper ban executed by \"{interaction.user.name}\" (ID: {interaction.user.id})."

        user_id, username = await process_ban(interaction.client, interaction.guild, interaction.message.id, interaction.user.id, reason)

        if user_id:
            Logger.info(f"\"{interaction.user.name}\" (ID: {interaction.user.id}) initiated gatekeeper ban on \"{username}\" (ID: {user_id}).")

            # Overwrite original embed & remove buttons
            embed = Embeds.info(f"<@{user_id}> was banned by <@{interaction.user.id}>.")
            await interaction.message.edit(embed=embed, view=None)

            # Respond to ephemeral thinking
            embed = Embeds.success(f"<@{user_id}> has been banned.")
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            Logger.warning(f"\"{interaction.user.name}\" (ID: {interaction.user.id}) failed to initiate gatekeeper ban (Message ID: {interaction.message.id}).")

            embed = Embeds.error("Failed to ban the user.")
            await interaction.followup.send(embed=embed, ephemeral=True)
