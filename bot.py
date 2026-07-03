import discord
from discord.ext import commands, tasks
from discord import app_commands

import os
import random
import asyncio
import sqlite3
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, jsonify
from threading import Thread
from collections import defaultdict
import time

# =========================================
# CONFIGURAÇÕES
# =========================================

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise Exception("❌ TOKEN não encontrado nas variáveis de ambiente.")

RECORDE = 456
FUSO_BRASIL = ZoneInfo("America/Sao_Paulo")

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

def agora():
    return datetime.now(FUSO_BRASIL)

def hoje():
    return agora().date()

# =========================================
# BANCO DE DADOS SQLITE
# =========================================

class Database:
    def __init__(self):
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

db = Database()

# =========================================
# WEB SERVER
# =========================================

app = Flask(__name__)

@app.route("/")
def home():
    try:
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
    help_command=None
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

# =========================================
# VERIFICAÇÃO DE DIAS
# =========================================

async def verificar_passagem_dos_dias():
    try:
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
                        title="🌈 UM RETORNO INESPERADO 🌈",
                        color=discord.Color.green()
                    )
                    embed.description = f"😭 Depois de **{dias} dias**, **{nome}** apareceu novamente.\n\n🕯️ A contagem foi reiniciada!"
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

@tasks.loop(minutes=30)
async def verificar_sistema():
    try:
        await verificar_passagem_dos_dias()
    except Exception as e:
        print(f"❌ Erro no loop: {e}")

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
# COMANDOS DO BOT - TODOS COM "!"
# =========================================

# ---------- MEMORIAL ----------

@bot.command(name='memorial')
async def cmd_memorial(ctx, *, usuario: discord.Member = None):
    """!memorial @usuario - Configura o memorial no canal atual"""
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ Apenas administradores podem configurar memoriais!")
        return
    
    if not usuario:
        await ctx.send(
            "❌ Você precisa marcar um usuário!\n"
            "Exemplo: `!memorial @faxina_maldita`"
        )
        return
    
    if get_memorial(usuario.id):
        await ctx.send(
            f"⚠️ {usuario.mention} já tem um memorial configurado!\n"
            f"Use `!remover @{usuario.name}` para remover."
        )
        return
    
    criar_memorial(usuario.id, usuario.display_name, ctx.channel.id)
    
    await ctx.send(f"✅ Memorial de {usuario.mention} configurado neste canal!")
    
    await asyncio.sleep(1)
    memorial = get_memorial(usuario.id)
    if memorial:
        embed = criar_embed_memorial(memorial)
        await ctx.send(embed=embed)

@bot.command(name='remover')
async def cmd_remover(ctx, *, usuario: discord.Member = None):
    """!remover @usuario - Remove o memorial"""
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ Apenas administradores podem remover memoriais!")
        return
    
    if not usuario:
        await ctx.send("❌ Você precisa marcar um usuário!\nExemplo: `!remover @faxina_maldita`")
        return
    
    if not get_memorial(usuario.id):
        await ctx.send(f"❌ Não existe memorial para {usuario.mention}.")
        return
    
    db.executar("DELETE FROM memoriais WHERE user_id = ?", (str(usuario.id),))
    await ctx.send(f"🗑️ Memorial de {usuario.mention} removido com sucesso!")

@bot.command(name='dias')
async def cmd_dias(ctx, *, usuario: discord.Member = None):
    """!dias @usuario - Mostra o status do memorial"""
    if not usuario:
        usuario = ctx.author
    
    memorial = get_memorial(usuario.id)
    if not memorial:
        await ctx.send(f"❌ {usuario.mention} não tem memorial configurado.")
        return
    
    embed = criar_embed_memorial(memorial)
    await ctx.send(embed=embed)

@bot.command(name='lista')
async def cmd_lista(ctx):
    """!lista - Lista todos os memoriais ativos"""
    memoriais = db.cursor.execute("SELECT * FROM memoriais").fetchall()
    
    if not memoriais:
        await ctx.send("📭 Nenhum memorial ativo no momento.")
        return
    
    embed = discord.Embed(
        title="📋 Lista de Memoriais",
        color=discord.Color.blurple()
    )
    
    descricao = ""
    for mem in memoriais:
        user_id, nome, canal_id, dias, apareceu_hoje, ultima_data = mem
        descricao += f"• **{nome}** - {dias} dias\n"
    
    embed.description = descricao
    embed.set_footer(text=f"Total de {len(memoriais)} memoriais")
    
    await ctx.send(embed=embed)

