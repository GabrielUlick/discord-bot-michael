import discord
from discord.ext import commands, tasks
from discord import app_commands, ui, ButtonStyle
from discord.ui import Button, View

import json
import os
import random
import asyncio
import sqlite3
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, jsonify
from threading import Thread
import re
from collections import defaultdict
import time

# =========================================
# CONFIGURAÇÕES OTIMIZADAS
# =========================================

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise Exception("❌ TOKEN não encontrado nas variáveis de ambiente.")

RECORDE = 456
FUSO_BRASIL = ZoneInfo("America/Sao_Paulo")

# AUMENTEI OS DELAYS PARA EVITAR RATE LIMIT
DELAY_ENTRE_MENSAGENS = 3
MAX_MENSSAGENS_POR_LOTE = 3
VERIFICAR_A_CADA_MINUTOS = 30

# Configurações
MAX_TICKETS_POR_USUARIO = 3
TEMPO_VERIFICACAO = 120
LIMITE_MENSAGENS_POR_MINUTO = 8
LIMITE_MENCOES_POR_MENSAGEM = 3
XP_POR_MENSAGEM = 5
XP_POR_MINUTO_CALL = 3

NIVEIS = {
    1: 100,
    2: 250,
    3: 500,
    4: 1000,
    5: 2000,
    10: 5000,
}

# Controle de rate limit GLOBAL
class RateLimiter:
    def __init__(self):
        self.last_request = 0
        self.min_interval = 0.5
    
    async def wait(self):
        now = time.time()
        elapsed = now - self.last_request
        if elapsed < self.min_interval:
            await asyncio.sleep(self.min_interval - elapsed)
        self.last_request = time.time()

rate_limiter = RateLimiter()

def agora():
    return datetime.now(FUSO_BRASIL)

def hoje():
    return agora().date()

# =========================================
# BANCO DE DADOS SQLITE - CORRIGIDO
# =========================================

