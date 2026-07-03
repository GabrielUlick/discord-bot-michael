import discord
from discord.ext import commands, tasks
from discord import app_commands, ui, ButtonStyle, SelectOption
from discord.ui import Button, View, Select

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
from collections import defaultdict, Counter

# =========================================
# CONFIGURAÇÕES
# =========================================

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise Exception("❌ TOKEN não encontrado nas variáveis de ambiente.")

RECORDE = 456
FUSO_BRASIL = ZoneInfo("America/Sao_Paulo")
DELAY_ENTRE_MENSAGENS = 2
MAX_MENSSAGENS_POR_LOTE = 5

# Configurações dos novos módulos
MAX_TICKETS_POR_USUARIO = 3
TEMPO_VERIFICACAO = 60  # segundos
LIMITE_MENSAGENS_POR_MINUTO = 10
LIMITE_MENCOES_POR_MENSAGEM = 3
XP_POR_MENSAGEM = 10
XP_POR_MINUTO_CALL = 5
NIVEIS = {
    1: 100,    # Nível 1: 100 XP
    2: 250,    # Nível 2: 250 XP
    3: 500,    # Nível 3: 500 XP
    4: 1000,   # Nível 4: 1000 XP
    5: 2000,   # Nível 5: 2000 XP
    10: 5000,  # Nível 10: 5000 XP
}

def agora():
    return datetime.now(FUSO_BRASIL)

def hoje():
    return agora().date()

# =========================================
# BANCO DE DADOS SQLITE (Melhor que JSON)
# =========================================

