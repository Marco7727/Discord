# ==== main.py ==========================================================
import discord, os, io, json, re, asyncio, datetime
from discord.ext import commands
from discord.ui import View, button
from aiohttp import web   # solo si quieres el web-keep-alive (opcional Railway)

# ────────────────────────────
# CONFIGURACIÓN
# ────────────────────────────
PROHIBITED_WORDS = {"hack", "cheat", "palabramala"}   # edita tu lista
WARN_LIMIT       = 3
MUTE_ROLE_NAME   = "Muted"
SOPORTE_ROLE     = "Soporte"
WARN_PATH        = "warns.json"

# ────────────────────────────
# HELPERS
# ────────────────────────────
def load_warns():
    if not os.path.exists(WARN_PATH):
        with open(WARN_PATH, "w") as f:
            json.dump({}, f)
    with open(WARN_PATH) as f:
        return json.load(f)

def save_warns(data):
    with open(WARN_PATH, "w") as f:
        json.dump(data, f, indent=2)

def add_warn(user_id: int, moderator_id: int, reason: str):
    data = load_warns()
    warns = data.get(str(user_id), [])
    warns.append({"mod": moderator_id, "reason": reason})
    data[str(user_id)] = warns
    save_warns(data)
    return len(warns)

def has_role(member: discord.Member, role_name: str):
    return any(r.name.lower() == role_name.lower() for r in member.roles)

HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")
def parse_color(value: str | None):
    if not value:
        return discord.Color.random()
    m = HEX.match(value.strip())
    return discord.Color(int(m.group(1), 16)) if m else discord.Color.random()

# ────────────────────────────
# INTENTS Y BOT
# ────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ────────────────────────────
# EVENTOS BÁSICOS
# ────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ Conectado como {bot.user}")
    try:
        synced = await bot.tree.sync()   # slash commands
        print(f"🌐 Slash commands sincronizados ({len(synced)})")
    except Exception as e:
        print("Sync falló:", e)

@bot.event
async def on_member_join(member):
    canal = discord.utils.get(member.guild.text_channels, name="bienvenidas")
    if canal:
        await canal.send(f"👋 ¡Bienvenido/a {member.mention} a Leleboxpvp!")

# ────────────────────────────
# AUTOMOD on_message
# ────────────────────────────
@bot.event
async def on_message(msg: discord.Message):
    await bot.process_commands(msg)      # ¡importante!

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
    now = datetime.datetime.utcnow().timestamp()
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
class CloseView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @button(label="❌ Cerrar Ticket", style=discord.ButtonStyle.red, custom_id="ticket_close")
    async def close(self, interaction: discord.Interaction, _):
        soporte = discord.utils.get(interaction.guild.roles, name=SOPORTE_ROLE)
        if soporte not in interaction.user.roles:
            await interaction.response.send_message("🚫 Solo Soporte puede cerrar el ticket.", ephemeral=True)
            return

        channel = interaction.channel
        log_channel = discord.utils.get(channel.guild.text_channels, name="logs")

        # historial
        msgs = [m async for m in channel.history(limit=None, oldest_first=True)]
        texto = "\n".join(
            f"[{m.created_at}] {m.author.display_name} ({m.author.id}): {m.content or '[Embed/Adjunto]'}"
            for m in msgs
        )
        file = discord.File(io.BytesIO(texto.encode()), filename=f"{channel.name}.txt")

        if log_channel:
            await log_channel.send(f"📁 Ticket cerrado por {interaction.user.mention} - `{channel.name}`", file=file)

        await channel.delete()

class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @button(label="🎟️ Abrir Ticket", style=discord.ButtonStyle.green, custom_id="ticket_open")
    async def open_ticket(self, interaction: discord.Interaction, _):
        guild  = interaction.guild
        member = interaction.user

        if discord.utils.get(guild.text_channels, name=f"ticket-{member.id}"):
            await interaction.response.send_message("❌ Ya tienes un ticket abierto.", ephemeral=True)
            return

        soporte  = discord.utils.get(guild.roles, name=SOPORTE_ROLE)
        categoria = discord.utils.get(guild.categories, name="Soporte") \
                   or await guild.create_category("Soporte")

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            soporte: discord.PermissionOverwrite(view_channel=True, send_messages=True) if soporte else None
        }
        overwrites = {k: v for k, v in overwrites.items() if v is not None}

        canal = await guild.create_text_channel(
            name=f"ticket-{member.id}",
            overwrites=overwrites,
            category=categoria
        )

        embed = discord.Embed(
            title="Soporte de Leleboxpvp",
            description="Describe tu problema y un miembro del equipo te responderá pronto.",
            color=discord.Color.red()
        )
        await canal.send(embed=embed, view=CloseView())
        await interaction.response.send_message(f"✅ Ticket creado: {canal.mention}", ephemeral=True)

