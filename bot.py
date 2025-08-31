""" SuperBot - single-file starter Combine of modules: config, db, handlers (moderation, welcome, promotion, chat_ai, settings)

INSTRUCTIONS:

Replace the placeholder values in CONFIG section below (BOT_TOKEN, OWNER_ID, API keys).

Place a welcome background at the path set in DEFAULT_WELCOME_IMG or change the path.

Install requirements: pip install aiogram aiohttp Pillow python-dotenv pydantic requests

Run: python superbot_main.py


This is a scaffold: many complex features (NSFW API, AI chat via OpenAI, TTS) are left as TODO hooks for you to plug your API keys and follow provider docs. Read comments for exact spots to replace.

"""

---------------- CONFIG ----------------

BOT_TOKEN = "8227672111:AAFgcJ82XE6kDE-mtx51uAWyDc7o6fdJGhg" OWNER_ID = 7807985222  # <--- Replace with your telegram user id (int) DATABASE_PATH = "data/superbot.db" DEFAULT_WELCOME_IMG = "assets/default_welcome.png"

Optional API keys (fill if you will use corresponding services)

NSFW_API_KEY = ""  # e.g., Sightengine / DeepAI / HuggingFace token AI_CHAT_API_KEY = ""  # e.g., OpenAI key TTS_API_KEY = ""  # text-to-speech provider

---------------- END CONFIG ----------------

import os import io import re import sqlite3 import asyncio import random from pathlib import Path from typing import Optional

from PIL import Image, ImageDraw, ImageFont from aiogram import Bot, Dispatcher, types from aiogram.types import Message, ChatType, ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup

Create data folders

Path("data").mkdir(parents=True, exist_ok=True) Path("assets").mkdir(parents=True, exist_ok=True)

---------------- DATABASE ----------------

conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False) cur = conn.cursor()

def init_db(): cur.executescript(""" CREATE TABLE IF NOT EXISTS groups ( chat_id INTEGER PRIMARY KEY, settings TEXT DEFAULT '{}' ); CREATE TABLE IF NOT EXISTS welcomes ( chat_id INTEGER PRIMARY KEY, template TEXT, use_image INTEGER DEFAULT 1 ); CREATE TABLE IF NOT EXISTS warns ( chat_id INTEGER, user_id INTEGER, warns INTEGER DEFAULT 0, PRIMARY KEY (chat_id, user_id) ); CREATE TABLE IF NOT EXISTS owner_links ( id INTEGER PRIMARY KEY AUTOINCREMENT, link TEXT UNIQUE ); CREATE TABLE IF NOT EXISTS groups_list ( chat_id INTEGER PRIMARY KEY ); CREATE TABLE IF NOT EXISTS settings_store ( chat_id INTEGER PRIMARY KEY, settings TEXT DEFAULT '{}' ); """) conn.commit()

init_db()

CRUD helpers

def add_group(chat_id:int): cur.execute("INSERT OR IGNORE INTO groups_list(chat_id) VALUES (?)", (chat_id,)) conn.commit()

def list_groups(): cur.execute("SELECT chat_id FROM groups_list") return [row[0] for row in cur.fetchall()]

Welcome CRUD

def set_welcome(chat_id:int, template:str, use_image:bool=True): cur.execute("INSERT INTO welcomes(chat_id, template, use_image) VALUES(?,?,?) ON CONFLICT(chat_id) DO UPDATE SET template=excluded.template, use_image=excluded.use_image", (chat_id, template, 1 if use_image else 0)) conn.commit()

def get_welcome(chat_id:int): cur.execute("SELECT template, use_image FROM welcomes WHERE chat_id=?", (chat_id,)) r = cur.fetchone() return r if r else (None, 1)

Owner links

def add_owner_link(link:str): cur.execute("INSERT OR IGNORE INTO owner_links(link) VALUES (?)",(link,)) conn.commit()

def is_owner_link_in_text(text:str)->bool: cur.execute("SELECT link FROM owner_links") links=[r[0] for r in cur.fetchall()] for l in links: if l and l in text: return True return False

warns

def add_warn(chat_id:int, user_id:int): cur.execute("INSERT INTO warns(chat_id,user_id, warns) VALUES(?,?,1) ON CONFLICT(chat_id,user_id) DO UPDATE SET warns=warns+1", (chat_id, user_id)) conn.commit()

def get_warns(chat_id:int, user_id:int)->int: cur.execute("SELECT warns FROM warns WHERE chat_id=? AND user_id=?", (chat_id, user_id)) r=cur.fetchone() return r[0] if r else 0

---------------- BOT SETUP ----------------

bot = Bot(token=BOT_TOKEN) dp = Dispatcher()

URL_RE = re.compile(r"(https?://\S+|t.me/\S+)")

---------------- UTIL HELPERS ----------------

