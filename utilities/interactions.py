# Handles interactions like buttons
# Manages Accept / Ban buttons for invite system

import discord

from utilities.embeds import Embeds
from utilities.output import Logger
from utilities.helpers import get_emoji, is_admin, config
from utilities.invites import process_verification, process_ban

class VerificationView(discord.ui.View):
    def __init__(self):
        # Disables timeout, required for persistent view
        super().__init__(timeout=None)

    # Verify button
    @discord.ui.button(
        style=discord.ButtonStyle.gray,
        emoji=discord.PartialEmoji.from_str(get_emoji("success")),
        custom_id="persistent_view:verify"
    )
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Grab verified role ID from config and check if the user has a role matching that ID
        verified_role_id = next((s for s in config.get("servers", []) if s.get("guild") == interaction.guild.id), {}).get("roles", {}).get("verified")

        # Block if they aren't verified or a bot admin
        if not (any(role.id == verified_role_id for role in interaction.user.roles) or is_admin(interaction.user.id)):
            embed = Embeds.error("Only verified members can approve new users.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Prevent Discord timing out
        await interaction.response.defer(ephemeral=True)

        # Pass message ID to backend
        member = await process_verification(interaction.guild, interaction.message.id)

        if member:
            # Overwrite original embed & remove buttons
            embed = Embeds.success(f"<@{member.id}> was verified by <@{interaction.user.id}>.")
            Logger.success(f"Verified {member.global_name} (ID: {member.id})")
            await interaction.message.edit(embed=embed, view=None)
        else:
            embed = Embeds.error(f"Failed to verify the user.")
            await interaction.followup.send(embed=embed)

    # Ban button
    @discord.ui.button(
        style=discord.ButtonStyle.gray,
        emoji=discord.PartialEmoji.from_str(get_emoji("error")),
        custom_id="persistent_view:ban"
    )
    async def ban_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Require bot admin / user ban perms to run ban action
        if not (interaction.user.guild_permissions.ban_members or is_admin(interaction.user.id)):
            embed = Embeds.error("You do not have permission to perform this action.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Prevent Discord timing out
        await interaction.response.defer(ephemeral=True)

        reason = f"Gatekeeper ban executed by {interaction.user.global_name} (ID: {interaction.user.id})"

        user_id = await process_ban(interaction.guild, interaction.message.id, reason)

        if user_id:
            # Overwrite original embed & remove buttons
            embed = Embeds.success(f"<@{user_id}> was banned by <@{interaction.user.id}>.")
            await interaction.message.edit(embed=embed, view=None)
        else:
            embed = Embeds.error(f"Failed to ban the user.")
            await interaction.followup.send(embed=embed)
