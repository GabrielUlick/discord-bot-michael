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
        "hora": agora().strftime("%d/%m/%Y %H:%M:%S")
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
    "usuario_id": 0,
    "nome": "",
    "canal_id": 0,

    "dias": 18,

    "apareceu_hoje": False,

    # formato YYYY-MM-DD
    "ultima_data": hoje().isoformat()
}


def carregar():

    if not os.path.exists(
        "dados.json"
    ):
        salvar(DADOS_PADRAO)
        return DADOS_PADRAO.copy()

    try:

        with open(
            "dados.json",
            "r",
            encoding="utf-8"
        ) as arquivo:

            dados = json.load(arquivo)


        # adiciona chaves que faltarem
        for chave, valor in DADOS_PADRAO.items():

            if chave not in dados:
                dados[chave] = valor


        return dados


    except Exception as erro:

        print(
            "⚠️ JSON corrompido:",
            erro
        )

        salvar(DADOS_PADRAO)

        return DADOS_PADRAO.copy()



def salvar(conteudo=None):

    if conteudo is None:
        conteudo = dados


    with open(
        "dados.json",
        "w",
        encoding="utf-8"
    ) as arquivo:

        json.dump(
            conteudo,
            arquivo,
            indent=4,
            ensure_ascii=False
        )


dados = carregar()


# =========================================
# CONFIGURAÇÃO DO BOT
# =========================================

intents = discord.Intents.default()

intents.message_content = True

# Presença removida para economizar recursos
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

def marcou_presenca():
    """
    Marca que o usuário apareceu hoje.
    """

    if not dados["apareceu_hoje"]:
        dados["apareceu_hoje"] = True
        salvar()


@bot.event
async def on_message(msg):

    if (
        dados["usuario_id"] != 0
        and msg.author.id == dados["usuario_id"]
    ):
        marcou_presenca()

    await bot.process_commands(msg)


@bot.event
async def on_voice_state_update(member, before, after):

    if (
        dados["usuario_id"] != 0
        and member.id == dados["usuario_id"]
    ):
        marcou_presenca()


# =========================================
# EMBEDS DO MEMORIAL
# =========================================

