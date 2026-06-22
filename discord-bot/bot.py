"""Discord 質疑応答ボット（stella-bot）。

指定した複数チャンネルの発言を取り込み（RAG）、その内容にもとづいて
質問に答える。管理はすべてスラッシュコマンドで行うため、
PC・iPhone・Android どの Discord アプリからでも操作できる。

主なコマンド:
  /source_add    チャンネルを知識ソースに登録し、過去ログを取り込む
  /source_remove チャンネルを登録解除（取り込んだ内容も削除）
  /source_list   登録中のチャンネル一覧
  /reindex       登録中チャンネルを取り込み直す
  /status        取り込み状況の確認
  /ask           質問する（ボットへのメンションでも可）
"""
from __future__ import annotations

import os
from typing import List

import discord
from discord import app_commands
from dotenv import load_dotenv

import store
import llm

load_dotenv()

HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "2000"))
TOP_K = int(os.getenv("TOP_K", "8"))
# 類似度がこの値未満の参考情報は「無関係」とみなして渡さない
MIN_SCORE = float(os.getenv("MIN_SCORE", "0.55"))

intents = discord.Intents.default()
intents.message_content = True  # メッセージ本文の取得に必須（Portalでも有効化が必要）

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


# ============ ユーティリティ ============

async def ingest_channel(channel: discord.TextChannel) -> int:
    """チャンネルの過去ログを取り込んで保存件数を返す。"""
    rows: List[tuple] = []
    async for msg in channel.history(limit=HISTORY_LIMIT):
        if msg.author.bot:
            continue
        content = (msg.content or "").strip()
        if not content:
            continue
        rows.append((msg.id, msg.author.display_name, content))

    total = 0
    # 埋め込みAPIに優しいよう、ある程度まとめて処理
    for i in range(0, len(rows), 100):
        total += store.upsert_documents(
            channel.guild.id, channel.id, rows[i : i + 100]
        )
    return total


def build_answer(question: str, guild_id: int) -> str:
    hits = store.search(guild_id, question, top_k=TOP_K)
    hits = [h for h in hits if h.score >= MIN_SCORE]
    blocks = [f"{h.author}: {h.content}" for h in hits]
    answer = llm.generate_answer(question, blocks)
    if hits:
        # 参照したチャンネルを重複なくまとめて表示
        channel_ids = list(dict.fromkeys(h.channel_id for h in hits))
        refs = ", ".join(f"<#{cid}>" for cid in channel_ids)
        answer += f"\n\n_参考: {refs}_"
    return answer


# ============ イベント ============

@client.event
async def on_ready():
    store.init_db()
    await tree.sync()
    print(f"ログイン完了: {client.user} （スラッシュコマンド同期済み）")


@client.event
async def on_message(message: discord.Message):
    if message.author.bot or message.guild is None:
        return

    # 登録チャンネルの新規発言はリアルタイムで索引に追加（常に最新に保つ）
    if store.is_source(message.guild.id, message.channel.id):
        content = (message.content or "").strip()
        if content:
            store.upsert_documents(
                message.guild.id,
                message.channel.id,
                [(message.id, message.author.display_name, content)],
            )

    # ボットへのメンションは質問として扱う
    if client.user in message.mentions:
        question = message.clean_content.replace(f"@{client.user.display_name}", "").strip()
        if not question:
            await message.reply("質問内容を一緒に書いて送ってください。例: `@ボット 〇〇について教えて`")
            return
        async with message.channel.typing():
            answer = build_answer(question, message.guild.id)
        await message.reply(answer[:2000])


# ============ スラッシュコマンド ============

def _is_admin(interaction: discord.Interaction) -> bool:
    perms = interaction.user.guild_permissions
    return perms.manage_guild or perms.administrator


@tree.command(name="ask", description="登録チャンネルの内容にもとづいて質問に答えます")
@app_commands.describe(question="知りたいこと")
async def ask(interaction: discord.Interaction, question: str):
    await interaction.response.defer(thinking=True)
    answer = build_answer(question, interaction.guild_id)
    await interaction.followup.send(answer[:2000])


@tree.command(name="source_add", description="チャンネルを知識ソースに登録し過去ログを取り込みます（管理者）")
@app_commands.describe(channel="知識として取り込むテキストチャンネル")
async def source_add(interaction: discord.Interaction, channel: discord.TextChannel):
    if not _is_admin(interaction):
        await interaction.response.send_message("このコマンドはサーバー管理権限が必要です。", ephemeral=True)
        return
    store.add_source(interaction.guild_id, channel.id)
    await interaction.response.defer(thinking=True)
    try:
        n = await ingest_channel(channel)
        await interaction.followup.send(
            f"✅ {channel.mention} を登録し、{n} 件のメッセージを取り込みました。"
        )
    except Exception as e:  # noqa: BLE001
        await interaction.followup.send(f"⚠️ 取り込み中にエラーが発生しました: `{e}`")


@tree.command(name="source_remove", description="チャンネルを登録解除し取り込んだ内容を削除します（管理者）")
@app_commands.describe(channel="登録解除するチャンネル")
async def source_remove(interaction: discord.Interaction, channel: discord.TextChannel):
    if not _is_admin(interaction):
        await interaction.response.send_message("このコマンドはサーバー管理権限が必要です。", ephemeral=True)
        return
    store.remove_source(interaction.guild_id, channel.id)
    await interaction.response.send_message(f"🗑️ {channel.mention} を登録解除しました。")


@tree.command(name="source_list", description="登録中の知識ソースチャンネル一覧")
async def source_list(interaction: discord.Interaction):
    ids = store.list_sources(interaction.guild_id)
    if not ids:
        await interaction.response.send_message("登録中のチャンネルはありません。`/source_add` で追加してください。")
        return
    lines = [f"・<#{cid}>（{store.count_documents(interaction.guild_id, cid)} 件）" for cid in ids]
    await interaction.response.send_message("**登録中の知識ソース**\n" + "\n".join(lines))


@tree.command(name="reindex", description="登録中のチャンネルをすべて取り込み直します（管理者）")
async def reindex(interaction: discord.Interaction):
    if not _is_admin(interaction):
        await interaction.response.send_message("このコマンドはサーバー管理権限が必要です。", ephemeral=True)
        return
    ids = store.list_sources(interaction.guild_id)
    if not ids:
        await interaction.response.send_message("登録中のチャンネルがありません。")
        return
    await interaction.response.defer(thinking=True)
    total = 0
    for cid in ids:
        ch = client.get_channel(cid)
        if isinstance(ch, discord.TextChannel):
            total += await ingest_channel(ch)
    await interaction.followup.send(f"🔄 再取り込み完了。合計 {total} 件を更新しました。")


@tree.command(name="status", description="取り込み状況を表示します")
async def status(interaction: discord.Interaction):
    total = store.count_documents(interaction.guild_id)
    n_sources = len(store.list_sources(interaction.guild_id))
    await interaction.response.send_message(
        f"📊 登録チャンネル: {n_sources} 個 / 取り込み済みメッセージ: {total} 件\n"
        f"使用モデル: 生成 `{llm.CHAT_MODEL}` / 埋め込み `{llm.EMBED_MODEL}`"
    )


def main():
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("環境変数 DISCORD_BOT_TOKEN が設定されていません。")
    client.run(token)


if __name__ == "__main__":
    main()