@bot.command(name='resetar')
async def cmd_resetar(ctx, *, usuario: discord.Member = None):
    """!resetar @usuario - Reseta a contagem do memorial"""
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ Apenas administradores podem resetar memoriais!")
        return
    
    if not usuario:
        await ctx.send("❌ Você precisa marcar um usuário!\nExemplo: `!resetar @faxina_maldita`")
        return
    
    if not get_memorial(usuario.id):
        await ctx.send(f"❌ Não existe memorial para {usuario.mention}.")
        return
    
    db.executar(
        "UPDATE memoriais SET dias = 0, apareceu_hoje = 0, ultima_data = ? WHERE user_id = ?",
        (hoje().isoformat(), str(usuario.id))
    )
    
    await ctx.send(f"🔄 Memorial de {usuario.mention} foi resetado para 0 dias!")

# ---------- TICKETS ----------

@bot.command(name='ticket')
async def cmd_ticket(ctx):
    """!ticket - Abre um ticket de suporte"""
    user_id = str(ctx.author.id)
    
    abertos = db.cursor.execute(
        "SELECT COUNT(*) FROM tickets WHERE user_id = ? AND status = 'aberto'",
        (user_id,)
    ).fetchone()[0]
    
    if abertos >= MAX_TICKETS_POR_USUARIO:
        await ctx.send(f"❌ Você já tem {abertos} tickets abertos! Feche um antes de abrir outro.")
        return
    
    guild = ctx.guild
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        ctx.author: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }
    
    staff_role = discord.utils.get(guild.roles, name="Staff")
    if staff_role:
        overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
    
    channel = await guild.create_text_channel(
        f"ticket-{ctx.author.name[:10]}",
        overwrites=overwrites
    )
    
    db.executar(
        "INSERT INTO tickets (user_id, canal_id, criado_em) VALUES (?, ?, ?)",
        (user_id, str(channel.id), agora().isoformat())
    )
    
    embed = discord.Embed(
        title="🎫 Ticket Aberto",
        description=f"Olá {ctx.author.mention}! Como podemos ajudar você?",
        color=discord.Color.green()
    )
    embed.add_field(name="ℹ️", value="Use `!fechar` quando terminar.", inline=False)
    embed.set_footer(text=f"ID: {db.cursor.lastrowid}")
    
    await channel.send(embed=embed)
    await ctx.send(f"✅ Ticket criado em {channel.mention}!")

@bot.command(name='fechar')
async def cmd_fechar(ctx):
    """!fechar - Fecha o ticket atual"""
    canal_id = str(ctx.channel.id)
    ticket = db.cursor.execute(
        "SELECT * FROM tickets WHERE canal_id = ? AND status = 'aberto'",
        (canal_id,)
    ).fetchone()
    
    if not ticket:
        await ctx.send("❌ Este não é um ticket válido.")
        return
    
    db.executar(
        "UPDATE tickets SET status = 'fechado' WHERE canal_id = ?",
        (canal_id,)
    )
    
    await ctx.send("🔒 Ticket fechado em 5 segundos...")
    await asyncio.sleep(5)
    await ctx.channel.delete()

# ---------- MODERAÇÃO ----------

@bot.command(name='warn')
@commands.has_permissions(administrator=True)
async def cmd_warn(ctx, usuario: discord.Member, *, motivo: str = "Sem motivo"):
    """!warn @usuario motivo - Adverte um usuário"""
    db.executar(
        "INSERT INTO warns (user_id, motivo, data, moderador) VALUES (?, ?, ?, ?)",
        (str(usuario.id), motivo, agora().isoformat(), str(ctx.author.id))
    )
    
    embed = discord.Embed(
        title="⚠️ Advertência",
        description=f"{usuario.mention} foi advertido!",
        color=discord.Color.orange()
    )
    embed.add_field(name="Motivo", value=motivo, inline=False)
    embed.add_field(name="Moderador", value=ctx.author.mention, inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name='limpar')
@commands.has_permissions(administrator=True)
async def cmd_limpar(ctx, quantidade: int):
    """!limpar 10 - Limpa mensagens do canal"""
    if quantidade > 100:
        await ctx.send("❌ Máximo de 100 mensagens por vez.")
        return
    
    deletados = await ctx.channel.purge(limit=quantidade + 1)
    msg = await ctx.send(f"✅ {len(deletados) - 1} mensagens deletadas!")
    await asyncio.sleep(3)
    await msg.delete()

@bot.command(name='silenciar')
@commands.has_permissions(administrator=True)
async def cmd_silenciar(ctx, usuario: discord.Member, tempo_minutos: int, *, motivo: str = "Sem motivo"):
    """!silenciar @usuario 5 motivo - Silencia um usuário"""
    timeout = timedelta(minutes=tempo_minutos)
    await usuario.timeout(timeout, reason=motivo)
    
    embed = discord.Embed(
        title="🔇 Usuário Silenciado",
        description=f"{usuario.mention} foi silenciado por {tempo_minutos} minutos.",
        color=discord.Color.red()
    )
    embed.add_field(name="Motivo", value=motivo, inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='desilenciar')