@bot.command()
async def setup(ctx):
    embed = discord.Embed(
        title="Soporte de Leleboxpvp",
        description="Haz clic en el botón para abrir un ticket.",
        color=discord.Color.red()
    )
    await ctx.send(embed=embed, view=TicketView())

# ────────────────────────────
# COMANDOS DE MODERACIÓN
# ────────────────────────────
def soporte_check():
    async def predicate(ctx):
        return has_role(ctx.author, SOPORTE_ROLE)
    return commands.check(predicate)

@bot.hybrid_command(description="Banear usuario")
@commands.has_permissions(ban_members=True)
@soporte_check()
async def ban(ctx, member: discord.Member, *, motivo="Sin motivo"):
    await member.ban(reason=motivo)
    await ctx.reply(f"🔨 {member} baneado\n> {motivo}")

@bot.hybrid_command(description="Kickear usuario")
@commands.has_permissions(kick_members=True)
@soporte_check()
async def kick(ctx, member: discord.Member, *, motivo="Sin motivo"):
    await member.kick(reason=motivo)
    await ctx.reply(f"👢 {member} expulsado\n> {motivo}")

@bot.hybrid_command(description="Advertir usuario")
@soporte_check()
async def warn(ctx, member: discord.Member, *, motivo="Sin motivo"):
    total = add_warn(member.id, ctx.author.id, motivo)
    await ctx.reply(f"⚠️ {member} advertido ({total}/{WARN_LIMIT})\n> {motivo}")
    if total >= WARN_LIMIT:
        await mute(ctx, member, tiempo=30)

@bot.hybrid_command(description="Mutear usuario (min)")
@soporte_check()
async def mute(ctx, member: discord.Member, tiempo: int = 10):
    role = discord.utils.get(ctx.guild.roles, name=MUTE_ROLE_NAME)
    if not role:
        role = await ctx.guild.create_role(name=MUTE_ROLE_NAME)
        for ch in ctx.guild.channels:
            await ch.set_permissions(role, send_messages=False, speak=False)
    await member.add_roles(role, reason="Mute temporal")
    await ctx.reply(f"🔇 {member} muteado por {tiempo} min.")
    await asyncio.sleep(tiempo * 60)
    if role in member.roles:
        await member.remove_roles(role, reason="Mute expiró")

@bot.hybrid_command(description="Desmutear usuario")
@soporte_check()
async def unmute(ctx, member: discord.Member):
    role = discord.utils.get(ctx.guild.roles, name=MUTE_ROLE_NAME)
    if role in member.roles:
        await member.remove_roles(role)
        await ctx.reply(f"🔊 {member} desmuteado.")

# ────────────────────────────
# COMANDO /embed
# ────────────────────────────
@bot.hybrid_command(description="Enviar embed: Título | Descripción | #hex")
@soporte_check()
async def embed(ctx, *, texto: str):
    partes = [p.strip() for p in texto.split("|")]
    titulo = partes[0]
    descripcion = partes[1] if len(partes) > 1 else ""
    color = parse_color(partes[2] if len(partes) > 2 else None)
    em = discord.Embed(title=titulo, description=descripcion, color=color)
    await ctx.send(embed=em)
    await ctx.reply("✅ Embed enviado", ephemeral=True)

# ────────────────────────────
# VISTAS PERSISTENTES
# ────────────────────────────
@bot.event
async def setup_hook():
    bot.add_view(TicketView())
    bot.add_view(CloseView())

    # (opcional) arrancar web-keep-alive
    async def _web():
        app = web.Application()
        app.add_routes([web.get("/", lambda _: web.Response(text="Bot activo."))])
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", 3000)
        await site.start()
    bot.loop.create_task(_web())

# ────────────────────────────
# ARRANQUE
# ────────────────────────────
bot.run(os.getenv("TOKEN"))
# ======================================================================