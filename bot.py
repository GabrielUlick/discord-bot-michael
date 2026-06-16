import discord
from discord.ext import commands, tasks
import json
import datetime
import random
from flask import Flask
from threading import Thread
import os

TOKEN = os.getenv("TOKEN")
RECORDE = 456

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
    "https://giphy.com/gifs/sadness-inside-out-q2qxiBO5prG9i",
    "https://giphy.com/gifs/depression-13t22jOjxpkAN2",
    "https://giphy.com/gifs/sadness-mBaNKEmk9SUKs",
    "https://giphy.com/gifs/brownsugarapp-90s-devastating-dramatic-crying-d7rvF20PqNuGKSQGhf",
    "https://giphy.com/gifs/sad-doggy-viral-lunch-tre-face-instagram-bqZadRhjePrJeqONfL",
    "https://giphy.com/gifs/justin-crying-cry-vince-mcmahon-3QWfMsI8IaarXxtBt6",
    "https://giphy.com/gifs/crying-alone-neymar-sad-AzRo1Y4WlDSY7NohuJ",
    "https://giphy.com/gifs/red-listening-angry-bird-5c2aGDKZgCx7gV3QpZ",
    "https://giphy.com/gifs/unscreen-dogs-puppy-doggo-7uowYcS5MHuZT4f9Rr",
    "https://giphy.com/gifs/arrested-development-michael-cera-george-bluth-3oEjI80DSa1grNPTDq",
    "https://giphy.com/gifs/dog-sad-triste-OzlmyoTC2n3aOTXGFi"
]


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True
intents.voice_states = True

# ===== WEB SERVER PARA O RENDER =====

app = Flask(__name__)


@app.route("/")
def home():
    return "🌈 Memorial do Michael está online!"


def rodar_web():
    porta = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=porta
    )


Thread(target=rodar_web, daemon=True).start()

bot = commands.Bot(command_prefix="!", intents=intents)


def carregar():
    if not os.path.exists("dados.json"):
        dados_base = {
            "usuario_id": 0,
            "nome": "",
            "canal_id": 0,
            "dias": 18,
            "apareceu_hoje": False,
            "ultima_verificacao": ""
        }

        with open("dados.json", "w") as f:
            json.dump(dados_base, f, indent=4)

        return dados_base

    with open("dados.json", "r") as f:
        return json.load(f)


dados = carregar()


def salvar():
    with open("dados.json", "w") as f:
        json.dump(dados, f, indent=4)


async def enviar_memorial(canal):

    faltam = RECORDE - dados["dias"]

    mensagem = (
        "🌈 **═══ MEMORIAL DA SAUDADE ═══** 🌈\n\n"
        f"🕯️ Hoje são **{dados['dias']} dias** sem {dados['nome']}.\n\n"
        f"{random.choice(frases).format(nome=dados['nome'], dias=dados['dias'])}\n\n"
        f"🏆 Recorde histórico: **{RECORDE} dias** (1 ano e 3 meses)\n"
    )

    if dados["dias"] < RECORDE:
        mensagem += (
            f"⏳ Faltam **{faltam} dias** para alcançar o recorde.\n"
        )

    elif dados["dias"] == RECORDE:
        mensagem += (
            "👑 Hoje alcançamos o recorde histórico.\n"
        )

    else:
        mensagem += (
            "🌌 Um novo recorde está sendo escrito.\n"
        )

    await canal.send(mensagem)
    await canal.send(random.choice(gifs))


def marcou_presenca():
    dados["apareceu_hoje"] = True
    salvar()


@bot.event
async def on_ready():
    print(f"🌈 Memorial iniciado como {bot.user}")

    if not verificar_dia.is_running():
        verificar_dia.start()


@bot.event
async def on_message(msg):

    if msg.author.id == dados["usuario_id"]:
        marcou_presenca()

    await bot.process_commands(msg)


@bot.event
async def on_voice_state_update(member, before, after):

    if member.id == dados["usuario_id"]:
        marcou_presenca()


@bot.event
async def on_presence_update(before, after):

    if after.id == dados["usuario_id"]:
        if before.status != after.status:
            marcou_presenca()


@tasks.loop(minutes=1)
async def verificar_dia():

    agora = datetime.datetime.now()
    hoje = agora.strftime("%d/%m/%Y")

    if agora.hour == 0 and agora.minute == 0:

        if dados["ultima_verificacao"] != hoje:

            canal = bot.get_channel(dados["canal_id"])

            if not canal:
                return


            if dados["apareceu_hoje"]:

                await canal.send(
                    "🌈 **UM RETORNO INESPERADO** 🌈\n\n"
                    f"😭 Depois de **{dados['dias']} dias**, "
                    f"{dados['nome']} voltou ao servidor.\n\n"
                    "🕯️ O memorial volta ao dia 0, "
                    "mas as lembranças continuam."
                )

                dados["dias"] = 0

            else:

                dados["dias"] += 1
                await enviar_memorial(canal)


            dados["apareceu_hoje"] = False
            dados["ultima_verificacao"] = hoje

            salvar()


@bot.command()
async def configurar(ctx):

    if not ctx.message.mentions:

        await ctx.send(
            "❌ Use o comando marcando a pessoa.\n"
            "Exemplo: !configurar @usuario"
        )

        return


    membro = ctx.message.mentions[0]

    dados["usuario_id"] = membro.id
    dados["nome"] = membro.display_name
    dados["canal_id"] = ctx.channel.id

    salvar()


    await ctx.send(
        f"🕯️ O memorial de {membro.mention} foi iniciado."
    )

    await enviar_memorial(ctx.channel)


@bot.command()
async def dias(ctx):

    faltam = RECORDE - dados["dias"]

    mensagem = (
        "🌈 **═══ STATUS DO MEMORIAL ═══** 🌈\n\n"
        f"🕯️ Dias sem {dados['nome']}: "
        f"**{dados['dias']}**\n"
        f"🏆 Recorde: **{RECORDE} dias**\n"
    )


    if dados["dias"] < RECORDE:
        mensagem += (
            f"⏳ Faltam {faltam} dias para o recorde."
        )

    else:
        mensagem += (
            "👑 O recorde já foi alcançado."
        )


    await ctx.send(mensagem)
    await ctx.send(random.choice(gifs))


bot.run(TOKEN)