class Database:
    def __init__(self):
        # check_same_thread=False permite usar em múltiplas threads
        self.conn = sqlite3.connect('bot_database.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.criar_tabelas()
    
    def criar_tabelas(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS memoriais (
                user_id TEXT PRIMARY KEY,
                nome TEXT,
                canal_id TEXT,
                dias INTEGER DEFAULT 0,
                apareceu_hoje INTEGER DEFAULT 0,
                ultima_data TEXT
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                canal_id TEXT,
                mensagem_id TEXT,
                status TEXT DEFAULT 'aberto',
                criado_em TEXT
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS xp (
                user_id TEXT PRIMARY KEY,
                xp INTEGER DEFAULT 0,
                nivel INTEGER DEFAULT 0,
                ultima_mensagem TEXT,
                tempo_call INTEGER DEFAULT 0
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS configuracoes (
                guild_id TEXT PRIMARY KEY,
                cargo_verificacao TEXT,
                canal_logs TEXT,
                canal_memoriais TEXT,
                cargo_nivel_1 TEXT,
                cargo_nivel_5 TEXT,
                cargo_nivel_10 TEXT
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS warns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                motivo TEXT,
                data TEXT,
                moderador TEXT
            )
        ''')
        
        self.conn.commit()
    
    def executar(self, query, params=()):
        self.cursor.execute(query, params)
        self.conn.commit()
        return self.cursor
    
    def fechar(self):
        self.conn.close()

# Instância única do banco (já com check_same_thread=False)
db = Database()

# =========================================
# WEB SERVER - CORRIGIDO
# =========================================

app = Flask(__name__)

@app.route("/")
def home():
    try:
        # CRIA UMA CONEXÃO NOVA PARA CADA REQUISIÇÃO (SOLUÇÃO MAIS SEGURA)
        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        
        memoriais = cursor.execute("SELECT COUNT(*) FROM memoriais").fetchone()[0]
        tickets = cursor.execute("SELECT COUNT(*) FROM tickets WHERE status='aberto'").fetchone()[0]
        
        conn.close()
        
        return {
            "status": "online",
            "bot": str(bot.user) if bot.user else "conectando",
            "hora": agora().strftime("%d/%m/%Y %H:%M:%S"),
            "memoriais": memoriais,
            "tickets": tickets
        }
    except Exception as e:
        return {"error": str(e)}, 500

@app.route("/stats")
def stats():
    try:
        # CRIA UMA CONEXÃO NOVA PARA CADA REQUISIÇÃO
        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        
        total_xp = cursor.execute("SELECT SUM(xp) FROM xp").fetchone()[0] or 0
        memoriais = cursor.execute("SELECT COUNT(*) FROM memoriais").fetchone()[0]
        tickets = cursor.execute("SELECT COUNT(*) FROM tickets WHERE status='aberto'").fetchone()[0]
        
        conn.close()
        
        return jsonify({
            "total_xp": total_xp,
            "total_memoriais": memoriais,
            "tickets_abertos": tickets
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def iniciar_web():
    porta = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=porta, threaded=True, use_reloader=False)

# Só inicia o web server se não estiver em debug
if not os.getenv("DEBUG"):
    Thread(target=iniciar_web, daemon=True).start()

# =========================================
# CONFIGURAÇÃO DO BOT
# =========================================

intents = discord.Intents.default()
intents.message_content = True
intents.presences = True
intents.voice_states = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None,
    max_messages=10000
)

# =========================================
# SISTEMA DE MEMORIAL
# =========================================

def get_memorial(user_id):
    result = db.cursor.execute(
        "SELECT * FROM memoriais WHERE user_id = ?", (str(user_id),)
    ).fetchone()
    if result:
        return {
            "user_id": result[0],
            "nome": result[1],
            "canal_id": result[2],
            "dias": result[3],
            "apareceu_hoje": bool(result[4]),
            "ultima_data": result[5]
        }
    return None

def criar_memorial(user_id, nome, canal_id):
    db.executar(
        "INSERT INTO memoriais VALUES (?, ?, ?, 0, 0, ?)",
        (str(user_id), nome, str(canal_id), hoje().isoformat())
    )

def marcou_presenca(user_id):
    db.executar(
        "UPDATE memoriais SET apareceu_hoje = 1 WHERE user_id = ?",
        (str(user_id),)
    )

# =========================================
# FRASES E GIFS
# =========================================

frases = [
    "🕯️ Mais um dia se passou. {nome} ainda não voltou ao servidor.",
    "🌧️ A saudade continua. Já são {dias} dias sem {nome}.",
    "💔 O lugar de {nome} continua vazio há {dias} dias.",
]

gifs = [
    "https://media.giphy.com/media/q2qxiBO5prG9i/giphy.gif",
    "https://media.giphy.com/media/13t22jOjxpkAN2/giphy.gif",
    "https://media.giphy.com/media/mBaNKEmk9SUKs/giphy.gif",
]

def criar_embed_memorial(memorial):
    dias = memorial["dias"]
    embed = discord.Embed(
        title="🌈 MEMORIAL DA SAUDADE",
        color=discord.Color.blue()
    )
    embed.description = (
        f"🕯️ **{dias} dias sem {memorial['nome']}**\n\n"
        f"{random.choice(frases).format(nome=memorial['nome'], dias=dias)}"
    )
    
    if dias < RECORDE:
        embed.add_field(
            name="🏆 Recorde",
            value=f"{RECORDE} dias (faltam {RECORDE - dias})",
            inline=False
        )
    elif dias == RECORDE:
        embed.color = discord.Color.gold()
        embed.add_field(name="👑 RECORDE ALCANÇADO!", value="Igualamos o maior tempo!", inline=False)
    else:
        embed.color = discord.Color.dark_purple()
        embed.add_field(name="🌌 NOVA ERA", value="Novo recorde sendo escrito!", inline=False)
    
    embed.set_image(url=random.choice(gifs))
    embed.set_footer(text=agora().strftime("%d/%m/%Y %H:%M"))
    return embed

# =========================================
# VERIFICAÇÃO DE DIAS
# =========================================

async def verificar_passagem_dos_dias():
    try:
        await rate_limiter.wait()
        
        hoje_atual = hoje()
        memoriais = db.cursor.execute("SELECT * FROM memoriais").fetchall()
        
        if not memoriais:
            return
        
        for memorial in memoriais:
            try:
                user_id, nome, canal_id, dias, apareceu_hoje, ultima_data = memorial
                
                ultima = date.fromisoformat(ultima_data)
                dias_passados = (hoje_atual - ultima).days
                
                if dias_passados <= 0:
                    continue
                
                canal = bot.get_channel(int(canal_id))
                if not canal:
                    continue
                
                if apareceu_hoje:
                    embed = discord.Embed(
                        title="🌈 RETORNO!",
                        color=discord.Color.green()
                    )
                    embed.description = f"**{nome}** voltou depois de {dias} dias!"
                    await canal.send(embed=embed)
                    await asyncio.sleep(1)
                    dias = 0
                else:
                    dias += 1
                    embed = criar_embed_memorial({
                        "nome": nome,
                        "dias": dias
                    })
                    await canal.send(embed=embed)
                    await asyncio.sleep(1.5)
                
                db.executar(
                    "UPDATE memoriais SET dias = ?, apareceu_hoje = 0, ultima_data = ? WHERE user_id = ?",
                    (dias, hoje_atual.isoformat(), user_id)
                )
                
                await asyncio.sleep(2)
                
            except Exception as e:
                print(f"⚠️ Erro no memorial {nome}: {e}")
                continue
                
    except Exception as e:
        print(f"❌ Erro na verificação: {e}")

# =========================================
# TICKETS
# =========================================

class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @ui.button(label="🎫 Abrir Ticket", style=ButtonStyle.green, custom_id="abrir_ticket")
    async def abrir_ticket(self, interaction: discord.Interaction, button: Button):
        user_id = str(interaction.user.id)
        
        abertos = db.cursor.execute(
            "SELECT COUNT(*) FROM tickets WHERE user_id = ? AND status = 'aberto'",
            (user_id,)
        ).fetchone()[0]
        
        if abertos >= MAX_TICKETS_POR_USUARIO:
            await interaction.response.send_message(
                f"❌ Limite de {MAX_TICKETS_POR_USUARIO} tickets!",
                ephemeral=True
            )
            return
        
        guild = interaction.guild
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        staff_role = discord.utils.get(guild.roles, name="Staff")
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        
        channel = await guild.create_text_channel(
            f"ticket-{interaction.user.name[:10]}",
            overwrites=overwrites
        )
        
        db.executar(
            "INSERT INTO tickets (user_id, canal_id, criado_em) VALUES (?, ?, ?)",
            (user_id, str(channel.id), agora().isoformat())
        )
        
        embed = discord.Embed(
            title="🎫 Ticket",
            description=f"Olá {interaction.user.mention}! Como podemos ajudar?",
            color=discord.Color.green()
        )
        embed.set_footer(text=f"ID: {db.cursor.lastrowid}")
        
        await channel.send(embed=embed)
        await interaction.response.send_message(f"✅ Ticket em {channel.mention}!", ephemeral=True)

class TicketControlView(View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @ui.button(label="🔒 Fechar", style=ButtonStyle.danger, custom_id="fechar_ticket")
    async def fechar_ticket(self, interaction: discord.Interaction, button: Button):
        canal_id = str(interaction.channel_id)
        
        db.executar(
            "UPDATE tickets SET status = 'fechado' WHERE canal_id = ?",
            (canal_id,)
        )
        
        await interaction.response.send_message("🔒 Fechando em 3 segundos...")
        await asyncio.sleep(3)
        await interaction.channel.delete()

# =========================================
# SISTEMA DE XP
# =========================================

def adicionar_xp(user_id, quantidade):
    usuario = db.cursor.execute(
        "SELECT xp FROM xp WHERE user_id = ?", (str(user_id),)
    ).fetchone()
    
    if usuario:
        xp_atual = usuario[0] + quantidade
        db.executar(
            "UPDATE xp SET xp = ? WHERE user_id = ?",
            (xp_atual, str(user_id))
        )
    else:
        xp_atual = quantidade
        db.executar(
            "INSERT INTO xp (user_id, xp) VALUES (?, ?)",
            (str(user_id), xp_atual)
        )
    
    return xp_atual

# =========================================
# MODERAÇÃO
# =========================================

class ModerationSystem:
    def __init__(self):
        self.message_buffer = defaultdict(list)
    
    async def verificar_mensagem(self, message):
        if message.author.bot:
            return False
        
        agora_msg = datetime.now()
        self.message_buffer[message.author.id].append(agora_msg)
        
        self.message_buffer[message.author.id] = [
            t for t in self.message_buffer[message.author.id]
            if (agora_msg - t).total_seconds() < 60
        ]
        
        if len(self.message_buffer[message.author.id]) > LIMITE_MENSAGENS_POR_MINUTO:
            await message.delete()
            await message.channel.send(
                f"⚠️ {message.author.mention} spam detectado!",
                delete_after=3
            )
            return True
        
        return False

mod_system = ModerationSystem()

# =========================================
# EVENTOS
# =========================================

@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}")
    await bot.wait_until_ready()
    
    try:
        await rate_limiter.wait()
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} comandos sincronizados")
    except Exception as e:
        print(f"❌ Erro ao sincronizar: {e}")
    
    await asyncio.sleep(5)
    await verificar_passagem_dos_dias()
    
    if not verificar_sistema.is_running():
        verificar_sistema.start()

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    await rate_limiter.wait()
    
    if await mod_system.verificar_mensagem(message):
        return
    
    adicionar_xp(message.author.id, XP_POR_MENSAGEM)
    
    if get_memorial(message.author.id):
        marcou_presenca(message.author.id)
    
    await bot.process_commands(message)

@bot.event
async def on_member_join(member):
    await rate_limiter.wait()
    pass

@bot.event
async def on_voice_state_update(member, before, after):
    await rate_limiter.wait()
    if get_memorial(member.id):
        marcou_presenca(member.id)

# =========================================
# LOOP OTIMIZADO
# =========================================

@tasks.loop(minutes=VERIFICAR_A_CADA_MINUTOS)
async def verificar_sistema():
    try:
        await verificar_passagem_dos_dias()
    except Exception as e:
        print(f"❌ Erro no loop: {e}")

# =========================================
# COMANDOS SLASH
# =========================================

@bot.tree.command(name="verificar", description="Verifica seu acesso")
async def verificar(interaction: discord.Interaction):
    await rate_limiter.wait()
    await interaction.response.send_message("✅ Verificado!", ephemeral=True)

@bot.tree.command(name="ticket", description="Abre um ticket")
async def ticket(interaction: discord.Interaction):
    await rate_limiter.wait()
    view = TicketView()
    embed = discord.Embed(
        title="🎫 Tickets",
        description="Clique no botão para abrir um ticket.",
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="fechar", description="Fecha o ticket")
async def fechar(interaction: discord.Interaction):
    await rate_limiter.wait()
    canal_id = str(interaction.channel_id)
    ticket = db.cursor.execute(
        "SELECT * FROM tickets WHERE canal_id = ? AND status = 'aberto'",
        (canal_id,)
    ).fetchone()
    
    if not ticket:
        await interaction.response.send_message("❌ Não é um ticket.", ephemeral=True)
        return
    
    db.executar(
        "UPDATE tickets SET status = 'fechado' WHERE canal_id = ?",
        (canal_id,)
    )
    
    await interaction.response.send_message("🔒 Fechando...")
    await asyncio.sleep(3)
    await interaction.channel.delete()

@bot.tree.command(name="ranking", description="Ranking de XP")
async def ranking(interaction: discord.Interaction):
    await rate_limiter.wait()
    resultados = db.cursor.execute(
        "SELECT user_id, xp, nivel FROM xp ORDER BY xp DESC LIMIT 10"
    ).fetchall()
    
    if not resultados:
        await interaction.response.send_message("📊 Sem XP ainda!", ephemeral=True)
        return
    
    embed = discord.Embed(title="🏆 Ranking", color=discord.Color.gold())
    desc = ""
    for i, (user_id, xp, nivel) in enumerate(resultados, 1):
        try:
            user = await bot.fetch_user(int(user_id))
            nome = user.display_name[:15]
        except:
            nome = user_id[:8]
        
        emoji = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}°"
        desc += f"{emoji} {nome} - Nv{nivel} ({xp} XP)\n"
    
    embed.description = desc
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="dias", description="Status do memorial")
async def dias(interaction: discord.Interaction, usuario: discord.Member = None):
    await rate_limiter.wait()
    if not usuario:
        usuario = interaction.user
    
    memorial = get_memorial(usuario.id)
    if not memorial:
        await interaction.response.send_message("❌ Sem memorial.", ephemeral=True)
        return
    
    embed = criar_embed_memorial(memorial)
    await interaction.response.send_message(embed=embed)

# =========================================
# INICIAR BOT
# =========================================

if __name__ == "__main__":
    print("🚀 Iniciando Bot Supremo...")
    try:
        bot.run(TOKEN, reconnect=True)
    except discord.errors.HTTPException as e:
        print(f"❌ Erro HTTP: {e}")
        if "429" in str(e):
            print("⏳ Aguardando 60 segundos antes de tentar novamente...")
            time.sleep(60)
            bot.run(TOKEN, reconnect=True)
    except Exception as e:
        print(f"❌ Erro: {e}")
