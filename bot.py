import discord
from discord.ext import commands, tasks
import json
import datetime
import asyncio
import os

TOKEN = os.getenv("TOKEN")


# ===== INTENTS =====

intents = discord.Intents.default()

intents.message_content = True
intents.members = True
intents.presences = True
intents.voice_states = True


bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# ===== DADOS =====


def carregar():
    with open("dados.json", "r") as arquivo:
        return json.load(arquivo)


def salvar(dados):
    with open("dados.json", "w") as arquivo:
        json.dump(dados, arquivo, indent=4)


dados = carregar()


# ===== BOT LIGADO =====


@bot.event
async def on_ready():
    print(f"Logado como {bot.user}")
    verificar_dia.start()


# ===== DETECTAR MENSAGENS =====


@bot.event
async def on_message(msg):

    if msg.author.id == dados["usuario_id"]:
        dados["apareceu_hoje"] = True
        salvar(dados)

    await bot.process_commands(msg)


# ===== DETECTAR CALL =====


@bot.event
async def on_voice_state_update(member, before, after):

    if member.id == dados["usuario_id"]:
        dados["apareceu_hoje"] = True
        salvar(dados)


# ===== DETECTAR STATUS =====


@bot.event
async def on_presence_update(before, after):

    if after.id == dados["usuario_id"]:

        if before.status != after.status:
            dados["apareceu_hoje"] = True
            salvar(dados)


# ===== VERIFICAR TODO MINUTO =====


@tasks.loop(minutes=1)
async def verificar_dia():

    agora = datetime.datetime.now()

    data = agora.strftime("%d/%m/%Y")

    if agora.hour == 0 and agora.minute == 0:

        if dados["ultima_verificacao"] != data:

            canal = bot.get_channel(dados["canal_id"])

            if canal is None:
                print("Canal não encontrado.")
                return


            if dados["apareceu_hoje"]:

                dados["dias"] = 0

                await canal.send(
                    "⚠️ Michael apareceu no servidor hoje!\n"
                    "Contador reiniciado para 0."
                )

            else:

                dados["dias"] += 1

                await canal.send(
                    f"🌈 {dados['dias']} dias sem a presença do Michael no servidor."
                )


            dados["apareceu_hoje"] = False

            dados["ultima_verificacao"] = data

            salvar(dados)


# ===== COMANDO CONFIGURAR =====


@bot.command()
async def configurar(ctx, membro: discord.Member):

    dados["usuario_id"] = membro.id

    dados["canal_id"] = ctx.channel.id

    salvar(dados)


    await ctx.send(
        f"Agora estou monitorando {membro.mention} neste canal."
    )


# ===== COMANDO VER DIAS =====


@bot.command()
async def dias(ctx):

    await ctx.send(
        f"🌈 Atualmente são {dados['dias']} dias sem Michael."
    )


# ===== INICIAR BOT =====


bot.run(TOKEN)