PLACEHOLDERS = { "{first_name}": lambda u, g: u.first_name or "", "{last_name}": lambda u, g: u.last_name or "", "{username}": lambda u, g: f"@{u.username}" if u.username else "", "{mention}": lambda u, g: f"{u.full_name}", "{id}": lambda u, g: str(u.id), "{group_name}": lambda u, g: g.title if hasattr(g, 'title') else str(g), "{member_count}": lambda u, g: str('?' ), "{fullname}": lambda u, g: getattr(u, 'full_name', f"{u.first_name} {u.last_name or ''}") }

def render_template(template:str, user:types.User, chat:types.Chat): out = template for k, fn in PLACEHOLDERS.items(): out = out.replace(k, fn(user, chat)) return out

async def is_user_admin(chat:types.Chat, user_id:int)->bool: try: member = await bot.get_chat_member(chat.id, user_id) return member.is_chat_admin() or member.status in ("administrator", "creator") except Exception: return False

---------------- MODERATION HANDLER ----------------

async def check_nsfw_media(msg:Message)->bool: # TODO: Implement real NSFW API call here. # If you add an external NSFW detector, use config.NSFW_API_KEY and call the API with the file bytes. return False

@dp.message(lambda m: m.chat.type != ChatType.PRIVATE) async def moderation_handler(msg:Message): text = msg.text or msg.caption or "" # External link check if URL_RE.search(text): if is_owner_link_in_text(text): return # future: check group settings to see if anti-link is enabled try: await msg.delete() except Exception: pass add_warn(msg.chat.id, msg.from_user.id) warns = get_warns(msg.chat.id, msg.from_user.id) if warns >= 3: try: await bot.ban_chat_member(msg.chat.id, msg.from_user.id) await bot.send_message(msg.chat.id, f"User {msg.from_user.get_mention(as_html=True)} banned for repeated links.", parse_mode='HTML') except Exception: pass return

# NSFW check for photos/videos
if msg.photo or msg.video:
    nsfw = await check_nsfw_media(msg)
    if nsfw:
        try:
            await msg.delete()
        except:
            pass
        add_warn(msg.chat.id, msg.from_user.id)
        await bot.send_message(msg.chat.id, f"NSFW content detected and removed: {msg.from_user.get_mention(as_html=True)}", parse_mode='HTML')
        return

---------------- WELCOME HANDLER ----------------

@dp.chat_member() async def on_chat_member_update(ev:ChatMemberUpdated): # handle new member join try: # If bot itself added to group, save group if ev.new_chat_member and ev.new_chat_member.user and ev.new_chat_member.user.id == (await bot.get_me()).id: add_group(ev.chat.id) return if ev.new_chat_member and ev.new_chat_member.status == 'member': user = ev.new_chat_member.user chat = ev.chat template, use_image = get_welcome(chat.id) if not template: template = "Welcome {mention} to {group_name}! You are our {member_count}th member." rendered = render_template(template, user, chat) if use_image: # generate simple welcome card try: base = Image.open(DEFAULT_WELCOME_IMG).convert("RGBA") except Exception: # fallback to plain message await bot.send_message(chat.id, rendered, parse_mode="Markdown") return draw = ImageDraw.Draw(base) try: font = ImageFont.truetype("arial.ttf", 18) except Exception: font = ImageFont.load_default() text = rendered draw.text((20, base.height - 80), text, (255,255,255), font=font) bio = io.BytesIO() base.save(bio, "PNG") bio.seek(0) await bot.send_photo(chat.id, photo=bio, caption=rendered, parse_mode="Markdown") else: await bot.send_message(chat.id, rendered, parse_mode="Markdown") except Exception as e: print("welcome handler error:", e)

---------------- WELCOME COMMANDS (ADMIN) ----------------

@dp.message(commands=['setwelcome']) async def cmd_setwelcome(msg:Message): # only admins can set if msg.chat.type == ChatType.PRIVATE: await msg.reply("This command must be used in group by admins.") return is_admin = await is_user_admin(msg.chat, msg.from_user.id) if not is_admin: await msg.reply("Only group admins can set welcome message.") return args = msg.get_args() if not args: await msg.reply("Usage: /setwelcome <welcome template>\nPlaceholders: {first_name}, {last_name}, {mention}, {username}, {id}, {group_name}, {member_count}") return # default to using image set_welcome(msg.chat.id, args, use_image=True) await msg.reply("✅ Welcome template saved. Use /previewwelcome to see sample.")

@dp.message(commands=['previewwelcome']) async def cmd_previewwelcome(msg:Message): t, use_image = get_welcome(msg.chat.id) if not t: await msg.reply("No welcome template set. Use /setwelcome first.") return # create a fake user object for preview fake_user = types.User(id=123456789, is_bot=False, first_name="Demo", last_name="User", username="demo_user") rendered = render_template(t, fake_user, msg.chat) if use_image: try: base = Image.open(DEFAULT_WELCOME_IMG).convert("RGBA") draw = ImageDraw.Draw(base) try: font = ImageFont.truetype("arial.ttf", 18) except Exception: font = ImageFont.load_default() draw.text((20, base.height - 80), rendered, (255,255,255), font=font) bio = io.BytesIO() base.save(bio, "PNG") bio.seek(0) await bot.send_photo(msg.chat.id, photo=bio, caption=rendered, parse_mode="Markdown") return except Exception: pass await msg.reply(rendered, parse_mode="Markdown")