@commands.has_permissions(administrator=True)
async def cmd_desilenciar(ctx, usuario: discord.Member):
    """!desilenciar @usuario - Remove o silêncio"""
    await usuario.timeout(None)
    await ctx.send(f"✅ {usuario.mention} foi desilenciado!")

# ---------- UTILIDADES ----------

@bot.command(name='ranking')
async def cmd_ranking(ctx):
    """!ranking - Mostra o ranking de XP"""
    resultados = db.cursor.execute(
        "SELECT user_id, xp FROM xp ORDER BY xp DESC LIMIT 10"
    ).fetchall()
    
    if not resultados:
        await ctx.send("📊 Ninguém tem XP ainda!")
        return
    
    embed = discord.Embed(
        title="🏆 Ranking de XP",
        color=discord.Color.gold()
    )
    
    descricao = ""
    for i, (user_id, xp) in enumerate(resultados, 1):
        try:
            user = await bot.fetch_user(int(user_id))
            nome = user.display_name
        except:
            nome = user_id[:8]
        
        medalhas = ["🥇", "🥈", "🥉"]
        emoji = medalhas[i-1] if i <= 3 else f"{i}°"
        descricao += f"{emoji} **{nome}** - {xp} XP\n"
    
    embed.description = descricao
    await ctx.send(embed=embed)

@bot.command(name='enquete')
async def cmd_enquete(ctx, pergunta: str, opcao1: str, opcao2: str, opcao3: str = None, opcao4: str = None):
    """!enquete "Pergunta" "Opção1" "Opção2" - Cria uma enquete"""
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
    embed.set_footer(text=f"Criado por {ctx.author.display_name}")
    
    msg = await ctx.send(embed=embed)
    
    for i in range(len(opcoes)):
        await msg.add_reaction(emojis[i])

@bot.command(name='sorteio')
async def cmd_sorteio(ctx, premio: str, duracao_minutos: int):
    """!sorteio "Prêmio" 5 - Realiza um sorteio"""
    msg = await ctx.send(
        f"🎉 **SORTEIO INICIADO!** 🎉\nPrêmio: **{premio}**\nReaja com 🎉 para participar!\nTempo: {duracao_minutos} minutos"
    )
    await msg.add_reaction("🎉")
    
    await asyncio.sleep(duracao_minutos * 60)
    
    msg_atualizada = await ctx.channel.fetch_message(msg.id)
    participantes = []
    
    for reaction in msg_atualizada.reactions:
        if str(reaction.emoji) == "🎉":
            async for user in reaction.users():
                if not user.bot:
                    participantes.append(user)
    
    if participantes:
        vencedor = random.choice(participantes)
        await ctx.send(f"🎊 **{vencedor.mention}** ganhou o sorteio de **{premio}**! Parabéns! 🎊")
    else:
        await ctx.send("❌ Ninguém participou do sorteio!")

@bot.command(name='userinfo')
async def cmd_userinfo(ctx, usuario: discord.Member = None):
    """!userinfo @usuario - Mostra informações do usuário"""
    if not usuario:
        usuario = ctx.author
    
    embed = discord.Embed(
        title=f"ℹ️ Informações de {usuario.display_name}",
        color=usuario.color
    )
    embed.set_thumbnail(url=usuario.display_avatar.url)
    embed.add_field(name="ID", value=usuario.id, inline=False)
    embed.add_field(name="Entrou em", value=usuario.joined_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name="Criado em", value=usuario.created_at.strftime("%d/%m/%Y"), inline=True)
    
    cargos = [role.mention for role in usuario.roles[1:5]]
    embed.add_field(name="Cargos", value=", ".join(cargos) or "Nenhum", inline=False)
    
    await ctx.send(embed=embed)

# ---------- COMANDOS DE VOZ ----------

@bot.command(name='call')
async def cmd_call(ctx, acao: str = None, bitrate: int = None):
    """!call lock/unlock/info - Gerencia a call"""
    if not ctx.author.voice:
        await ctx.send("❌ Você não está em uma call!")
        return
    
    channel = ctx.author.voice.channel
    
    if acao == "lock":
        await channel.set_permissions(ctx.guild.default_role, connect=False)
        await ctx.send(f"🔒 {channel.mention} foi trancada!")
    
    elif acao == "unlock":
        await channel.set_permissions(ctx.guild.default_role, connect=None)
        await ctx.send(f"🔓 {channel.mention} foi destrancada!")
    
    elif acao == "info":
        embed = discord.Embed(
            title=f"📊 Informações da Call",
            color=discord.Color.blue()
        )
        embed.add_field(name="Nome", value=channel.name, inline=False)
        embed.add_field(name="Membros", value=len(channel.members), inline=True)
        embed.add_field(name="Bitrate", value=f"{channel.bitrate // 1000} kbps", inline=True)
        embed.add_field(name="Limite", value=channel.user_limit or "Ilimitado", inline=True)
        await ctx.send(embed=embed)
    
    elif acao == "bitrate" and bitrate:
        if 8 <= bitrate <= 96:
            await channel.edit(bitrate=bitrate * 1000)
            await ctx.send(f"📶 Bitrate alterado para {bitrate} kbps!")
        else:
            await ctx.send("❌ Bitrate deve ser entre 8 e 96 kbps!")
    
    else:
        await ctx.send("❌ Use: `!call lock/unlock/info` ou `!call bitrate 64`")

