# ==== main.py ==========================================================
# Python 3.11  ─  discord.py 2.3.2  ─  Paper 1.21  ─  Render / Railway ready
# ----------------------------------------------------------------------

import discord, os, io, json, re, asyncio, datetime
from discord.ext import commands
from discord.ui import View, button
from discord import app_commands
from aiohttp import web   # ⇠ solo si usas keep-alive (Railway / Render)

# ────────────────────────────
# CONFIGURACIÓN
# ────────────────────────────
PROHIBITED_WORDS   = {"hack", "cheat", "palabramala"}   # edita tu lista
WARN_LIMIT         = 3
MUTE_ROLE_NAME     = "Muted"
SOPORTE_ROLE       = "Soporte"
WARN_PATH          = "warns.json"
TICKET_COUNTER_JSON = "ticket_counter.json"             # nº de ticket persistente

# ────────────────────────────
# HELPERS (warns, colores, contador)
# ────────────────────────────
def load_warns() -> dict:
    if not os.path.exists(WARN_PATH):
        with open(WARN_PATH, "w") as f:
            json.dump({}, f)
    with open(WARN_PATH) as f:
        return json.load(f)

def save_warns(data: dict):
    with open(WARN_PATH, "w") as f:
        json.dump(data, f, indent=2)

def add_warn(user_id: int, moderator_id: int, reason: str) -> int:
    data  = load_warns()
    warns = data.get(str(user_id), [])
    warns.append({"mod": moderator_id, "reason": reason})
    data[str(user_id)] = warns
    save_warns(data)
    return len(warns)

HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")
def parse_color(value: str | None) -> discord.Color:
    if not value:
        return discord.Color.random()
    m = HEX.match(value.strip())
    return discord.Color(int(m.group(1), 16)) if m else discord.Color.random()

# ---- contador persistente de tickets ---------------------------------
def load_counter() -> int:
    if not os.path.exists(TICKET_COUNTER_JSON):
        with open(TICKET_COUNTER_JSON, "w") as f:
            json.dump({"last": 0}, f)
            return 0
    with open(TICKET_COUNTER_JSON) as f:
        return json.load(f).get("last", 0)

def save_counter(n: int):
    with open(TICKET_COUNTER_JSON, "w") as f:
        json.dump({"last": n}, f)

# ────────────────────────────
# BOT & INTENTS
# ────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ────────────────────────────
# CHECK: solo rol Soporte (slash)
# ────────────────────────────
def soporte_only():
    async def predicate(inter: discord.Interaction) -> bool:
        return any(r.name.lower() == SOPORTE_ROLE.lower() for r in inter.user.roles)
    return app_commands.check(predicate)

# ────────────────────────────
# EVENTOS BÁSICOS
# ────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ Conectado como {bot.user}")
    synced = await bot.tree.sync()
    print(f"🌐 Slash commands sincronizados ({len(synced)})")

@bot.event
async def on_member_join(member):
    canal = discord.utils.get(member.guild.text_channels, name="bienvenidas")
    if canal:
        await canal.send(f"👋 ¡Bienvenido/a {member.mention} a Leleboxpvp!")

# ────────────────────────────
# AUTOMOD → on_message
# ────────────────────────────
@bot.event
async def on_message(msg: discord.Message):
    await bot.process_commands(msg)

    if msg.author.bot:
        return

    # 1) palabras prohibidas
    if any(p in msg.content.lower() for p in PROHIBITED_WORDS):
        await msg.delete()
        total = add_warn(msg.author.id, bot.user.id, "Palabra prohibida")
        await msg.channel.send(
            f"{msg.author.mention} ⚠️ Lenguaje no permitido. Warn {total}/{WARN_LIMIT}",
            delete_after=5
        )
        return

    # 2) anti-spam (3 duplicados en 10 s)
    now   = datetime.datetime.utcnow().timestamp()
    cache = getattr(msg.author, "_spam", [])
    cache.append((now, msg.content))
    cache[:] = [(t, c) for t, c in cache if now - t <= 10]
    setattr(msg.author, "_spam", cache)

    if sum(1 for _, c in cache if c == msg.content) >= 3:
        await msg.delete()
        total = add_warn(msg.author.id, bot.user.id, "Spam")
        await msg.channel.send(
            f"{msg.author.mention} ⛔ Spam detectado. Warn {total}/{WARN_LIMIT}",
            delete_after=5
        )

