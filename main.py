import discord
from discord import app_commands, ui
import requests
import os
import json
import asyncio
from dotenv import load_dotenv
from datetime import datetime
from functools import partial

# ============================
# ENVIRONMENT SETUP
# ============================
if os.path.exists('.env'):
    load_dotenv()

JSONBIN_URL = os.getenv("JSONBIN_URL")
JSONBIN_API_KEY = os.getenv("JSONBIN_API_KEY")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))
ALLOWED_CHANNEL = int(os.getenv("ALLOWED_CHANNEL", "0"))

# Validate required environment variables
required_vars = {
    "JSONBIN_URL": JSONBIN_URL,
    "JSONBIN_API_KEY": JSONBIN_API_KEY,
    "DISCORD_BOT_TOKEN": BOT_TOKEN
}

missing_vars = [var for var, value in required_vars.items() if not value]
if missing_vars:
    raise Exception(f"Missing environment variables: {', '.join(missing_vars)}")

JSONBIN_HEADERS = {
    "Content-Type": "application/json",
    "X-Master-Key": JSONBIN_API_KEY,
    "X-Bin-Meta": "false"
}

# ============================
# RED THEME COLORS
# ============================
COLOR_PRIMARY = 0xDC143C      # Crimson Red (Main)
COLOR_SUCCESS = 0xFF4500     # Orange Red (Success)
COLOR_ERROR = 0x8B0000       # Dark Red (Error)
COLOR_WARNING = 0xFF6347     # Tomato (Warning)
COLOR_INFO = 0xCD5C5C        # Indian Red (Info)

