# ==== main.py ==========================================================
import discord, os, io, json, re, asyncio, datetime
from discord.ext import commands
from discord.ui import View, button
from aiohttp import web

PROHIBITED_WORDS = {"hack", "cheat", "palabramala"}
WARN_LIMIT       = 6
MUTE_ROLE_NAME   = "Muted"
SOPORTE_ROLE     = "Soporte"
WARN_PATH        = "warns.json"
TICKET_COUNTER_PATH = "ticket_counter.json"      # ← nuevo

# ─── helpers warn/colores (sin cambios) ───────────────────────────────
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

# ─── contador persistente ─────────────────────────────────────────────
def load_counter() -> int:
    if not os.path.exists(TICKET_COUNTER_PATH):
        with open(TICKET_COUNTER_PATH, "w") as f:
            json.dump({"last": 0}, f)
            return 0
    with open(TICKET_COUNTER_PATH) as f:
        return json.load(f).get("last", 0)

def save_counter(n: int):
    with open(TICKET_COUNTER_PATH, "w") as f:
        json.dump({"last": n}, f)

# ─── bot / intents ────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Conectado como {bot.user}")
    try:
        await bot.tree.sync()
    except Exception as e:
        print("Sync falló:", e)

@bot.event
async def on_member_join(member):
    canal = discord.utils.get(member.guild.text_channels, name="bienvenidas")
    if canal:
        await canal.send(f"👋 ¡Bienvenido/a {member.mention} a Leleboxpvp!")

# ─── automod (igual que antes) ────────────────────────────────────────
@bot.event
async def on_message(msg):
    await bot.process_commands(msg)
    if msg.author.bot:
        return
    if any(p in msg.content.lower() for p in PROHIBITED_WORDS):
        await msg.delete()
        total = add_warn(msg.author.id, bot.user.id, "Palabra prohibida")
        await msg.channel.send(
            f"{msg.author.mention} ⚠️ Lenguaje no permitido. Warn {total}/{WARN_LIMIT}",
            delete_after=5
        )
        return
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

# ─── tickets ──────────────────────────────────────────────────────────
TICKET_LOCK = asyncio.Lock()

def usuario_ya_tiene_ticket(guild, member):
    for ch in guild.text_channels:
        if ch.name.startswith("ticket-") and ch.overwrites_for(member).view_channel:
            return True
    return False

class CloseView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @button(label="❌ Cerrar Ticket", style=discord.ButtonStyle.red, custom_id="ticket_close")
    async def close(self, interaction, _):
        soporte = discord.utils.get(interaction.guild.roles, name=SOPORTE_ROLE)
        if soporte not in interaction.user.roles:
            await interaction.response.send_message("🚫 Solo Soporte puede cerrar el ticket.", ephemeral=True)
            return

        channel = interaction.channel
        log_channel = discord.utils.get(channel.guild.text_channels, name="logs")

        msgs = [m async for m in channel.history(limit=None, oldest_first=True)]
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
    async def open_ticket(self, interaction, _):
        guild  = interaction.guild
        member = interaction.user

        if usuario_ya_tiene_ticket(guild, member):
            await interaction.response.send_message("❌ Ya tienes un ticket abierto.", ephemeral=True)
            return

        soporte  = discord.utils.get(guild.roles, name=SOPORTE_ROLE)
        categoria = discord.utils.get(guild.categories, name="Soporte") \
                   or await guild.create_category("Soporte")

        # ── número único persistente ─────────────────────────
        async with TICKET_LOCK:
            numero = load_counter() + 1
            save_counter(numero)
            nombre_canal = f"ticket-{numero}"

            canal = await guild.create_text_channel(
                name=nombre_canal,
                overwrites={
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    member: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                    soporte: discord.PermissionOverwrite(view_channel=True, send_messages=True)
                             if soporte else None
                },
                category=categoria
            )
        # ────────────────────────────────────────────────────

        embed = discord.Embed(
            title=f"Ticket #{numero}",
            description=f"{member.mention}, describe tu problema y un miembro del equipo te atenderá.",
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

# ─── vistas persistentes y arranque (igual) ───────────────────────────
@bot.event
async def setup_hook():
    bot.add_view(TicketView())
    bot.add_view(CloseView())
    async def _web():
        app = web.Application()
        app.add_routes([web.get("/", lambda _: web.Response(text="Bot activo."))])
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", 3000).start()
    bot.loop.create_task(_web())

bot.run(os.getenv("TOKEN"))
# ======================================================================