# ────────────────────────────
# SISTEMA DE TICKETS
# ────────────────────────────
TICKET_LOCK = asyncio.Lock()

def usuario_ya_tiene_ticket(guild: discord.Guild, member: discord.Member) -> bool:
    """True si ya hay un canal ticket visible por el usuario."""
    for ch in guild.text_channels:
        if ch.name.startswith("ticket-") and ch.overwrites_for(member).view_channel:
            return True
    return False

class CloseView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @button(label="❌ Cerrar Ticket", style=discord.ButtonStyle.red, custom_id="ticket_close")
    async def close(self, interaction: discord.Interaction, _):
        soporte = discord.utils.get(interaction.guild.roles, name=SOPORTE_ROLE)
        if soporte not in interaction.user.roles:
            await interaction.response.send_message("🚫 Solo Soporte puede cerrar el ticket.", ephemeral=True)
            return

        channel     = interaction.channel
        log_channel = discord.utils.get(channel.guild.text_channels, name="logs")

        # historial
        msgs  = [m async for m in channel.history(limit=None, oldest_first=True)]
        texto = "\n".join(
            f"[{m.created_at}] {m.author.display_name}: {m.content or '[Embed/Adjunto]'}"
            for m in msgs
        )
        file = discord.File(io.BytesIO(texto.encode()), filename=f"{channel.name}.txt")

        if log_channel:
            await log_channel.send(
                f"📁 Ticket cerrado por {interaction.user.mention} - `{channel.name}`",
                file=file
            )
        await channel.delete()

class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @button(label="🎟️ Abrir Ticket", style=discord.ButtonStyle.green, custom_id="ticket_open")
    async def open_ticket(self, interaction: discord.Interaction, _):
        guild  = interaction.guild
        member = interaction.user

        if usuario_ya_tiene_ticket(guild, member):
            await interaction.response.send_message("❌ Ya tienes un ticket abierto.", ephemeral=True)
            return

        soporte   = discord.utils.get(guild.roles, name=SOPORTE_ROLE)
        categoria = discord.utils.get(guild.categories, name="Soporte") \
                   or await guild.create_category("Soporte")

        # ── número único persistente ────────────────────────────
        async with TICKET_LOCK:
            numero = load_counter() + 1
            save_counter(numero)

            canal = await guild.create_text_channel(
                name=f"ticket-{numero}",
                overwrites={
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    member: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                    soporte: discord.PermissionOverwrite(view_channel=True, send_messages=True)
                             if soporte else None
                },
                category=categoria
            )
        # ─────────────────────────────────────────────────────────

        embed = discord.Embed(
            title=f"Ticket #{numero}",
            description=f"{member.mention}, describe tu problema y un miembro del equipo te atenderá.",
            color=discord.Color.red()
        )
        await canal.send(embed=embed, view=CloseView())
        await interaction.response.send_message(f"✅ Ticket creado: {canal.mention}", ephemeral=True)

# ────────────────────────────
# COMANDO CON PREFIJO (único): !setup
# ────────────────────────────
@bot.command()
async def setup(ctx):
    embed = discord.Embed(
        title="Soporte de Leleboxpvp",
        description="Haz clic en el botón para abrir un ticket.",
        color=discord.Color.red()
    )
    await ctx.send(embed=embed, view=TicketView())