@bot.command(name='criar_sala')
async def cmd_criar_sala(ctx, *, nome: str = None):
    """!criar_sala Nome - Cria uma sala temporária"""
    if not ctx.author.voice:
        await ctx.send("❌ Você não está em uma call!")
        return
    
    if not nome:
        nome = f"Sala de {ctx.author.display_name}"
    
    guild = ctx.guild
    categoria = discord.utils.get(guild.categories, name="Salas Temporárias")
    if not categoria:
        categoria = await guild.create_category("Salas Temporárias")
    
    channel = await guild.create_voice_channel(
        nome,
        category=categoria
    )
    
    await ctx.author.move_to(channel)
    await ctx.send(f"✅ Sala {channel.mention} criada e você foi movido!")

# ---------- AJUDA ----------

@bot.command(name='ajuda')
async def cmd_ajuda(ctx):
    """!ajuda - Mostra todos os comandos"""
    embed = discord.Embed(
        title="📚 Comandos do Bot",
        color=discord.Color.blue(),
        description="Todos os comandos usam `!` no início"
    )
    
    embed.add_field(
        name="🔧 Memorial",
        value=(
            "`!memorial @usuario` - Configura memorial\n"
            "`!remover @usuario` - Remove memorial\n"
            "`!dias @usuario` - Status do memorial\n"
            "`!lista` - Lista memoriais\n"
            "`!resetar @usuario` - Reseta contagem"
        ),
        inline=False
    )
    
    embed.add_field(
        name="🎫 Tickets",
        value=(
            "`!ticket` - Abre ticket\n"
            "`!fechar` - Fecha ticket"
        ),
        inline=False
    )
    
    embed.add_field(
        name="⚙️ Moderação (Admin)",
        value=(
            "`!warn @usuario motivo` - Adverte\n"
            "`!silenciar @usuario 5 motivo` - Silencia\n"
            "`!desilenciar @usuario` - Desilencia\n"
            "`!limpar 10` - Limpa mensagens"
        ),
        inline=False
    )
    
    embed.add_field(
        name="📊 Utilidades",
        value=(
            "`!ranking` - Ranking de XP\n"
            "`!enquete \"Pergunta\" \"Op1\" \"Op2\"` - Enquete\n"
            "`!sorteio \"Prêmio\" 5` - Sorteio\n"
            "`!userinfo @usuario` - Info do usuário"
        ),
        inline=False
    )
    
    embed.add_field(
        name="🎤 Voz",
        value=(
            "`!call lock/unlock/info` - Gerencia call\n"
            "`!criar_sala Nome` - Cria sala temporária"
        ),
        inline=False
    )
    
    await ctx.send(embed=embed)

# =========================================
# EVENTOS
# =========================================

@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}")
    await bot.wait_until_ready()
    
    await asyncio.sleep(5)
    await verificar_passagem_dos_dias()
    
    if not verificar_sistema.is_running():
        verificar_sistema.start()
    
    print("🚀 Bot está pronto para usar! Use !ajuda para ver os comandos.")

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    if get_memorial(message.author.id):
        marcou_presenca(message.author.id)
    
    # Adiciona XP
    adicionar_xp(message.author.id, XP_POR_MENSAGEM)
    
    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    if get_memorial(member.id):
        marcou_presenca(member.id)

# =========================================
# TRATAMENTO DE ERROS
# =========================================

@cmd_memorial.error
async def cmd_memorial_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⛔ Apenas administradores podem configurar memoriais!")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Usuário não encontrado! Certifique-se de marcar alguém.")
    else:
        await ctx.send(f"❌ Erro: {error}")

@cmd_remover.error
async def cmd_remover_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⛔ Apenas administradores podem remover memoriais!")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Usuário não encontrado!")

@cmd_warn.error
async def cmd_warn_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⛔ Apenas administradores podem usar este comando!")

@cmd_silenciar.error
async def cmd_silenciar_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⛔ Apenas administradores podem silenciar usuários!")

# =========================================
# INICIAR BOT
# =========================================

if __name__ == "__main__":
    print("🚀 Iniciando Bot Supremo...")
    try:
        bot.run(TOKEN, reconnect=True)
    except Exception as e:
        print(f"❌ Erro: {e}")
