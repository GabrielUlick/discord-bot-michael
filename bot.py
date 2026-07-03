import discord
from discord.ext import commands, tasks

import json
import os
import random

from flask import Flask
from threading import Thread

from datetime import datetime, date
from zoneinfo import ZoneInfo


# =========================================
# CONFIGURAÇÕES
# =========================================

TOKEN = os.getenv("TOKEN")

if not TOKEN:
    raise Exception(
        "❌ TOKEN não encontrado nas variáveis de ambiente."
    )


RECORDE = 456

FUSO_BRASIL = ZoneInfo("America/Sao_Paulo")


def agora():
    """
    Retorna data/hora do Brasil
    """
    return datetime.now(FUSO_BRASIL)


def hoje():
    """
    Retorna a data atual do Brasil
    """
    return agora().date()


# =========================================
# FRASES DO MEMORIAL
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


# =========================================
# GIFS DIRETOS PARA DISCORD
# =========================================

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
# WEB SERVER PARA RENDER
# =========================================

app = Flask(__name__)


@app.route("/")
def home():
    return {
        "status": "online",
        "bot": str(bot.user) if bot.user else "conectando",
        "hora": agora().strftime("%d/%m/%Y %H:%M:%S"),
        "memoriais": len(dados.get("memoriais", {}))
    }


def iniciar_web():

    porta = int(
        os.getenv("PORT", 10000)
    )

    app.run(
        host="0.0.0.0",
        port=porta,
        threaded=True,
        use_reloader=False
    )


Thread(
    target=iniciar_web,
    daemon=True
).start()


# =========================================
# BANCO DE DADOS JSON
# =========================================


DADOS_PADRAO = {
    "memoriais": {}  # { "user_id": { "nome": "", "canal_id": 0, "dias": 0, "apareceu_hoje": False, "ultima_data": "" } }
}


def carregar():

    if not os.path.exists("dados.json"):
        salvar(DADOS_PADRAO)
        return DADOS_PADRAO.copy()

    try:
        with open("dados.json", "r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)

        # Garante que a estrutura existe
        if "memoriais" not in dados:
            dados["memoriais"] = {}

        return dados

    except Exception as erro:
        print("⚠️ JSON corrompido:", erro)
        salvar(DADOS_PADRAO)
        return DADOS_PADRAO.copy()


def salvar(conteudo=None):
    if conteudo is None:
        conteudo = dados

    with open("dados.json", "w", encoding="utf-8") as arquivo:
        json.dump(conteudo, arquivo, indent=4, ensure_ascii=False)


dados = carregar()


# =========================================
# CONFIGURAÇÃO DO BOT
# =========================================

intents = discord.Intents.default()
intents.message_content = True
intents.presences = False
intents.voice_states = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)


# =========================================
# FUNÇÕES DE PRESENÇA
# =========================================

def get_memorial(user_id):
    """Retorna o memorial de um usuário ou None se não existir"""
    return dados["memoriais"].get(str(user_id))


def criar_memorial(user_id, nome, canal_id):
    """Cria um novo memorial para um usuário"""
    dados["memoriais"][str(user_id)] = {
        "nome": nome,
        "canal_id": canal_id,
        "dias": 0,
        "apareceu_hoje": False,
        "ultima_data": hoje().isoformat()
    }
    salvar()


def marcou_presenca(user_id):
    """
    Marca que o usuário apareceu hoje.
    """
    memorial = get_memorial(user_id)
    if memorial and not memorial["apareceu_hoje"]:
        memorial["apareceu_hoje"] = True
        salvar()


@bot.event
async def on_message(msg):
    # Verifica se o autor tem memorial
    if str(msg.author.id) in dados["memoriais"]:
        marcou_presenca(msg.author.id)

    await bot.process_commands(msg)


@bot.event
async def on_voice_state_update(member, before, after):
    # Verifica se o membro tem memorial
    if str(member.id) in dados["memoriais"]:
        marcou_presenca(member.id)


# =========================================
# EMBEDS DO MEMORIAL
# =========================================