def criar_embed_memorial():

    dias = dados["dias"]

    embed = discord.Embed(
        title="🌈 ═══ MEMORIAL DA SAUDADE ═══ 🌈",
        color=discord.Color.blue()
    )

    embed.description = (
        f"🕯️ **Hoje são {dias} dias sem {dados['nome']}**\n\n"
        f"{random.choice(frases).format(nome=dados['nome'], dias=dias)}"
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


def criar_embed_retorno():

    embed = discord.Embed(
        title="🌈 UM RETORNO INESPERADO 🌈",
        color=discord.Color.green()
    )


    embed.description = (
        f"😭 Depois de **{dados['dias']} dias**, "
        f"**{dados['nome']}** apareceu novamente.\n\n"
        "🕯️ O memorial volta ao dia 0,\n"
        "mas as lembranças continuam vivas."
    )


    embed.set_footer(
        text="A contagem foi reiniciada."
    )


    return embed


async def enviar_memorial(canal):

    await canal.send(
        embed=criar_embed_memorial()
    )


async def enviar_retorno(canal):

    await canal.send(
        embed=criar_embed_retorno()
    )


# =========================================
# SISTEMA DE CONTAGEM INTELIGENTE
# =========================================

async def verificar_passagem_dos_dias():
    """
    Verifica quantos dias se passaram desde
    a última atualização registrada.
    """

    hoje_atual = hoje()

    ultima = date.fromisoformat(
        dados["ultima_data"]
    )


    dias_passados = (
        hoje_atual - ultima
    ).days


    # Nada mudou
    if dias_passados <= 0:
        return


    canal = bot.get_channel(
        dados["canal_id"]
    )


    if canal is None:

        print(
            "⚠️ Canal do memorial não encontrado."
        )

        dados["ultima_data"] = hoje_atual.isoformat()

        salvar()

        return


    # Para cada dia que passou,
    # atualiza a contagem corretamente
    for _ in range(dias_passados):

        if dados["apareceu_hoje"]:

            await enviar_retorno(canal)

            dados["dias"] = 0

        else:

            dados["dias"] += 1

            await enviar_memorial(canal)


        # Novo dia começa sem presença
        dados["apareceu_hoje"] = False


    dados["ultima_data"] = hoje_atual.isoformat()

    salvar()


# =========================================
# LOOP AUTOMÁTICO
# =========================================

@tasks.loop(minutes=5)
async def verificar_sistema():

    await verificar_passagem_dos_dias()


@bot.event
async def on_ready():

    print(
        f"🌈 Memorial iniciado como {bot.user}"
    )

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


    dados["usuario_id"] = membro.id
    dados["nome"] = membro.display_name
    dados["canal_id"] = ctx.channel.id

    # Reinicia o controle de dias
    dados["apareceu_hoje"] = False
    dados["ultima_data"] = hoje().isoformat()

    salvar()


    await ctx.send(
        f"🌈 O memorial de {membro.mention} "
        "foi configurado com sucesso."
    )


    # Envia o estado atual
    await enviar_memorial(ctx.channel)



@bot.command()
async def dias(ctx):
    """
    Mostra o status atual do memorial.
    """

    if dados["usuario_id"] == 0:

        await ctx.send(
            "❌ Nenhum memorial foi configurado ainda."
        )
        return


    await ctx.send(
        embed=criar_embed_memorial()
    )



@bot.command()
async def teste(ctx):
    """
    Testa a aparência do memorial.
    Não altera nenhuma contagem.
    """

    await ctx.send(
        "🧪 Visualização de teste:"
    )

    await ctx.send(
        embed=criar_embed_memorial()
    )



@bot.command()
async def info(ctx):
    """
    Mostra informações técnicas do sistema.
    """

    if dados["usuario_id"] == 0:

        await ctx.send(
            "❌ Nenhum memorial configurado."
        )
        return


    embed = discord.Embed(
        title="📊 Informações do Memorial",
        color=discord.Color.blurple()
    )


    embed.add_field(
        name="👤 Pessoa lembrada",
        value=dados["nome"],
        inline=False
    )


    embed.add_field(
        name="📅 Dias de ausência",
        value=str(dados["dias"]),
        inline=True
    )


    embed.add_field(
        name="🏆 Recorde",
        value=f"{RECORDE} dias",
        inline=True
    )


    embed.add_field(
        name="📍 Canal",
        value=f"<#{dados['canal_id']}>",
        inline=False
    )


    embed.add_field(
        name="🕒 Última atualização",
        value=dados["ultima_data"],
        inline=False
    )


    embed.add_field(
        name="🌎 Horário",
        value=agora().strftime("%d/%m/%Y %H:%M"),
        inline=False
    )


    await ctx.send(
        embed=embed
    )



# =========================================
# TRATAMENTO DE ERROS
# =========================================


@configurar.error
async def erro_configurar(ctx, erro):

    if isinstance(
        erro,
        commands.MissingPermissions
    ):

        await ctx.send(
            "⛔ Apenas administradores "
            "podem configurar o memorial."
        )

    else:

        raise erro



# =========================================
# MENSAGEM DE INICIALIZAÇÃO
# =========================================


@bot.event
async def on_connect():

    print(
        "🔗 Conectando ao Discord..."
    )

    @bot.event
    async def on_disconnect():
        print("🔴 Bot desconectado do Discord")
    
    
    @bot.event
    async def on_resumed():
        print("🟢 Conexão com o Discord retomada")

# =========================================
# INICIAR BOT
# =========================================


print(
    "🚀 Iniciando Memorial da Saudade..."
)

bot.run(TOKEN)