class Database:
    def __init__(self):
        self.conn = sqlite3.connect('bot_database.db')
        self.cursor = self.conn.cursor()
        self.criar_tabelas()
    
    def criar_tabelas(self):
        # Tabela de memoriais
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
        
        # Tabela de tickets
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
        
        # Tabela de XP e níveis
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS xp (
                user_id TEXT PRIMARY KEY,
                xp INTEGER DEFAULT 0,
                nivel INTEGER DEFAULT 0,
                ultima_mensagem TEXT,
                tempo_call INTEGER DEFAULT 0
            )
        ''')
        
        # Tabela de configurações do servidor
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
        
        # Tabela de warns/penalidades
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

db = Database()

# =========================================
# WEB SERVER
# =========================================

app = Flask(__name__)

@app.route("/")
def home():
    return {
        "status": "online",
        "bot": str(bot.user) if bot.user else "conectando",
        "hora": agora().strftime("%d/%m/%Y %H:%M:%S"),
        "memoriais": db.cursor.execute("SELECT COUNT(*) FROM memoriais").fetchone()[0],
        "tickets": db.cursor.execute("SELECT COUNT(*) FROM tickets WHERE status='aberto'").fetchone()[0]
    }

@app.route("/stats")
def stats():
    total_xp = db.cursor.execute("SELECT SUM(xp) FROM xp").fetchone()[0] or 0
    return jsonify({
        "total_xp": total_xp,
        "total_memoriais": db.cursor.execute("SELECT COUNT(*) FROM memoriais").fetchone()[0],
        "tickets_abertos": db.cursor.execute("SELECT COUNT(*) FROM tickets WHERE status='aberto'").fetchone()[0]
    })

def iniciar_web():
    porta = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=porta, threaded=True, use_reloader=False)

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
    help_command=None
)

# =========================================
# SISTEMA DE MEMORIAL (Adaptado para SQLite)
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
    "📻 Tentamos chamar {nome}, mas ainda não houve resposta.",
    "🌙 A noite chega e {nome} continua ausente. Dia {dias}.",
    "😔 O servidor sente falta de {nome} há {dias} dias.",
    "📅 O calendário avança. {dias} dias desde a última aparição de {nome}.",
    "🌈 O memorial de {nome} continua aceso."
]

gifs = [
    "https://media.giphy.com/media/q2qxiBO5prG9i/giphy.gif",
    "https://media.giphy.com/media/13t22jOjxpkAN2/giphy.gif",
    "https://media.giphy.com/media/mBaNKEmk9SUKs/giphy.gif",
    "https://media.giphy.com/media/d7rvF20PqNuGKSQGhf/giphy.gif",
    "https://media.giphy.com/media/bqZadRhjePrJeqONfL/giphy.gif",
    "https://media.giphy.com/media/3QWfMsI8IaarXxtBt6/giphy.gif",
    "https://media.giphy.com/media/AzRo1Y4WlDSY7NohuJ/giphy.gif",
    "https://media.giphy.com/media/5c2aGDKZgCx7gV3QpZ/giphy.gif",
    "https://media.giphy.com/media/7uowYcS5MHuZT4f9Rr/giphy.gif",
    "https://media.giphy.com/media/3oEjI80DSa1grNPTDq/giphy.gif",
    "https://media.giphy.com/media/OzlmyoTC2n3aOTXGFi/giphy.gif"
]

# =========================================
# SISTEMA DE TICKETS (NOVO)
# =========================================

class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @ui.button(label="🎫 Abrir Ticket", style=ButtonStyle.green, custom_id="abrir_ticket")
    async def abrir_ticket(self, interaction: discord.Interaction, button: Button):
        user_id = str(interaction.user.id)
        
        # Verifica limite de tickets
        abertos = db.cursor.execute(
            "SELECT COUNT(*) FROM tickets WHERE user_id = ? AND status = 'aberto'",
            (user_id,)
        ).fetchone()[0]
        
        if abertos >= MAX_TICKETS_POR_USUARIO:
            await interaction.response.send_message(
                f"❌ Você já tem {abertos} tickets abertos! Feche um antes de abrir outro.",
                ephemeral=True
            )
            return
        
        # Cria canal do ticket
        guild = interaction.guild
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        # Adiciona permissão para staff
        staff_role = discord.utils.get(guild.roles, name="Staff")
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        
        channel = await guild.create_text_channel(
            f"ticket-{interaction.user.name}",
            overwrites=overwrites,
            category=discord.utils.get(guild.categories, name="Tickets")
        )
        
        # Salva no banco
        db.executar(
            "INSERT INTO tickets (user_id, canal_id, criado_em) VALUES (?, ?, ?)",
            (user_id, str(channel.id), agora().isoformat())
        )
        
        # Mensagem inicial
        embed = discord.Embed(
            title="🎫 Ticket Aberto",
            description=f"Olá {interaction.user.mention}! Como podemos ajudar você?",
            color=discord.Color.green()
        )
        embed.add_field(name="ℹ️", value="Use `/ticket fechar` quando terminar.", inline=False)
        embed.set_footer(text=f"ID do Ticket: {db.cursor.lastrowid}")
        
        view = TicketControlView()
        await channel.send(embed=embed, view=view)
        
        await interaction.response.send_message(
            f"✅ Ticket criado em {channel.mention}!",
            ephemeral=True
        )

class TicketControlView(View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @ui.button(label="🔒 Fechar Ticket", style=ButtonStyle.danger, custom_id="fechar_ticket")
    async def fechar_ticket(self, interaction: discord.Interaction, button: Button):
        canal_id = str(interaction.channel_id)
        
        # Verifica se é um ticket
        ticket = db.cursor.execute(
            "SELECT * FROM tickets WHERE canal_id = ? AND status = 'aberto'",
            (canal_id,)
        ).fetchone()
        
        if not ticket:
            await interaction.response.send_message("❌ Este não é um ticket válido.", ephemeral=True)
            return
        
        # Salva histórico
        historico = []
        async for msg in interaction.channel.history(limit=None, oldest_first=True):
            historico.append(f"{msg.author}: {msg.content}")
        
        with open(f"ticket_{ticket[0]}_historico.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(historico))
        
        # Fecha ticket
        db.executar(
            "UPDATE tickets SET status = 'fechado' WHERE canal_id = ?",
            (canal_id,)
        )
        
        await interaction.response.send_message("🔒 Ticket sendo fechado em 5 segundos...")
        await asyncio.sleep(5)
        await interaction.channel.delete()

# =========================================
# SISTEMA DE NÍVEIS E XP (NOVO)
# =========================================

def get_nivel(xp):
    nivel = 0
    for n, xp_necessario in sorted(NIVEIS.items()):
        if xp >= xp_necessario:
            nivel = n
    return nivel

def adicionar_xp(user_id, quantidade):
    # Busca ou cria registro
    usuario = db.cursor.execute(
        "SELECT xp, nivel FROM xp WHERE user_id = ?", (str(user_id),)
    ).fetchone()
    
    if usuario:
        xp_atual = usuario[0] + quantidade
        nivel_atual = get_nivel(xp_atual)
        db.executar(
            "UPDATE xp SET xp = ?, nivel = ? WHERE user_id = ?",
            (xp_atual, nivel_atual, str(user_id))
        )
    else:
        xp_atual = quantidade
        nivel_atual = get_nivel(xp_atual)
        db.executar(
            "INSERT INTO xp (user_id, xp, nivel) VALUES (?, ?, ?)",
            (str(user_id), xp_atual, nivel_atual)
        )
    
    return xp_atual, nivel_atual

async def verificar_nivel(member, novo_nivel):
    """Verifica se o membro ganhou um cargo por nível"""
    config = db.cursor.execute(
        "SELECT * FROM configuracoes WHERE guild_id = ?", (str(member.guild.id),)
    ).fetchone()
    
    if not config:
        return
    
    cargos_niveis = {
        1: config[3],   # cargo_nivel_1
        5: config[4],   # cargo_nivel_5
        10: config[5]   # cargo_nivel_10
    }
    
    for nivel, cargo_id in cargos_niveis.items():
        if novo_nivel >= nivel and cargo_id:
            cargo = member.guild.get_role(int(cargo_id))
            if cargo and cargo not in member.roles:
                await member.add_roles(cargo)
                await member.send(f"🎉 Parabéns! Você alcançou o nível {nivel} e ganhou o cargo {cargo.name}!")

# =========================================
# SISTEMA DE MODERAÇÃO AUTOMÁTICA (NOVO)
# =========================================

class ModerationSystem:
    def __init__(self):
        self.message_buffer = defaultdict(list)
        self.mention_buffer = defaultdict(int)
    
    async def verificar_mensagem(self, message):
        if message.author.bot:
            return False
        
        # Verifica spam de mensagens
        agora_msg = datetime.now()
        self.message_buffer[message.author.id].append(agora_msg)
        
        # Remove mensagens antigas
        self.message_buffer[message.author.id] = [
            t for t in self.message_buffer[message.author.id]
            if (agora_msg - t).total_seconds() < 60
        ]
        
        if len(self.message_buffer[message.author.id]) > LIMITE_MENSAGENS_POR_MINUTO:
            await message.delete()
            await message.channel.send(
                f"⚠️ {message.author.mention}, você está enviando mensagens muito rápido!",
                delete_after=5
            )
            return True
        
        # Verifica menções em massa
        mentions = len(message.mentions)
        if mentions > LIMITE_MENCOES_POR_MENSAGEM:
            await message.delete()
            await message.channel.send(
                f"⚠️ {message.author.mention}, muitas menções em uma mensagem!",
                delete_after=5
            )
            return True
        
        # Verifica links suspeitos
        if re.search(r'(discord\.gg|discordapp\.com/invite|http[s]?://)', message.content):
            # Permite links apenas em canais específicos
            canais_permitidos = ['links', 'geral']
            if not any(canal in message.channel.name.lower() for canal in canais_permitidos):
                # Verifica se é membro verificado (tem cargo específico)
                cargo_verificacao = discord.utils.get(message.guild.roles, name="Verificado")
                if not cargo_verificacao or cargo_verificacao not in message.author.roles:
                    await message.delete()
                    await message.channel.send(
                        f"⚠️ {message.author.mention}, links só são permitidos em canais específicos ou para membros verificados!",
                        delete_after=5
                    )
                    return True
        
        return False
    
    async def verificar_entrada(self, member):
        """Sistema de verificação para novos membros"""
        config = db.cursor.execute(
            "SELECT cargo_verificacao FROM configuracoes WHERE guild_id = ?",
            (str(member.guild.id),)
        ).fetchone()
        
        if not config or not config[0]:
            return
        
        cargo = member.guild.get_role(int(config[0]))
        if not cargo:
            return
        
        # Move para canal de verificação
        canal_verificacao = discord.utils.get(member.guild.text_channels, name="verificação")
        if canal_verificacao:
            embed = discord.Embed(
                title="🔐 Verificação",
                description=f"{member.mention}, para verificar seu acesso, digite `/verificar` neste canal.",
                color=discord.Color.blue()
            )
            await canal_verificacao.send(embed=embed)
            
            # Timer para kick automático
            await asyncio.sleep(TEMPO_VERIFICACAO)
            
            # Verifica se ainda não tem o cargo
            if cargo not in member.roles:
                await member.kick(reason="Não verificou dentro do tempo limite")
    
    async def verificar_saida(self, member):
        """Monitora se um membro saiu do servidor"""
        # Atualiza memorial se existir
        if get_memorial(member.id):
            # Já está sendo monitorado pelo sistema
            pass

mod_system = ModerationSystem()

# =========================================
# COMANDOS SLASH (Novo formato)
# =========================================

class BotaoVerificar(View):
    def __init__(self, cargo_id):
        super().__init__(timeout=None)
        self.cargo_id = cargo_id
    
    @ui.button(label="✅ Verificar", style=ButtonStyle.green, custom_id="verificar")
    async def verificar(self, interaction: discord.Interaction, button: Button):
        cargo = interaction.guild.get_role(self.cargo_id)
        if cargo:
            await interaction.user.add_roles(cargo)
            await interaction.response.send_message(
                "✅ Você foi verificado com sucesso!",
                ephemeral=True
            )

@bot.tree.command(name="verificar", description="Verifica seu acesso ao servidor")
async def verificar(interaction: discord.Interaction):
    config = db.cursor.execute(
        "SELECT cargo_verificacao FROM configuracoes WHERE guild_id = ?",
        (str(interaction.guild_id),)
    ).fetchone()
    
    if not config or not config[0]:
        await interaction.response.send_message("❌ Sistema de verificação não configurado.", ephemeral=True)
        return
    
    cargo = interaction.guild.get_role(int(config[0]))
    if not cargo:
        await interaction.response.send_message("❌ Cargo de verificação não encontrado.", ephemeral=True)
        return
    
    if cargo in interaction.user.roles:
        await interaction.response.send_message("✅ Você já está verificado!", ephemeral=True)
        return
    
    await interaction.user.add_roles(cargo)
    await interaction.response.send_message("✅ Você foi verificado com sucesso!", ephemeral=True)

@bot.tree.command(name="ticket", description="Abre um ticket de suporte")
async def ticket(interaction: discord.Interaction):
    view = TicketView()
    embed = discord.Embed(
        title="🎫 Sistema de Tickets",
        description="Clique no botão abaixo para abrir um ticket de suporte.",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="ℹ️",
        value=f"Limite de {MAX_TICKETS_POR_USUARIO} tickets por usuário.",
        inline=False
    )
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="fechar", description="Fecha o ticket atual")
async def fechar(interaction: discord.Interaction):
    canal_id = str(interaction.channel_id)
    ticket = db.cursor.execute(
        "SELECT * FROM tickets WHERE canal_id = ? AND status = 'aberto'",
        (canal_id,)
    ).fetchone()
    
    if not ticket:
        await interaction.response.send_message("❌ Este não é um ticket válido.", ephemeral=True)
        return
    
    # Salva histórico
    historico = []
    async for msg in interaction.channel.history(limit=None, oldest_first=True):
        historico.append(f"{msg.author}: {msg.content}")
    
    with open(f"ticket_{ticket[0]}_historico.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(historico))
    
    db.executar(
        "UPDATE tickets SET status = 'fechado' WHERE canal_id = ?",
        (canal_id,)
    )
    
    await interaction.response.send_message("🔒 Ticket sendo fechado em 5 segundos...")
    await asyncio.sleep(5)
    await interaction.channel.delete()

@bot.tree.command(name="ranking", description="Mostra o ranking de XP do servidor")
async def ranking(interaction: discord.Interaction):
    resultados = db.cursor.execute(
        "SELECT user_id, xp, nivel FROM xp ORDER BY xp DESC LIMIT 10"
    ).fetchall()
    
    if not resultados:
        await interaction.response.send_message("📊 Ninguém tem XP ainda!", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="🏆 Ranking de XP",
        color=discord.Color.gold()
    )
    
    descricao = ""
    for i, (user_id, xp, nivel) in enumerate(resultados, 1):
        try:
            user = await bot.fetch_user(int(user_id))
            nome = user.display_name
        except:
            nome = user_id[:8]
        
        medalhas = ["🥇", "🥈", "🥉"]
        emoji = medalhas[i-1] if i <= 3 else f"{i}°"
        descricao += f"{emoji} **{nome}** - Nível {nivel} ({xp} XP)\n"
    
    embed.description = descricao
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="configurar_cargos", description="[ADMIN] Configura cargos por nível")
@app_commands.default_permissions(administrator=True)
async def configurar_cargos(
    interaction: discord.Interaction,
    nivel_1: discord.Role = None,
    nivel_5: discord.Role = None,
    nivel_10: discord.Role = None
):
    guild_id = str(interaction.guild_id)
    
    # Verifica se já existe configuração
    config = db.cursor.execute(
        "SELECT * FROM configuracoes WHERE guild_id = ?", (guild_id,)
    ).fetchone()
    
    if config:
        db.executar(
            """UPDATE configuracoes SET 
               cargo_nivel_1 = ?, cargo_nivel_5 = ?, cargo_nivel_10 = ? 
               WHERE guild_id = ?""",
            (str(nivel_1.id) if nivel_1 else None,
             str(nivel_5.id) if nivel_5 else None,
             str(nivel_10.id) if nivel_10 else None,
             guild_id)
        )
    else:
        db.executar(
            """INSERT INTO configuracoes (guild_id, cargo_nivel_1, cargo_nivel_5, cargo_nivel_10)
               VALUES (?, ?, ?, ?)""",
            (guild_id,
             str(nivel_1.id) if nivel_1 else None,
             str(nivel_5.id) if nivel_5 else None,
             str(nivel_10.id) if nivel_10 else None)
        )
    
    await interaction.response.send_message(
        "✅ Configurações de cargos atualizadas!",
        ephemeral=True
    )

@bot.tree.command(name="configurar_verificacao", description="[ADMIN] Configura sistema de verificação")
@app_commands.default_permissions(administrator=True)
async def configurar_verificacao(
    interaction: discord.Interaction,
    cargo: discord.Role
):
    guild_id = str(interaction.guild_id)
    db.executar(
        "INSERT OR REPLACE INTO configuracoes (guild_id, cargo_verificacao) VALUES (?, ?)",
        (guild_id, str(cargo.id))
    )
    
    await interaction.response.send_message(
        f"✅ Sistema de verificação configurado com cargo {cargo.mention}!",
        ephemeral=True
    )

@bot.tree.command(name="configurar_memorial", description="[ADMIN] Configura memorial")
@app_commands.default_permissions(administrator=True)
async def configurar_memorial(
    interaction: discord.Interaction,
    usuario: discord.Member,
    canal: discord.TextChannel
):
    if get_memorial(usuario.id):
        await interaction.response.send_message(
            f"⚠️ {usuario.mention} já tem um memorial configurado!",
            ephemeral=True
        )
        return
    
    criar_memorial(usuario.id, usuario.display_name, canal.id)
    
    await interaction.response.send_message(
        f"✅ Memorial de {usuario.mention} configurado no canal {canal.mention}!",
        ephemeral=True
    )

# =========================================
# EVENTOS
# =========================================

@bot.event
async def on_ready():
    print(f"🌈 Bot conectado como {bot.user}")
    await bot.wait_until_ready()
    
    # Sincroniza comandos slash
    try:
        synced = await bot.tree.sync()
        print(f"✅ Sincronizados {len(synced)} comandos slash")
    except Exception as e:
        print(f"❌ Erro ao sincronizar: {e}")
    
    # Verifica memoriais
    await verificar_passagem_dos_dias()
    
    if not verificar_sistema.is_running():
        verificar_sistema.start()

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    # Sistema de moderação automática
    if await mod_system.verificar_mensagem(message):
        return
    
    # Sistema de XP
    xp_ganho = XP_POR_MENSAGEM
    novo_xp, novo_nivel = adicionar_xp(message.author.id, xp_ganho)
    await verificar_nivel(message.author, novo_nivel)
    
    # Verifica presença em memorial
    if get_memorial(message.author.id):
        marcou_presenca(message.author.id)
    
    await bot.process_commands(message)

@bot.event
async def on_member_join(member):
    await mod_system.verificar_entrada(member)

@bot.event
async def on_member_remove(member):
    await mod_system.verificar_saida(member)

@bot.event
async def on_voice_state_update(member, before, after):
    # Sistema de XP por call
    if after.channel and not before.channel:  # Entrou na call
        # Inicia contagem de tempo
        db.executar(
            "UPDATE xp SET tempo_call = 0 WHERE user_id = ?",
            (str(member.id),)
        )
    elif before.channel and not after.channel:  # Saiu da call
        # Adiciona XP pelo tempo em call
        tempo = db.cursor.execute(
            "SELECT tempo_call FROM xp WHERE user_id = ?",
            (str(member.id),)
        ).fetchone()
        
        if tempo and tempo[0] > 0:
            xp_ganho = (tempo[0] // 60) * XP_POR_MINUTO_CALL
            if xp_ganho > 0:
                adicionar_xp(member.id, xp_ganho)
    
    # Verifica memorial
    if get_memorial(member.id):
        marcou_presenca(member.id)

# =========================================
# SISTEMA DE CONTAGEM (Adaptado para SQLite)
# =========================================

async def verificar_passagem_dos_dias():
    hoje_atual = hoje()
    memoriais = db.cursor.execute("SELECT * FROM memoriais").fetchall()
    
    for memorial in memoriais:
        user_id, nome, canal_id, dias, apareceu_hoje, ultima_data = memorial
        
        try:
            ultima = date.fromisoformat(ultima_data)
            dias_passados = (hoje_atual - ultima).days
            
            if dias_passados <= 0:
                continue
            
            canal = bot.get_channel(int(canal_id))
            if not canal:
                print(f"⚠️ Canal de {nome} não encontrado.")
                continue
            
            for _ in range(dias_passados):
                if apareceu_hoje:
                    # Mensagem de retorno
                    embed = discord.Embed(
                        title="🌈 UM RETORNO INESPERADO 🌈",
                        color=discord.Color.green()
                    )
                    embed.description = f"😭 Depois de **{dias} dias**, **{nome}** apareceu novamente."
                    await canal.send(embed=embed)
                    dias = 0
                else:
                    dias += 1
                    embed = criar_embed_memorial({
                        "nome": nome,
                        "dias": dias
                    })
                    await canal.send(embed=embed)
                
                await asyncio.sleep(DELAY_ENTRE_MENSAGENS)
            
            # Atualiza no banco
            db.executar(
                "UPDATE memoriais SET dias = ?, apareceu_hoje = 0, ultima_data = ? WHERE user_id = ?",
                (dias, hoje_atual.isoformat(), user_id)
            )
            
        except Exception as e:
            print(f"❌ Erro ao processar memorial {user_id}: {e}")

def criar_embed_memorial(memorial):
    dias = memorial["dias"]
    embed = discord.Embed(
        title="🌈 ═══ MEMORIAL DA SAUDADE ═══ 🌈",
        color=discord.Color.blue()
    )
    embed.description = (
        f"🕯️ **Hoje são {dias} dias sem {memorial['nome']}**\n\n"
        f"{random.choice(frases).format(nome=memorial['nome'], dias=dias)}"
    )
    
    if dias < RECORDE:
        faltam = RECORDE - dias
        embed.add_field(
            name="🏆 Recorde Histórico",
            value=f"{RECORDE} dias\n⏳ Faltam {faltam} dias para alcançar.",
            inline=False
        )
    elif dias == RECORDE:
        embed.color = discord.Color.gold()
        embed.add_field(
            name="👑 RECORDE ALCANÇADO",
            value="Hoje igualamos o maior tempo de ausência!",
            inline=False
        )
    else:
        embed.color = discord.Color.dark_purple()
        embed.add_field(
            name="🌌 NOVA ERA",
            value="Um novo recorde está sendo escrito.",
            inline=False
        )
    
    embed.set_image(url=random.choice(gifs))
    embed.set_footer(
        text="Atualizado em " + agora().strftime("%d/%m/%Y às %H:%M")
    )
    return embed

@tasks.loop(minutes=10)
async def verificar_sistema():
    try:
        await verificar_passagem_dos_dias()
    except Exception as e:
        print(f"❌ Erro no loop: {e}")

# =========================================
# COMANDOS DE ADMIN (Slash)
# =========================================

@bot.tree.command(name="warn", description="[ADMIN] Adverte um usuário")
@app_commands.default_permissions(administrator=True)
async def warn(interaction: discord.Interaction, usuario: discord.Member, motivo: str):
    db.executar(
        "INSERT INTO warns (user_id, motivo, data, moderador) VALUES (?, ?, ?, ?)",
        (str(usuario.id), motivo, agora().isoformat(), str(interaction.user.id))
    )
    
    embed = discord.Embed(
        title="⚠️ Advertência",
        description=f"{usuario.mention} foi advertido!",
        color=discord.Color.orange()
    )
    embed.add_field(name="Motivo", value=motivo, inline=False)
    embed.add_field(name="Moderador", value=interaction.user.mention, inline=True)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="limpar", description="[ADMIN] Limpa mensagens do canal")
@app_commands.default_permissions(administrator=True)
async def limpar(interaction: discord.Interaction, quantidade: int):
    if quantidade > 100:
        await interaction.response.send_message("❌ Máximo de 100 mensagens por vez.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    deletados = await interaction.channel.purge(limit=quantidade)
    await interaction.followup.send(f"✅ {len(deletados)} mensagens deletadas!", ephemeral=True)

@bot.tree.command(name="silenciar", description="[ADMIN] Silencia um usuário")
@app_commands.default_permissions(administrator=True)
async def silenciar(
    interaction: discord.Interaction,
    usuario: discord.Member,
    tempo_minutos: int,
    motivo: str = "Sem motivo"
):
    timeout = timedelta(minutes=tempo_minutos)
    await usuario.timeout(timeout, reason=motivo)
    
    embed = discord.Embed(
        title="🔇 Usuário Silenciado",
        description=f"{usuario.mention} foi silenciado por {tempo_minutos} minutos.",
        color=discord.Color.red()
    )
    embed.add_field(name="Motivo", value=motivo, inline=False)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="desilenciar", description="[ADMIN] Remove o silêncio de um usuário")
@app_commands.default_permissions(administrator=True)
async def desilenciar(interaction: discord.Interaction, usuario: discord.Member):
    await usuario.timeout(None)
    await interaction.response.send_message(f"✅ {usuario.mention} foi desilenciado!")

# =========================================
# COMANDOS DE UTILIDADE
# =========================================

@bot.tree.command(name="enquete", description="Cria uma enquete")
async def enquete(
    interaction: discord.Interaction,
    pergunta: str,
    opcao1: str,
    opcao2: str,
    opcao3: str = None,
    opcao4: str = None
):
    opcoes = [opcao1, opcao2]
    if opcao3:
        opcoes.append(opcao3)
    if opcao4:
        opcoes.append(opcao4)
    
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]
    descricao = "\n".join([f"{emojis[i]} {op}" for i, op in enumerate(opcoes)])
    
    embed = discord.Embed(
        title=f"📊 Enquete: {pergunta}",
        description=descricao,
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"Criado por {interaction.user.display_name}")
    
    message = await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()
    
    for i in range(len(opcoes)):
        await msg.add_reaction(emojis[i])

@bot.tree.command(name="sorteio", description="Realiza um sorteio no canal")
async def sorteio(interaction: discord.Interaction, premio: str, duracao_minutos: int):
    await interaction.response.send_message(
        f"🎉 **SORTEIO INICIADO!** 🎉\nPrêmio: **{premio}**\nReaja com 🎉 para participar!\nTempo: {duracao_minutos} minutos"
    )
    
    msg = await interaction.original_response()
    await msg.add_reaction("🎉")
    
    await asyncio.sleep(duracao_minutos * 60)
    
    msg_atualizada = await interaction.channel.fetch_message(msg.id)
    participantes = []
    
    for reaction in msg_atualizada.reactions:
        if str(reaction.emoji) == "🎉":
            async for user in reaction.users():
                if not user.bot:
                    participantes.append(user)
    
    if participantes:
        vencedor = random.choice(participantes)
        await interaction.channel.send(f"🎊 **{vencedor.mention}** ganhou o sorteio de **{premio}**! Parabéns! 🎊")
    else:
        await interaction.channel.send("❌ Ninguém participou do sorteio!")

@bot.tree.command(name="userinfo", description="Mostra informações de um usuário")
async def userinfo(interaction: discord.Interaction, usuario: discord.Member = None):
    if not usuario:
        usuario = interaction.user
    
    embed = discord.Embed(
        title=f"ℹ️ Informações de {usuario.display_name}",
        color=usuario.color
    )
    embed.set_thumbnail(url=usuario.display_avatar.url)
    embed.add_field(name="ID", value=usuario.id, inline=False)
    embed.add_field(name="Entrou em", value=usuario.joined_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name="Criado em", value=usuario.created_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name="Cargos", value=", ".join([role.mention for role in usuario.roles[1:5]]) or "Nenhum", inline=False)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="dias", description="Mostra status do memorial")
async def dias(interaction: discord.Interaction, usuario: discord.Member = None):
    if not usuario:
        usuario = interaction.user
    
    memorial = get_memorial(usuario.id)
    if not memorial:
        await interaction.response.send_message(
            f"❌ {usuario.mention} não tem memorial configurado.",
            ephemeral=True
        )
        return
    
    embed = criar_embed_memorial(memorial)
    await interaction.response.send_message(embed=embed)

# =========================================
# COMANDOS DE VOZ
# =========================================

@bot.tree.command(name="call", description="Gerencia a call atual")
async def call(
    interaction: discord.Interaction,
    acao: str = None,  # lock, unlock, bitrate, info
    bitrate: int = None
):
    if not interaction.user.voice:
        await interaction.response.send_message("❌ Você não está em uma call!", ephemeral=True)
        return
    
    channel = interaction.user.voice.channel
    
    if acao == "lock":
        await channel.set_permissions(interaction.guild.default_role, connect=False)
        await interaction.response.send_message(f"🔒 {channel.mention} foi trancada!")
    
    elif acao == "unlock":
        await channel.set_permissions(interaction.guild.default_role, connect=None)
        await interaction.response.send_message(f"🔓 {channel.mention} foi destrancada!")
    
    elif acao == "bitrate" and bitrate:
        if 8 <= bitrate <= 96:
            await channel.edit(bitrate=bitrate * 1000)
            await interaction.response.send_message(f"📶 Bitrate alterado para {bitrate} kbps!")
        else:
            await interaction.response.send_message("❌ Bitrate deve ser entre 8 e 96 kbps!", ephemeral=True)
    
    elif acao == "info":
        embed = discord.Embed(
            title=f"📊 Informações da Call",
            color=discord.Color.blue()
        )
        embed.add_field(name="Nome", value=channel.name, inline=False)
        embed.add_field(name="Membros", value=len(channel.members), inline=True)
        embed.add_field(name="Bitrate", value=f"{channel.bitrate // 1000} kbps", inline=True)
        embed.add_field(name="Limite", value=channel.user_limit or "Ilimitado", inline=True)
        await interaction.response.send_message(embed=embed)
    
    else:
        await interaction.response.send_message(
            "❌ Use: `/call lock|unlock|bitrate|info`",
            ephemeral=True
        )

@bot.tree.command(name="criar_sala", description="Cria uma sala temporária")
async def criar_sala(interaction: discord.Interaction, nome: str = "Sala de {user}"):
    if not interaction.user.voice:
        await interaction.response.send_message("❌ Você não está em uma call!", ephemeral=True)
        return
    
    guild = interaction.guild
    categoria = discord.utils.get(guild.categories, name="Salas Temporárias")
    if not categoria:
        categoria = await guild.create_category("Salas Temporárias")
    
    nome_final = nome.replace("{user}", interaction.user.display_name)
    channel = await guild.create_voice_channel(
        nome_final,
        category=categoria
    )
    
    await interaction.user.move_to(channel)
    await interaction.response.send_message(f"✅ Sala {channel.mention} criada e movido!")

# =========================================
# INICIAR BOT
# =========================================

print("🚀 Iniciando Bot Supremo...")
bot.run(TOKEN)
