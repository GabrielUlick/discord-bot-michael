import discord
from discord.ext import commands, tasks

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
import re

# =========================================
# CONFIGURAÇÕES
# =========================================

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise Exception("❌ TOKEN não encontrado nas variáveis de ambiente.")

FUSO_BRASIL = ZoneInfo("America/Sao_Paulo")

# Configurações
MAX_TICKETS_POR_USUARIO = 3
TEMPO_VERIFICACAO = 120
LIMITE_MENSAGENS_POR_MINUTO = 8
XP_POR_MENSAGEM = 5
XP_POR_MINUTO_CALL = 3

# Configurações de VOZ
DIAS_PARA_ENTRAR_CALL = 10  # Dias de ausência para ativar

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
        # Tabela de memoriais com coluna 'recorde'
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS memoriais (
                user_id TEXT PRIMARY KEY,
                nome TEXT,
                canal_id TEXT,
                dias INTEGER DEFAULT 0,
                apareceu_hoje INTEGER DEFAULT 0,
                ultima_data TEXT,
                recorde TEXT DEFAULT '456'
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
        
        # Tabela de XP
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS xp (
                user_id TEXT PRIMARY KEY,
                xp INTEGER DEFAULT 0,
                nivel INTEGER DEFAULT 0,
                ultima_mensagem TEXT,
                tempo_call INTEGER DEFAULT 0
            )
        ''')
        
        # Tabela de configurações
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS configuracoes (
                guild_id TEXT PRIMARY KEY,
                cargo_verificacao TEXT,
                canal_logs TEXT,
                canal_memoriais TEXT,
                cargo_nivel_1 TEXT,
                cargo_nivel_5 TEXT,
                cargo_nivel_10 TEXT,
                canal_voz_id TEXT
            )
        ''')
        
        # Tabela de warns
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS warns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                motivo TEXT,
                data TEXT,
                moderador TEXT
            )
        ''')
        
        # Migração para adicionar coluna 'recorde' se não existir
        try:
            self.cursor.execute("ALTER TABLE memoriais ADD COLUMN recorde TEXT DEFAULT '456'")
        except sqlite3.OperationalError:
            pass
        
        # Migração para adicionar canal_voz_id na configuração
        try:
            self.cursor.execute("ALTER TABLE configuracoes ADD COLUMN canal_voz_id TEXT")
        except sqlite3.OperationalError:
            pass
        
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

def pegar_emojis_do_canal(canal_id):
    """Pega TODOS os emojis do título do canal do memorial"""
    try:
        canal = bot.get_channel(int(canal_id))
        if not canal:
            return []
        
        # Pega o nome do canal
        nome_canal = canal.name
        
        # Procura por emojis no nome
        import re
        
        # Padrão para emojis Unicode (inclui 🫃 e outros)
        emoji_pattern = re.compile(
            "[\U0001F600-\U0001F64F"  # emoticons
            "\U0001F300-\U0001F5FF"  # symbols & pictographs
            "\U0001F680-\U0001F6FF"  # transport & map symbols
            "\U0001F700-\U0001F77F"  # alchemical symbols
            "\U0001F780-\U0001F7FF"  # Geometric Shapes Extended
            "\U0001F800-\U0001F8FF"  # Supplemental Arrows-C
            "\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
            "\U0001FA00-\U0001FA6F"  # Chess Symbols
            "\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
            "\U00002702-\U000027B0"  # Dingbats
            "\U000024C2-\U0001F251"
            "\U0001F7E0-\U0001F7EB"  # More symbols
            "\U0001F90C-\U0001F93A"  # More emojis
            "\U0001F9B4-\U0001F9BF"  # Body parts
            "\U0001FAC0-\U0001FAC5"  # More emojis
            "]+",
            flags=re.UNICODE
        )
        
        # Encontra todos os emojis no nome
        emojis_encontrados = emoji_pattern.findall(nome_canal)
        
        # Se não encontrou emojis Unicode, tenta encontrar :emoji: pattern
        if not emojis_encontrados:
            emoji_named = re.findall(r':([a-zA-Z0-9_]+):', nome_canal)
            if emoji_named:
                # Tenta converter para emojis usando o Discord
                for nome_emoji in emoji_named:
                    try:
                        # Tenta pegar o emoji do Discord
                        emoji_obj = discord.utils.get(bot.emojis, name=nome_emoji)
                        if emoji_obj:
                            emojis_encontrados.append(str(emoji_obj))
                        else:
                            # Se não encontrar, mantém o texto :nome:
                            emojis_encontrados.append(f":{nome_emoji}:")
                    except:
                        emojis_encontrados.append(f":{nome_emoji}:")
        
        # Remove duplicatas mantendo a ordem
        emojis_unicos = []
        for emoji in emojis_encontrados:
            if emoji not in emojis_unicos:
                emojis_unicos.append(emoji)
        
        return emojis_unicos
        
    except Exception as e:
        print(f"⚠️ Erro ao pegar emojis do canal: {e}")
        return []

def get_memorial(user_id):
    """Retorna o memorial de um usuário ou None se não existir"""
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
            "ultima_data": result[5],
            "recorde": result[6] if len(result) > 6 else "456"
        }
    return None

def criar_memorial(user_id, nome, canal_id, recorde="456"):
    """Cria um novo memorial com recorde personalizado"""
    db.executar(
        "INSERT INTO memoriais (user_id, nome, canal_id, dias, apareceu_hoje, ultima_data, recorde) VALUES (?, ?, ?, 0, 0, ?, ?)",
        (str(user_id), nome, str(canal_id), hoje().isoformat(), str(recorde))
    )

def marcou_presenca(user_id):
    """Marca que o usuário apareceu hoje"""
    db.executar(
        "UPDATE memoriais SET apareceu_hoje = 1 WHERE user_id = ?",
        (str(user_id),)
    )

def atualizar_recorde(user_id, recorde):
    """Atualiza o recorde de um memorial"""
    db.executar(
        "UPDATE memoriais SET recorde = ? WHERE user_id = ?",
        (str(recorde), str(user_id))
    )

def get_canal_voz(guild_id):
    """Pega o canal de voz configurado para o servidor"""
    result = db.cursor.execute(
        "SELECT canal_voz_id FROM configuracoes WHERE guild_id = ?",
        (str(guild_id),)
    ).fetchone()
    
    if result and result[0]:
        return int(result[0])
    return None

def set_canal_voz(guild_id, canal_id):
    """Configura o canal de voz para o servidor"""
    db.executar(
        "INSERT OR REPLACE INTO configuracoes (guild_id, canal_voz_id) VALUES (?, ?)",
        (str(guild_id), str(canal_id))
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

# SEUS GIFS ORIGINAIS
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

# Frases para o TTS (apenas para memoriais)
FRASES_TTS_MEMORIAL = [
    "Atenção! {nome} está ausente há {dias} dias.",
    "Oi pessoal! {nome} não aparece há {dias} dias. Alguém tem notícias?",
    "Mais um dia sem {nome}. Já são {dias} dias de saudade.",
    "Lembrando que {nome} está sumido há {dias} dias. Volta pra gente!",
    "{nome} já está fora há {dias} dias. A saudade está batendo.",
]

def criar_embed_memorial(memorial):
    """Cria o embed do memorial com emojis personalizados do canal"""
    dias = memorial["dias"]
    recorde = memorial.get("recorde", "456")
    
    # Pega os emojis do canal do memorial
    emojis_titulo = pegar_emojis_do_canal(memorial.get("canal_id"))
    
    # Se tiver emojis, usa o PRIMEIRO para os dois lados (padrão 🫃-dias-sem-leo-🫃)
    if emojis_titulo:
        emoji = emojis_titulo[0]  # Pega o primeiro emoji
    else:
        emoji = "🌈"  # Fallback padrão
    
    embed = discord.Embed(
        title=f"{emoji} ═══ MEMORIAL DA SAUDADE ═══ {emoji}",
        color=discord.Color.blue()
    )
    embed.description = (
        f"🕯️ **Hoje são {dias} dias sem {memorial['nome']}**\n\n"
        f"{random.choice(frases).format(nome=memorial['nome'], dias=dias)}"
    )
    
    # Tenta converter o recorde para número
    try:
        recorde_num = int(recorde)
        if dias < recorde_num:
            faltam = recorde_num - dias
            embed.add_field(
                name=f"{emoji} Recorde Histórico",
                value=f"{recorde_num} dias\n⏳ Faltam {faltam} dias para alcançar.",
                inline=False
            )
        elif dias == recorde_num:
            embed.color = discord.Color.gold()
            embed.add_field(
                name=f"👑 RECORDE ALCANÇADO",
                value=f"Hoje igualamos o maior tempo de ausência: {recorde_num} dias!",
                inline=False
            )
        else:
            embed.color = discord.Color.dark_purple()
            embed.add_field(
                name=f"🌌 NOVA ERA",
                value=f"Um novo recorde está sendo escrito! {dias} dias e contando...",
                inline=False
            )
    except ValueError:
        # Se não for número, mostra como texto personalizado
        embed.add_field(
            name=f"{emoji} Recorde Personalizado",
            value=recorde,
            inline=False
        )
    
    # Sorteia um GIF aleatório da sua lista
    embed.set_image(url=random.choice(gifs))
    embed.set_footer(
        text=f"{emoji} Atualizado em " + agora().strftime("%d/%m/%Y às %H:%M")
    )
    return embed

# =========================================
# SISTEMA DE VOZ - TTS
# =========================================

async def falar_tts(texto, canal_voz):
    """Fala um texto em um canal de voz usando TTS"""
    try:
        # Verifica se o bot já está conectado em algum canal de voz neste servidor
        for vc in bot.voice_clients:
            if vc.guild == canal_voz.guild:
                await vc.disconnect()
                await asyncio.sleep(1)
        
        # Conecta ao canal
        vc = await canal_voz.connect(timeout=10.0)
        
        # Prepara o texto para URL (remove caracteres especiais)
        texto_limpo = re.sub(r'[^a-zA-Z0-9áéíóúâêôãõç ]', '', texto)
        texto_url = texto_limpo.replace(' ', '%20')
        
        if not texto_url or len(texto_url) < 1:
            texto_url = "teste"
        
        # Tenta usar o Google TTS
        url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={texto_url}&tl=pt&client=tw-ob"
        
        # Cria o áudio com FFmpeg
        audio_source = discord.FFmpegPCMAudio(
            url,
            before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
        )
        
        # Toca o áudio
        vc.play(audio_source)
        
        # Espera terminar
        timeout = 30
        while vc.is_playing() and timeout > 0:
            await asyncio.sleep(0.5)
            timeout -= 0.5
        
        await asyncio.sleep(1)
        await vc.disconnect()
        return True
        
    except Exception as e:
        print(f"❌ Erro no TTS: {e}")
        # Tenta desconectar se houver erro
        try:
            for vc in bot.voice_clients:
                if vc.guild == canal_voz.guild:
                    await vc.disconnect()
        except:
            pass
        return False

async def entrar_call_tts_memorial(memorial, guild):
    """Entra na call para falar sobre um memorial específico"""
    try:
        # Pega o canal de voz configurado
        canal_voz_id = get_canal_voz(guild.id)
        canal_voz = None
        
        if canal_voz_id:
            canal_voz = bot.get_channel(canal_voz_id)
        
        # Se não tiver configurado, procura um canal com membros
        if not canal_voz:
            for channel in guild.voice_channels:
                if len(channel.members) > 0:
                    canal_voz = channel
                    break
        
        # Se ainda não achou, pega o primeiro canal de voz
        if not canal_voz and guild.voice_channels:
            canal_voz = guild.voice_channels[0]
        
        if not canal_voz:
            print(f"❌ Nenhum canal de voz encontrado para {guild.name}")
            return False
        
        # Escolhe uma frase aleatória
        frase = random.choice(FRASES_TTS_MEMORIAL).format(
            nome=memorial["nome"],
            dias=memorial["dias"]
        )
        
        await falar_tts(frase, canal_voz)
        return True
        
    except Exception as e:
        print(f"❌ Erro ao entrar na call: {e}")
        return False

async def anunciar_todos_memoriais(guild, canal_voz):
    """Anuncia todos os memoriais de uma vez na call onde o usuário está"""
    try:
        memoriais = db.cursor.execute("SELECT * FROM memoriais").fetchall()
        
        if not memoriais:
            return "📭 Nenhum memorial ativo no momento."
        
        # Filtra apenas os que têm dias > 0
        ativos = [m for m in memoriais if m[3] > 0]
        
        if not ativos:
            return "📭 Nenhum memorial com dias contados no momento."
        
        # Conecta ao canal
        vc = await canal_voz.connect()
        
        # Anuncia um por um
        for mem in ativos:
            user_id, nome, canal_id, dias, apareceu_hoje, ultima_data, recorde = mem
            
            if dias > 0:
                frase = f"{nome} está ausente há {dias} dias."
                
                # Tenta falar com TTS
                try:
                    texto_url = re.sub(r'[^a-zA-Z0-9áéíóúâêôãõç ]', '', frase)
                    texto_url = texto_url.replace(' ', '%20')
                    
                    audio_source = discord.FFmpegPCMAudio(
                        f"https://translate.google.com/translate_tts?ie=UTF-8&q={texto_url}&tl=pt&client=tw-ob",
                        before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
                    )
                    
                    vc.play(audio_source)
                    
                    while vc.is_playing():
                        await asyncio.sleep(0.5)
                    
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    print(f"⚠️ Erro no TTS para {nome}: {e}")
                    continue
        
        # Frase final
        if ativos:
            try:
                frase_final = f"Estes são todos os ausentes do servidor. Total de {len(ativos)} pessoas."
                texto_url = re.sub(r'[^a-zA-Z0-9áéíóúâêôãõç ]', '', frase_final)
                texto_url = texto_url.replace(' ', '%20')
                
                audio_source = discord.FFmpegPCMAudio(
                    f"https://translate.google.com/translate_tts?ie=UTF-8&q={texto_url}&tl=pt&client=tw-ob",
                    before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
                )
                
                vc.play(audio_source)
                
                while vc.is_playing():
                    await asyncio.sleep(0.5)
                
                await asyncio.sleep(1)
                
            except Exception as e:
                print(f"⚠️ Erro no TTS final: {e}")
        
        await vc.disconnect()
        
        return f"✅ Anunciados {len(ativos)} memoriais na call {canal_voz.mention}!"
        
    except Exception as e:
        print(f"❌ Erro no anúncio: {e}")
        return f"❌ Erro no anúncio: {e}"

# =========================================
# VERIFICAÇÃO DE DIAS
# =========================================

async def verificar_passagem_dos_dias():
    """Verifica os dias passados para cada memorial"""
    try:
        hoje_atual = hoje()
        memoriais = db.cursor.execute("SELECT * FROM memoriais").fetchall()
        
        if not memoriais:
            return
        
        for memorial in memoriais:
            try:
                user_id, nome, canal_id, dias, apareceu_hoje, ultima_data, recorde = memorial
                
                ultima = date.fromisoformat(ultima_data)
                dias_passados = (hoje_atual - ultima).days
                
                if dias_passados <= 0:
                    continue
                
                canal = bot.get_channel(int(canal_id))
                if not canal:
                    continue
                
                # Pega o emoji do canal
                emojis_titulo = pegar_emojis_do_canal(canal_id)
                emoji = emojis_titulo[0] if emojis_titulo else "🌈"
                
                if apareceu_hoje:
                    embed = discord.Embed(
                        title=f"{emoji} UM RETORNO INESPERADO {emoji}",
                        color=discord.Color.green()
                    )
                    embed.description = f"😭 Depois de **{dias} dias**, **{nome}** apareceu novamente.\n\n🕯️ A contagem foi reiniciada!"
                    await canal.send(embed=embed)
                    await asyncio.sleep(1)
                    dias = 0
                else:
                    dias += 1
                    memorial_dict = {
                        "nome": nome,
                        "dias": dias,
                        "recorde": recorde,
                        "canal_id": canal_id
                    }
                    embed = criar_embed_memorial(memorial_dict)
                    await canal.send(embed=embed)
                    await asyncio.sleep(1.5)
                    
                    # VERIFICA SE DEVE ENTRAR NA CALL
                    if dias == DIAS_PARA_ENTRAR_CALL:
                        guild = canal.guild
                        await entrar_call_tts_memorial(memorial_dict, guild)
                
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
    """Adiciona XP a um usuário"""
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
# COMANDOS DO BOT
# =========================================

# ---------- MEMORIAL ----------

@bot.command(name='memorial')
async def cmd_memorial(ctx, usuario: discord.Member, *, recorde: str = "456"):
    """!memorial @usuario 500 - Configura memorial com recorde específico"""
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ Apenas administradores podem configurar memoriais!")
        return
    
    if get_memorial(usuario.id):
        await ctx.send(
            f"⚠️ {usuario.mention} já tem um memorial configurado!\n"
            f"Use `!remover @{usuario.name}` para remover ou `!setrecorde @{usuario.name} 500` para alterar."
        )
        return
    
    criar_memorial(usuario.id, usuario.display_name, ctx.channel.id, recorde)
    
    try:
        num_recorde = int(recorde)
        await ctx.send(f"✅ Memorial de {usuario.mention} configurado com recorde de **{num_recorde} dias**!")
    except ValueError:
        await ctx.send(f"✅ Memorial de {usuario.mention} configurado com recorde: **{recorde}**")
    
    await asyncio.sleep(1)
    memorial = get_memorial(usuario.id)
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
        user_id, nome, canal_id, dias, apareceu_hoje, ultima_data, recorde = mem
        status = "✅ Online" if apareceu_hoje else "❌ Ausente"
        descricao += f"• **{nome}** - {dias} dias ({status}) | Recorde: {recorde}\n"
    
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

@bot.command(name='recorde')
async def cmd_recorde(ctx, *, usuario: discord.Member = None):
    """!recorde @usuario - Mostra o recorde atual do memorial"""
    if not usuario:
        usuario = ctx.author
    
    memorial = get_memorial(usuario.id)
    if not memorial:
        await ctx.send(f"❌ {usuario.mention} não tem memorial configurado.")
        return
    
    recorde = memorial.get("recorde", "456")
    await ctx.send(f"🏆 O recorde de {usuario.mention} é: **{recorde}**")

@bot.command(name='setrecorde')
@commands.has_permissions(administrator=True)
async def cmd_setrecorde(ctx, usuario: discord.Member, *, recorde: str):
    """!setrecorde @usuario 500 - Define o recorde do memorial"""
    
    if not get_memorial(usuario.id):
        await ctx.send(f"❌ {usuario.mention} não tem memorial configurado.\nUse `!memorial @usuario` primeiro.")
        return
    
    atualizar_recorde(usuario.id, recorde)
    
    try:
        num_recorde = int(recorde)
        await ctx.send(f"✅ Recorde de {usuario.mention} definido para **{num_recorde} dias**!")
    except ValueError:
        await ctx.send(f"✅ Recorde de {usuario.mention} definido como: **{recorde}**")
    
    await asyncio.sleep(1)
    memorial = get_memorial(usuario.id)
    embed = criar_embed_memorial(memorial)
    await ctx.send(embed=embed)

# ---------- COMANDOS DE VOZ ----------

@bot.command(name='setcall')
@commands.has_permissions(administrator=True)
async def cmd_setcall(ctx, canal: discord.VoiceChannel = None):
    """!setcall #canal - Define o canal de voz para o bot entrar (para memorial automático)"""
    if canal:
        set_canal_voz(ctx.guild.id, canal.id)
        await ctx.send(f"✅ Canal de voz configurado para {canal.mention}")
    else:
        set_canal_voz(ctx.guild.id, None)
        await ctx.send("✅ Configuração de canal removida. O bot usará o primeiro canal disponível.")

@bot.command(name='anunciacao')
@commands.has_permissions(administrator=True)
async def cmd_anunciacao(ctx):
    """!anunciacao - Entra na call onde você está e anuncia todos os ausentes do memorial"""
    # Verifica se o usuário está em uma call
    if not ctx.author.voice:
        await ctx.send("❌ Você precisa estar em uma call para usar este comando!")
        return
    
    canal_voz = ctx.author.voice.channel
    
    # Verifica se o bot tem permissão
    if not canal_voz.permissions_for(ctx.guild.me).connect:
        await ctx.send("❌ Não tenho permissão para CONECTAR neste canal de voz!")
        return
    
    if not canal_voz.permissions_for(ctx.guild.me).speak:
        await ctx.send("❌ Não tenho permissão para FALAR neste canal!")
        return
    
    await ctx.send(f"🔊 Entrando em {canal_voz.mention} para fazer o anúncio...")
    
    # Anuncia todos os memoriais
    resultado = await anunciar_todos_memoriais(ctx.guild, canal_voz)
    await ctx.send(resultado)

@bot.command(name='testcall')
@commands.has_permissions(administrator=True)
async def cmd_testcall(ctx, *, texto: str = "Olá! Este é um teste do sistema de voz."):
    """!testcall "Texto" - Testa o TTS no canal de voz"""
    if not ctx.author.voice:
        await ctx.send("❌ Você precisa estar em uma call para testar!")
        return
    
    canal_voz = ctx.author.voice.channel
    
    # Verifica permissões
    if not canal_voz.permissions_for(ctx.guild.me).connect:
        await ctx.send("❌ Não tenho permissão para CONECTAR neste canal!")
        return
    
    if not canal_voz.permissions_for(ctx.guild.me).speak:
        await ctx.send("❌ Não tenho permissão para FALAR neste canal!")
        return
    
    await ctx.send(f"🔊 Testando TTS: \"{texto}\"")
    
    try:
        sucesso = await falar_tts(texto, canal_voz)
        if sucesso:
            await ctx.send("✅ Teste concluído com sucesso!")
        else:
            await ctx.send("❌ Falha no teste! Verifique os logs do servidor.")
    except Exception as e:
        await ctx.send(f"❌ Erro: {str(e)[:100]}")

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

@bot.command(name='testemojis')
async def cmd_testemojis(ctx):
    """!testemojis - Testa os emojis do canal atual"""
    emojis = pegar_emojis_do_canal(ctx.channel.id)
    
    if emojis:
        emoji = emojis[0]  # Pega o primeiro emoji
        
        embed = discord.Embed(
            title=f"{emoji} TESTE DE EMOJIS {emoji}",
            color=discord.Color.blue()
        )
        embed.description = f"Emojis encontrados no nome do canal: **{', '.join(emojis)}**"
        embed.add_field(
            name="Emoji usado",
            value=emoji,
            inline=True
        )
        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ Nenhum emoji encontrado no nome deste canal!")

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
            "`!memorial @usuario 500` - Configura memorial com recorde\n"
            "`!remover @usuario` - Remove memorial\n"
            "`!dias @usuario` - Status do memorial\n"
            "`!lista` - Lista memoriais\n"
            "`!resetar @usuario` - Reseta contagem\n"
            "`!recorde @usuario` - Mostra recorde\n"
            "`!setrecorde @usuario 500` - Altera recorde"
        ),
        inline=False
    )
    
    embed.add_field(
        name="🎤 Voz",
        value=(
            "`!setcall #canal` - Configura canal de voz (para memorial automático)\n"
            "`!anunciacao` - Entra na sua call e anuncia todos ausentes\n"
            "`!testcall \"Texto\"` - Testa o TTS na sua call"
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
            "`!userinfo @usuario` - Info do usuário\n"
            "`!testemojis` - Testa emojis do canal"
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