# ────────────────────────────
# COMANDOS DE MODERACIÓN → SOLO SLASH
# ────────────────────────────
async def _mute_member(guild: discord.Guild, member: discord.Member, tiempo: int):
    role = discord.utils.get(guild.roles, name=MUTE_ROLE_NAME)
    if not role:
        role = await guild.create_role(name=MUTE_ROLE_NAME)
        for ch in guild.channels:
            await ch.set_permissions(role, send_messages=False, speak=False)
    await member.add_roles(role, reason="Mute temporal")
    await asyncio.sleep(tiempo * 60)
    if role in member.roles:
        await member.remove_roles(role, reason="Mute expiró")

# BAN
@bot.tree.command(name="ban", description="Banear usuario")
@soporte_only()
@app_commands.describe(member="Usuario a banear", motivo="Razón")
async def ban_cmd(inter: discord.Interaction, member: discord.Member, motivo: str = "Sin motivo"):
    await member.ban(reason=motivo)
    await inter.response.send_message(f"🔨 {member} baneado\n> {motivo}", ephemeral=True)

# KICK
@bot.tree.command(name="kick", description="Kickear usuario")
@soporte_only()
@app_commands.describe(member="Usuario a expulsar", motivo="Razón")
async def kick_cmd(inter: discord.Interaction, member: discord.Member, motivo: str = "Sin motivo"):
    await member.kick(reason=motivo)
    await inter.response.send_message(f"👢 {member} expulsado\n> {motivo}", ephemeral=True)

# WARN
@bot.tree.command(name="warn", description="Advertir usuario")
@soporte_only()
@app_commands.describe(member="Usuario", motivo="Razón")
async def warn_cmd(inter: discord.Interaction, member: discord.Member, motivo: str = "Sin motivo"):
    total = add_warn(member.id, inter.user.id, motivo)
    await inter.response.send_message(
        f"⚠️ {member} advertido ({total}/{WARN_LIMIT})\n> {motivo}",
        ephemeral=True
    )
    if total >= WARN_LIMIT:
        await _mute_member(inter.guild, member, 30)

# MUTE
@bot.tree.command(name="mute", description="Mutear usuario (minutos)")
@soporte_only()
@app_commands.describe(member="Usuario", tiempo="Duración")
async def mute_cmd(inter: discord.Interaction, member: discord.Member, tiempo: int = 10):
    await _mute_member(inter.guild, member, tiempo)
    await inter.response.send_message(f"🔇 {member} muteado por {tiempo} min.", ephemeral=True)

# UNMUTE
@bot.tree.command(name="unmute", description="Desmutear usuario")
@soporte_only()
@app_commands.describe(member="Usuario")
async def unmute_cmd(inter: discord.Interaction, member: discord.Member):
    role = discord.utils.get(inter.guild.roles, name=MUTE_ROLE_NAME)
    if role and role in member.roles:
        await member.remove_roles(role)
        await inter.response.send_message(f"🔊 {member} desmuteado.", ephemeral=True)

# EMBED
@bot.tree.command(name="embed", description="Enviar un embed rápido")
@soporte_only()
@app_commands.describe(texto='Formato: "Título | Descripción | #hex"')
async def embed_cmd(inter: discord.Interaction, *, texto: str):
    partes = [p.strip() for p in texto.split("|")]
    titulo = partes[0]
    descripcion = partes[1] if len(partes) > 1 else ""
    color = parse_color(partes[2] if len(partes) > 2 else None)
    em = discord.Embed(title=titulo, description=descripcion, color=color)
    await inter.channel.send(embed=em)
    await inter.response.send_message("✅ Embed enviado", ephemeral=True)

# ────────────────────────────
# VISTAS PERSISTENTES + KEEP-ALIVE WEB
# ────────────────────────────
@bot.event
async def setup_hook():
    bot.add_view(TicketView())
    bot.add_view(CloseView())

    # (opcional) servidor web para mantener vivo en Railway / Render
    async def _web():
        app = web.Application()
        app.add_routes([web.get("/", lambda _: web.Response(text="Bot activo."))])
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", 3000).start()
    bot.loop.create_task(_web())

# ────────────────────────────
# ARRANQUE
# ────────────────────────────
bot.run(os.getenv("TOKEN"))
# ======================================================================