"""버튼 클릭 자동 역할 부여 시스템."""
from __future__ import annotations

import json
from pathlib import Path
import time

import discord
from discord import app_commands
from discord.ext import commands

DATA_FILE = Path("autorole_data.json")
PANELS: dict[str, dict] = {}


def load_data() -> None:
    global PANELS
    try:
        PANELS = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        PANELS = {}


def save_data() -> None:
    DATA_FILE.write_text(json.dumps(PANELS, ensure_ascii=False, indent=2), encoding="utf-8")


class RolePanelView(discord.ui.View):
    def __init__(self, panel_id: str, buttons: list[dict]):
        super().__init__(timeout=None)
        for index, item in enumerate(buttons):
            button = discord.ui.Button(
                label=item["label"],
                emoji=item.get("emoji") or None,
                style=discord.ButtonStyle.primary,
                custom_id=f"autorole:{panel_id}:{item['role_id']}",
                row=index // 5,
            )
            button.callback = self._callback
            self.add_item(button)

    async def _callback(self, interaction: discord.Interaction) -> None:
        role_id = int(interaction.data["custom_id"].split(":")[-1])
        role = interaction.guild.get_role(role_id) if interaction.guild else None
        if role is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("역할을 찾을 수 없습니다.", ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role, reason="자동 역할 버튼")
            text = f"**{role.name}** 역할을 해제했습니다."
        else:
            await interaction.user.add_roles(role, reason="자동 역할 버튼")
            text = f"**{role.name}** 역할을 받았습니다."
        await interaction.response.send_message(text, ephemeral=True)


class AddRoleModal(discord.ui.Modal, title="역할 버튼 추가"):
    label = discord.ui.TextInput(label="버튼 이름", max_length=50)
    emoji = discord.ui.TextInput(label="이모지", required=False, max_length=20)

    def __init__(self, panel_id: str, role: discord.Role):
        super().__init__()
        self.panel_id = panel_id
        self.role = role

    async def on_submit(self, interaction: discord.Interaction) -> None:
        PANELS[self.panel_id]["buttons"].append({
            "label": self.label.value.strip(),
            "emoji": self.emoji.value.strip(),
            "role_id": self.role.id,
        })
        save_data()
        await interaction.response.send_message("역할 버튼을 추가했습니다.", ephemeral=True)


class PanelEditor(discord.ui.View):
    def __init__(self, panel_id: str):
        super().__init__(timeout=300)
        self.panel_id = panel_id
        self.role: discord.Role | None = None

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="추가할 역할 선택")
    async def select_role(self, interaction: discord.Interaction, select: discord.ui.RoleSelect) -> None:
        self.role = select.values[0]
        await interaction.response.send_message(f"선택: {self.role.name}", ephemeral=True)

    @discord.ui.button(label="버튼 추가", style=discord.ButtonStyle.success)
    async def add_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self.role is None:
            await interaction.response.send_message("역할을 먼저 선택하세요.", ephemeral=True)
            return
        await interaction.response.send_modal(AddRoleModal(self.panel_id, self.role))

    @discord.ui.button(label="이 채널에 게시", style=discord.ButtonStyle.primary)
    async def publish(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        panel = PANELS[self.panel_id]
        if not panel["buttons"]:
            await interaction.response.send_message("버튼을 하나 이상 추가하세요.", ephemeral=True)
            return
        embed = discord.Embed(title=panel["title"], description=panel["description"], color=0x5865F2)
        message = await interaction.channel.send(embed=embed, view=RolePanelView(self.panel_id, panel["buttons"]))
        panel.update({"guild_id": interaction.guild_id, "channel_id": interaction.channel_id, "message_id": message.id})
        save_data()
        await interaction.response.send_message("역할 패널을 게시했습니다.", ephemeral=True)


class AutoRoleCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        load_data()

    async def cog_load(self) -> None:
        for panel_id, panel in PANELS.items():
            if panel.get("buttons"):
                self.bot.add_view(RolePanelView(panel_id, panel["buttons"]), message_id=panel.get("message_id"))

    @app_commands.command(name="역할패널만들기", description="[관리자] 자동 역할 패널을 만듭니다.")
    @app_commands.default_permissions(administrator=True)
    async def create_panel(self, interaction: discord.Interaction) -> None:
        panel_id = str(time.time_ns())
        PANELS[panel_id] = {
            "title": "🎭 역할 선택",
            "description": "버튼을 눌러 역할을 받거나 해제하세요.",
            "buttons": [],
        }
        save_data()
        await interaction.response.send_message(
            "역할을 선택한 뒤 버튼을 추가하고 게시하세요.",
            view=PanelEditor(panel_id),
            ephemeral=True,
        )

    @app_commands.command(name="역할패널목록", description="[관리자] 역할 패널 목록을 확인합니다.")
    @app_commands.default_permissions(administrator=True)
    async def list_panels(self, interaction: discord.Interaction) -> None:
        rows = [p for p in PANELS.values() if p.get("guild_id") == interaction.guild_id]
        text = "\n".join(f"• {p['title']} — 버튼 {len(p['buttons'])}개" for p in rows) or "등록된 패널이 없습니다."
        await interaction.response.send_message(text, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutoRoleCog(bot))