def criar_embed_memorial(memorial, user_id):
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
            value=(
                f"{RECORDE} dias\n"
                f"⏳ Faltam {faltam} dias para alcançar."
            ),
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

    embed.set_image(
        url=random.choice(gifs)
    )

    embed.set_footer(
        text=(
            "Atualizado em "
            + agora().strftime("%d/%m/%Y às %H:%M")
        )
    )

    return embed


def criar_embed_retorno(memorial):
    embed = discord.Embed(
        title="🌈 UM RETORNO INESPERADO 🌈",
        color=discord.Color.green()
    )

    embed.description = (
        f"😭 Depois de **{memorial['dias']} dias**, "
        f"**{memorial['nome']}** apareceu novamente.\n\n"
        "🕯️ O memorial volta ao dia 0,\n"
        "mas as lembranças continuam vivas."
    )

    embed.set_footer(
        text="A contagem foi reiniciada."
    )

    return embed


async def enviar_memorial(memorial, canal):
    await canal.send(
        embed=criar_embed_memorial(memorial, None)
    )


async def enviar_retorno(memorial, canal):
    await canal.send(
        embed=criar_embed_retorno(memorial)
    )


# =========================================
# SISTEMA DE CONTAGEM INTELIGENTE
# =========================================

async def verificar_passagem_dos_dias():
    """
    Verifica quantos dias se passaram desde
    a última atualização registrada para cada memorial.
    """

    hoje_atual = hoje()
    memoriais_para_remover = []

    for user_id_str, memorial in dados["memoriais"].items():
        ultima = date.fromisoformat(memorial["ultima_data"])
        dias_passados = (hoje_atual - ultima).days

        # Nada mudou para este memorial
        if dias_passados <= 0:
            continue

        canal = bot.get_channel(memorial["canal_id"])
        if canal is None:
            print(f"⚠️ Canal do memorial de {memorial['nome']} não encontrado.")
            memorial["ultima_data"] = hoje_atual.isoformat()
            salvar()
            continue

        # Para cada dia que passou, atualiza a contagem
        for _ in range(dias_passados):
            if memorial["apareceu_hoje"]:
                await enviar_retorno(memorial, canal)
                memorial["dias"] = 0
            else:
                memorial["dias"] += 1
                await enviar_memorial(memorial, canal)

            # Novo dia começa sem presença
            memorial["apareceu_hoje"] = False

        memorial["ultima_data"] = hoje_atual.isoformat()
        salvar()


# =========================================
# LOOP AUTOMÁTICO
# =========================================

@tasks.loop(minutes=5)
async def verificar_sistema():
    await verificar_passagem_dos_dias()


@bot.event
async def on_ready():
    print(f"🌈 Memorial iniciado como {bot.user}")
    
    # Confere imediatamente ao iniciar
    await verificar_passagem_dos_dias()

    if not verificar_sistema.is_running():
        verificar_sistema.start()


# =========================================
# COMANDOS DO BOT
# =========================================

@bot.command()
@commands.has_permissions(administrator=True)
async def configurar(ctx):
    """
    Define qual usuário será monitorado.
    Apenas administradores podem usar.
    """

    if not ctx.message.mentions:
        await ctx.send(
            "❌ Você precisa marcar um usuário.\n\n"
            "Exemplo:\n"
            "`!configurar @usuario`"
        )
        return

    membro = ctx.message.mentions[0]
    user_id_str = str(membro.id)

    # Verifica se já existe memorial para este usuário
    if user_id_str in dados["memoriais"]:
        await ctx.send(
            f"⚠️ Já existe um memorial para {membro.mention}.\n"
            "Use `!remover @usuario` para remover ou atualize manualmente."
        )
        return

    # Cria novo memorial
    criar_memorial(
        user_id=membro.id,
        nome=membro.display_name,
        canal_id=ctx.channel.id
    )

    await ctx.send(
        f"🌈 Memorial de {membro.mention} "
        "foi configurado com sucesso."
    )

    # Envia o estado atual
    memorial = get_memorial(membro.id)
    await enviar_memorial(memorial, ctx.channel)


