import discord
from discord.ext import commands
from discord.ui import View, button
import os
import io
from aiohttp import web

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True  # NECESARIO para detectar nuevos usuarios

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}")

# 🎉 Mensaje de bienvenida al servidor
@bot.event
async def on_member_join(member):
    canal_bienvenida = discord.utils.get(member.guild.text_channels, name="bienvenidas")
    if canal_bienvenida:
        await canal_bienvenida.send(f"👋 ¡Bienvenido/a {member.mention} a Leleboxpvp!")

# 🔒 Botón para cerrar ticket (solo Soporte)
class CloseView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @button(label="❌ Cerrar Ticket", style=discord.ButtonStyle.red, custom_id="ticket_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        soporte = discord.utils.get(interaction.guild.roles, name="Soporte")
        if soporte not in interaction.user.roles:
            await interaction.response.send_message("🚫 Solo el equipo de Soporte puede cerrar el ticket.", ephemeral=True)
            return

        channel = interaction.channel
        user = interaction.user
        log_channel = discord.utils.get(channel.guild.text_channels, name="logs")

        # Guardar historial
        messages = [msg async for msg in channel.history(limit=None, oldest_first=True)]
        log_text = ""
        for msg in messages:
            autor = f"{msg.author.display_name} ({msg.author.id})"
            contenido = msg.content or "[Embed/Archivo]"
            log_text += f"[{msg.created_at}] {autor}: {contenido}\n"

        file = discord.File(io.BytesIO(log_text.encode()), filename=f"{channel.name}.txt")

        if log_channel:
            await log_channel.send(
                content=f"📁 Ticket cerrado por {user.mention} - `{channel.name}`",
                file=file
            )

        await channel.delete()

# 🎟 Botón para abrir ticket (solo 1 por usuario)
class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @button(label="🎟️ Abrir Ticket", style=discord.ButtonStyle.green, custom_id="ticket_open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        member = interaction.user

        # Verificar si ya tiene un ticket abierto
        canal_existente = discord.utils.get(
            guild.text_channels,
            name=f"ticket-{member.name.lower()}"
        )
        if canal_existente:
            await interaction.response.send_message(
                f"❌ Ya tienes un ticket abierto: {canal_existente.mention}",
                ephemeral=True
            )
            return

        soporte = discord.utils.get(guild.roles, name="Soporte")
        categoria = discord.utils.get(guild.categories, name="Soporte")

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        if soporte:
            overwrites[soporte] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        canal_ticket = await guild.create_text_channel(
            name=f"ticket-{member.name}",
            overwrites=overwrites,
            category=categoria
        )

        embed = discord.Embed(
            title="Soporte de Leleboxpvp",
            description="Describe tu problema con detalle. Un miembro del equipo te respondera pronto.",
            color=discord.Color.red()
        )

        await canal_ticket.send(embed=embed, view=CloseView())
        await interaction.response.send_message(f"✅ Ticket creado: {canal_ticket.mention}", ephemeral=True)

# 📩 Comando !setup
@bot.command()
async def setup(ctx):
    embed = discord.Embed(
        title="Soporte de Leleboxpvp",
        description="Haz clic en el botón para abrir un ticket.",
        color=discord.Color.red()
    )
    await ctx.send(embed=embed, view=TicketView())

# 🌐 Servidor web para mantener el bot activo (Replit + UptimeRobot)
async def handle(request):
    return web.Response(text="Bot activo.")

@bot.event
async def setup_hook():
    app = web.Application()
    app.add_routes([web.get('/', handle)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 3000)
    await site.start()
    print("🌐 Servidor web iniciado en puerto 3000")

# ▶️ Iniciar el bot
bot.run(os.getenv("TOKEN"))