---------------- PROMOTION (OWNER) ----------------

@dp.message(commands=['promote']) async def cmd_promote(msg:Message): if msg.from_user.id != OWNER_ID: await msg.reply("❌ Only owner can use this command.") return args = msg.get_args() if not args: await msg.reply("Usage: /promote <message>") return await msg.chat.send_message(args)

@dp.message(commands=['promoteall']) async def cmd_promoteall(msg:Message): # recommended to use in bot DM to owner if msg.from_user.id != OWNER_ID: await msg.reply("❌ Only owner can use this command.") return text = msg.get_args() if not text: await msg.reply("Usage: /promoteall <message>") return groups = list_groups() sent = 0 for gid in groups: try: await bot.send_message(gid, text) sent += 1 except Exception: pass await msg.reply(f"Promotion sent to {sent} groups.")

---------------- AI CHAT (Nezuko-like) ----------------

PERSONALITY_PREFIXES = ["Kon'nichiwa~", "Hiii Oniichan~", "Hehe~", "UwU", "Mmm~"]

@dp.message(lambda m: m.chat.type != ChatType.PRIVATE and not (m.text and m.text.startswith('/'))) async def ai_chat_handler(msg:Message): # for prototype, respond with personality + occasional sticker # In production: call AI_CHAT_API_KEY provider and stream realistic replies txt = (msg.text or '').lower() # voice request detection if any(k in txt for k in ("voice", "voice note", "voice bhejo", "gana sunao")): # TODO: implement real TTS and send as voice await msg.reply("🗣️ (voice) Oyasumii Oniichan~") return reply = random.choice(PERSONALITY_PREFIXES) + " " + f"{msg.from_user.first_name}, {random.choice(['kya haal?', 'kaise ho?', 'tumne kya kiya?'])}" if random.random() < 0.2: # optional: send sticker (replace with a valid file_id) try: await msg.reply_sticker("CAACAgIAAxkBAAEBPLACEHOLDER_STICKER_ID") except Exception: pass await msg.reply(reply)

---------------- SETTINGS PANEL ----------------

@dp.message(commands=['settings']) async def cmd_settings(msg:Message): if msg.chat.type == ChatType.PRIVATE: await msg.reply("Settings must be configured inside a group by admins.") return is_admin = await is_user_admin(msg.chat, msg.from_user.id) if not is_admin: await msg.reply("Only group admins can open settings.") return kb = InlineKeyboardMarkup(inline_keyboard=[ [InlineKeyboardButton(text="Toggle Moderation", callback_data="tog_mod")], [InlineKeyboardButton(text="Toggle Fun & Games", callback_data="tog_fun")], [InlineKeyboardButton(text="Toggle NSFW Filter", callback_data="tog_nsfw")], [InlineKeyboardButton(text="Toggle Promotion", callback_data="tog_promo")], [InlineKeyboardButton(text="Welcome Settings", callback_data="tog_welcome")], ]) await msg.reply("Group Settings — toggle features:", reply_markup=kb)

@dp.callback_query(lambda c: c.data and c.data.startswith("tog_")) async def cb_toggle(cq:types.CallbackQuery): key = cq.data.split("_",1)[1] # TODO: load and toggle settings in DB (settings_store) await cq.answer(f"Toggled {key}")

---------------- ADMIN UTIL: add owner link ----------------

@dp.message(commands=['addownerlink']) async def cmd_addownerlink(msg:Message): if msg.from_user.id != OWNER_ID: return link = msg.get_args().strip() if not link: await msg.reply("Usage: /addownerlink <link>") return add_owner_link(link) await msg.reply("Owner link added to whitelist.")

---------------- START / CHAT MEMBER ----------------

@dp.message(commands=['start']) async def start_cmd(msg:Message): if msg.chat.type == ChatType.PRIVATE: await msg.reply(f"SuperBot online. Owner: {OWNER_ID}\nUse /promoteall from here to run mass promotion.") else: await msg.reply("SuperBot at your service. Use /settings to configure.")

@dp.chat_member() async def on_bot_added(update:ChatMemberUpdated): # duplicate handler to ensure group stored try: if update.new_chat_member and update.new_chat_member.user and update.new_chat_member.user.id == (await bot.get_me()).id: add_group(update.chat.id) except Exception: pass

---------------- RUN ----------------

if name == 'main': print("SuperBot starting...") # ensure DB exists init_db() # guidance printed for owner print("REPLACE these in file TOP: BOT_TOKEN, OWNER_ID, DEFAULT_WELCOME_IMG, and optional API keys.") try: import uvloop n        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy()) except Exception: pass dp.run_polling(bot)