@bot.command()
@commands.has_permissions(administrator=True)
async def remover(ctx):
    """
    Remove o memorial de um usuário.
    Apenas administradores podem usar.
    """

    if not ctx.message.mentions:
        await ctx.send(
            "❌ Você precisa marcar um usuário.\n\n"
            "Exemplo:\n"
            "`!remover @usuario`"
        )
        return

    membro = ctx.message.mentions[0]
    user_id_str = str(membro.id)

    if user_id_str not in dados["memoriais"]:
        await ctx.send(
            f"❌ Não existe memorial para {membro.mention}."
        )
        return

    del dados["memoriais"][user_id_str]
    salvar()

    await ctx.send(
        f"🗑️ Memorial de {membro.mention} foi removido com sucesso."
    )


@bot.command()
async def listar(ctx):
    """
    Lista todos os memoriais ativos.
    """

    if not dados["memoriais"]:
        await ctx.send("📭 Nenhum memorial ativo no momento.")
        return

    embed = discord.Embed(
        title="📋 Lista de Memoriais",
        color=discord.Color.blurple()
    )

    descricao = ""
    for user_id_str, memorial in dados["memoriais"].items():
        descricao += f"• **{memorial['nome']}** - {memorial['dias']} dias\n"

    embed.description = descricao
    embed.set_footer(
        text=f"Total de {len(dados['memoriais'])} memoriais"
    )

    await ctx.send(embed=embed)


@bot.command()
async def dias(ctx, membro: discord.Member = None):
    """
    Mostra o status atual do memorial de um usuário.
    Se nenhum usuário for mencionado, mostra o memorial do autor.
    """

    if membro is None:
        membro = ctx.author

    user_id_str = str(membro.id)

    if user_id_str not in dados["memoriais"]:
        await ctx.send(
            f"❌ Não existe memorial para {membro.mention}."
        )
        return

    memorial = get_memorial(membro.id)
    await ctx.send(
        embed=criar_embed_memorial(memorial, membro.id)
    )


@bot.command()
async def teste(ctx):
    """
    Testa a aparência do memorial do autor.
    Não altera nenhuma contagem.
    """

    if str(ctx.author.id) not in dados["memoriais"]:
        await ctx.send(
            "❌ Você não tem um memorial configurado.\n"
            "Peça a um administrador para configurar."
        )
        return

    memorial = get_memorial(ctx.author.id)
    await ctx.send("🧪 Visualização de teste:")
    await ctx.send(
        embed=criar_embed_memorial(memorial, ctx.author.id)
    )


@bot.command()
async def info(ctx):
    """
    Mostra informações técnicas do sistema.
    """

    embed = discord.Embed(
        title="📊 Informações do Sistema",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="📊 Total de Memoriais",
        value=str(len(dados["memoriais"])),
        inline=False
    )

    embed.add_field(
        name="🏆 Recorde Global",
        value=f"{RECORDE} dias",
        inline=False
    )

    embed.add_field(
        name="🌎 Horário do Sistema",
        value=agora().strftime("%d/%m/%Y %H:%M"),
        inline=False
    )

    # Lista os memoriais ativos
    if dados["memoriais"]:
        lista = ""
        for user_id_str, memorial in dados["memoriais"].items():
            lista += f"• {memorial['nome']} - {memorial['dias']} dias\n"
        embed.add_field(
            name="📋 Memoriais Ativos",
            value=lista,
            inline=False
        )

    await ctx.send(embed=embed)


# =========================================
# TRATAMENTO DE ERROS
# =========================================

@configurar.error
async def erro_configurar(ctx, erro):
    if isinstance(erro, commands.MissingPermissions):
        await ctx.send(
            "⛔ Apenas administradores "
            "podem configurar o memorial."
        )
    else:
        raise erro


@remover.error
async def erro_remover(ctx, erro):
    if isinstance(erro, commands.MissingPermissions):
        await ctx.send(
            "⛔ Apenas administradores "
            "podem remover memoriais."
        )
    else:
        raise erro


# =========================================
# MENSAGEM DE INICIALIZAÇÃO
# =========================================

@bot.event
async def on_connect():
    print("🔗 Conectando ao Discord...")

    @bot.event
    async def on_disconnect():
        print("🔴 Bot desconectado do Discord")

    @bot.event
    async def on_resumed():
        print("🟢 Conexão com o Discord retomada")


# =========================================
# INICIAR BOT
# =========================================

print("🚀 Iniciando Sistema de Memoriais Múltiplos...")
bot.run(TOKEN)