# ============================
# JSONBIN.IO FUNCTIONS (THREAD-SAFE WRAPPERS)
# ============================
def fetch_jsonbin():
    """Blocking function to fetch data"""
    try:
        response = requests.get(JSONBIN_URL, headers=JSONBIN_HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return data if isinstance(data, list) else []
        return []
    except Exception as e:
        print(f"Error fetching from JSONBin: {e}")
        return []

def push_jsonbin(data):
    """Blocking function to update data"""
    try:
        response = requests.put(JSONBIN_URL, headers=JSONBIN_HEADERS, json=data, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Error updating JSONBin: {e}")
        return False

async def get_whitelist_data():
    """Non-blocking fetch using run_in_executor to prevent event loop lag"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fetch_jsonbin)

async def update_whitelist_data(data):
    """Non-blocking update"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(push_jsonbin, data))

async def get_uid_entry(uid):
    data = await get_whitelist_data()
    for entry in data:
        if entry.get("uid") == uid:
            return entry
    return None

async def add_uid_entry(uid, expiry, comment):
    data = await get_whitelist_data()
    existing_index = -1
    for i, entry in enumerate(data):
        if entry.get("uid") == uid:
            existing_index = i
            break
    
    new_entry = {"uid": uid, "expiry_date": expiry, "comment": comment}
    if existing_index >= 0:
        data[existing_index] = new_entry
    else:
        data.append(new_entry)
    
    return await update_whitelist_data(data)

async def remove_uid_entry(uid):
    data = await get_whitelist_data()
    new_data = [entry for entry in data if entry.get("uid") != uid]
    if len(new_data) != len(data):
        return await update_whitelist_data(new_data)
    return False

async def change_uid_entry(old_uid, new_uid):
    data = await get_whitelist_data()
    for entry in data:
        if entry.get("uid") == new_uid:
            return False, "NEW_UID_EXISTS"
    
    found = False
    for entry in data:
        if entry.get("uid") == old_uid:
            entry["uid"] = new_uid
            found = True
            break
            
    if found:
        success = await update_whitelist_data(data)
        return (True, "SUCCESS") if success else (False, "UPDATE_FAILED")
    
    return False, "OLD_UID_NOT_FOUND"

# ============================
# LOGGING SYSTEM
# ============================
async def send_log(bot, action: str, uid: str, user: discord.User, expiry: str = None, comment: str = None, old_uid: str = None):
    if not LOG_CHANNEL_ID: return
    ch = bot.get_channel(LOG_CHANNEL_ID)
    if not ch: return

    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    embed = discord.Embed(timestamp=datetime.now())
    embed.set_footer(text="🔴 Whitelist System")
    
    if action == "ADD":
        embed.title = "🔴 UID ADDED"
        embed.color = COLOR_SUCCESS
        embed.add_field(name="UID", value=f"`{uid}`", inline=True)
        embed.add_field(name="Expiry", value=f"`{expiry}`", inline=True)
        embed.add_field(name="Comment", value=f"`{comment}`", inline=True)
    elif action == "REMOVE":
        embed.title = "❌ UID REMOVED"
        embed.color = COLOR_ERROR
        embed.add_field(name="UID", value=f"`{uid}`", inline=True)
    elif action == "CHANGE":
        embed.title = "🔄 UID CHANGED"
        embed.color = COLOR_WARNING
        embed.add_field(name="Old UID", value=f"`{old_uid}`", inline=True)
        embed.add_field(name="New UID", value=f"`{uid}`", inline=True)

    embed.add_field(name="Action By", value=f"`{user.name}`\n(`{user.id}`)", inline=True)
    embed.add_field(name="Timestamp", value=f"`{current_time}`", inline=True)
    
    try:
        await ch.send(embed=embed)
    except Exception as e:
        print(f"Log error: {e}")

async def send_simple_log(bot, message: str):
    if not LOG_CHANNEL_ID: return
    ch = bot.get_channel(LOG_CHANNEL_ID)
    if ch:
        try:
            await ch.send(f"`{datetime.now().strftime('%H:%M:%S')}` {message}")
        except: pass

# ============================
# FORMAT DATE
# ============================
def format_box_date(raw):
    try:
        y, m, d = raw.split("-")
        return f"{d} - {m} - {y}"
    except:
        return raw

# ============================
# MODALS (INPUT FORMS)
# ============================

class CheckUIDModal(ui.Modal, title="🔍 ตรวจสอบ UID"):
    uid_input = ui.TextInput(label="UID", placeholder="กรอก UID ที่ต้องการตรวจสอบ", required=True, max_length=50)
    
    async def on_submit(self, interaction: discord.Interaction):
        # defer interaction ทันทีเพื่อป้องกัน Timeout 3 วินาที
        await interaction.response.defer(ephemeral=True)
        uid = self.uid_input.value.strip()
        entry = await get_uid_entry(uid)
        
        if not entry:
            embed = discord.Embed(title="❌ ไม่พบ UID", description=f"UID `{uid}` ไม่อยู่ในระบบ", color=COLOR_ERROR)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        embed = discord.Embed(title="📦 ข้อมูล WHITELIST", color=COLOR_PRIMARY)
        embed.add_field(name="🔑 UID", value=f"`{entry['uid']}`", inline=False)
        embed.add_field(name="📅 วันหมดอายุ", value=f"`{format_box_date(entry['expiry_date'])}`", inline=True)
        embed.add_field(name="📝 หมายเหตุ", value=f"`{entry['comment']}`", inline=True)
        embed.set_footer(text="🔴 Whitelist System")
        await interaction.followup.send(embed=embed, ephemeral=True)

class AddUIDModal(ui.Modal, title="➕ เพิ่ม UID"):
    uid_input = ui.TextInput(label="UID", placeholder="กรอก UID", required=True, max_length=50)
    year_input = ui.TextInput(label="ปี (Year)", placeholder="เช่น 2025", required=True, max_length=4)
    month_input = ui.TextInput(label="เดือน (Month)", placeholder="เช่น 12", required=True, max_length=2)
    day_input = ui.TextInput(label="วัน (Day)", placeholder="เช่น 31", required=True, max_length=2)
    comment_input = ui.TextInput(label="หมายเหตุ (Comment)", placeholder="กรอกหมายเหตุ", required=True, max_length=100)
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            uid = self.uid_input.value.strip()
            year = int(self.year_input.value.strip())
            month = int(self.month_input.value.strip())
            day = int(self.day_input.value.strip())
            comment = self.comment_input.value.strip()
            expiry = f"{year:04d}-{month:02d}-{day:02d}"
            
            existing_entry = await get_uid_entry(uid)
            success = await add_uid_entry(uid, expiry, comment)
            
            if success:
                status_text = "อัพเดท" if existing_entry else "เพิ่ม"
                embed = discord.Embed(title=f"✅ {status_text} UID สำเร็จ", color=COLOR_SUCCESS if not existing_entry else COLOR_WARNING)
                embed.description = f"UID `{uid}` ถูกดำเนินการเรียบร้อยแล้ว"
                embed.add_field(name="📅 วันหมดอายุ", value=f"`{format_box_date(expiry)}`", inline=True)
                embed.add_field(name="📝 หมายเหตุ", value=f"`{comment}`", inline=True)
                await interaction.followup.send(embed=embed, ephemeral=True)
                await send_log(interaction.client, "ADD", uid, interaction.user, expiry, comment)
            else:
                await interaction.followup.send("❌ เกิดข้อผิดพลาดในการบันทึกข้อมูล", ephemeral=True)
        except ValueError:
            await interaction.followup.send("❌ รูปแบบวันที่ไม่ถูกต้อง (ต้องเป็นตัวเลข)", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

class RemoveUIDModal(ui.Modal, title="🗑️ ลบ UID"):
    uid_input = ui.TextInput(label="UID", placeholder="กรอก UID ที่ต้องการลบ", required=True, max_length=50)
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = self.uid_input.value.strip()
        success = await remove_uid_entry(uid)
        
        if success:
            embed = discord.Embed(title="🗑️ ลบ UID สำเร็จ", description=f"UID `{uid}` ถูกลบแล้ว", color=COLOR_SUCCESS)
            await interaction.followup.send(embed=embed, ephemeral=True)
            await send_log(interaction.client, "REMOVE", uid, interaction.user)
        else:
            await interaction.followup.send(f"❌ ไม่พบ UID `{uid}` ในระบบ", ephemeral=True)

class ChangeUIDModal(ui.Modal, title="🔄 เปลี่ยน UID"):
    old_uid_input = ui.TextInput(label="UID เก่า", placeholder="กรอก UID เก่า", required=True)
    new_uid_input = ui.TextInput(label="UID ใหม่", placeholder="กรอก UID ใหม่", required=True)
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        old_uid = self.old_uid_input.value.strip()
        new_uid = self.new_uid_input.value.strip()
        
        if old_uid == new_uid:
            await interaction.followup.send("❌ UID ใหม่ต้องไม่ซ้ำกับอันเดิม", ephemeral=True)
            return

        success, status = await change_uid_entry(old_uid, new_uid)
        if success:
            embed = discord.Embed(title="✅ เปลี่ยน UID สำเร็จ", description=f"จาก `{old_uid}` เป็น `{new_uid}`", color=COLOR_SUCCESS)
            await interaction.followup.send(embed=embed, ephemeral=True)
            await send_log(interaction.client, "CHANGE", new_uid, interaction.user, old_uid=old_uid)
        else:
            msg = "ไม่พบ UID เก่า" if status == "OLD_UID_NOT_FOUND" else "UID ใหม่มีในระบบแล้ว" if status == "NEW_UID_EXISTS" else "บันทึกล้มเหลว"
            await interaction.followup.send(f"❌ {msg}", ephemeral=True)

# ============================
# MAIN MENU VIEW (STABLE VERSION)
# ============================

class MainMenuView(ui.View):
    def __init__(self):
        # กำหนด timeout=None เพื่อให้ปุ่มอยู่ถาวร (Persistent View)
        super().__init__(timeout=None)
    
    @ui.button(label="🔍 ตรวจสอบ UID", style=discord.ButtonStyle.danger, custom_id="persistent:check_uid", row=0)
    async def check_uid_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(CheckUIDModal())
    
    @ui.button(label="📋 ดู UID ทั้งหมด", style=discord.ButtonStyle.danger, custom_id="persistent:list_uids", row=0)
    async def list_uids_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            data = await get_whitelist_data()
            if not data:
                await interaction.followup.send("📋 ไม่มีข้อมูล UID ในระบบ", ephemeral=True)
                return
            
            embed = discord.Embed(title="📋 รายการ UID ทั้งหมด", color=COLOR_PRIMARY)
            uid_chunks = []
            current_chunk = ""
            
            for entry in data:
                line = f"`{entry['uid']}` | {format_box_date(entry['expiry_date'])} | {entry['comment']}\n"
                if len(current_chunk) + len(line) > 1024:
                    uid_chunks.append(current_chunk)
                    current_chunk = line
                else:
                    current_chunk += line
            if current_chunk: uid_chunks.append(current_chunk)

            for i, chunk in enumerate(uid_chunks):
                embed.add_field(name=f"📦 รายการที่ {i+1}", value=chunk, inline=False)
            
            embed.set_footer(text=f"🔴 ทั้งหมด {len(data)} รายการ")
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

    @ui.button(label="➕ เพิ่ม UID", style=discord.ButtonStyle.danger, custom_id="persistent:add_uid", row=1)
    async def add_uid_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(AddUIDModal())
    
    @ui.button(label="🔄 เปลี่ยน UID", style=discord.ButtonStyle.danger, custom_id="persistent:change_uid", row=1)
    async def change_uid_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(ChangeUIDModal())
    
    @ui.button(label="🗑️ ลบ UID", style=discord.ButtonStyle.secondary, custom_id="persistent:remove_uid", row=2)
    async def remove_uid_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(RemoveUIDModal())

# ============================
# BOT CLASS
# ============================
class MyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def on_ready(self):
        print(f"[READY] Logged in as {self.user}")
        # ลงทะเบียน persistent view เพื่อให้ปุ่มรันได้ตลอดแม้บอทรีสตาร์ท
        self.add_view(MainMenuView())
        
        try:
            await self.tree.sync()
            print("Commands Synced.")
            await send_simple_log(self, "🔴 **Bot System Online**")
        except Exception as e:
            print(f"Sync error: {e}")

    async def setup_hook(self):
        # เรียกใช้ตอนบอทเริ่มทำงาน
        print("[SETUP] Preparing environment...")

bot = MyBot()

# ============================
# COMMANDS
# ============================
@bot.tree.command(name="menu", description="แสดงเมนูหลัก Whitelist System")
async def menu_cmd(interaction: discord.Interaction):
    if ALLOWED_CHANNEL and interaction.channel_id != ALLOWED_CHANNEL:
        await interaction.response.send_message("❌ ไม่อนุญาตให้ใช้คำสั่งในห้องนี้", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="🔴 WHITELIST SYSTEM",
        description=(
            "**ระบบจัดการ Whitelist (Array Mode)**\n\n"
            "🔍 **ตรวจสอบ UID** - ค้นหาข้อมูลรายตัว\n"
            "📋 **ดู UID ทั้งหมด** - แสดงรายการที่มีทั้งหมด\n"
            "➕ **เพิ่ม UID** - ลงทะเบียนใหม่\n"
            "🔄 **เปลี่ยน UID** - แก้ไขรหัสเดิม\n"
            "🗑️ **ลบ UID** - นำข้อมูลออก"
        ),
        color=COLOR_PRIMARY
    )
    embed.set_footer(text="🔴 Whitelist System | เลือกเมนูด้านล่าง")
    
    # ส่งเมนูพร้อม View ที่ไม่มีปุ่ม Pause/Resume แล้ว
    await interaction.response.send_message(embed=embed, view=MainMenuView())

# ============================
# RUN BOT
# ============================
if __name__ == "__main__":
    bot.run(BOT_TOKEN)
