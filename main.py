import discord
from discord import app_commands, ui
import requests
import os
import json
from dotenv import load_dotenv
from datetime import datetime, timedelta

# ============================
# ENVIRONMENT SETUP
# ============================
if os.path.exists('.env'):
    load_dotenv()

JSONBIN_URL = os.getenv("JSONBIN_URL")
JSONBIN_API_KEY = os.getenv("JSONBIN_API_KEY")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))
DEV_ID = int(os.getenv("DEV_DISCORD_ID", "0"))
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

WHITELIST_PAUSED = False

# ============================
# RED THEME COLORS
# ============================
COLOR_PRIMARY = 0xDC143C      # Crimson Red (Main)
COLOR_SUCCESS = 0xFF4500     # Orange Red (Success)
COLOR_ERROR = 0x8B0000       # Dark Red (Error)
COLOR_WARNING = 0xFF6347     # Tomato (Warning)
COLOR_INFO = 0xCD5C5C        # Indian Red (Info)

# ============================
# JSONBIN.IO FUNCTIONS
# ============================
def get_whitelist_data():
    """Fetch whitelist data from JSONBin.io"""
    try:
        response = requests.get(JSONBIN_URL, headers=JSONBIN_HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list):
                return data
            else:
                return []
        else:
            print(f"Error fetching data: {response.status_code}")
            return []
    except Exception as e:
        print(f"Error fetching from JSONBin: {e}")
        return []

def update_whitelist_data(data):
    """Update whitelist data on JSONBin.io"""
    try:
        response = requests.put(JSONBIN_URL, headers=JSONBIN_HEADERS, json=data, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Error updating JSONBin: {e}")
        return False

def get_uid_entry(uid):
    """Get specific UID entry from whitelist"""
    data = get_whitelist_data()
    for entry in data:
        if entry.get("uid") == uid:
            return entry
    return None

def add_uid_entry(uid, expiry, comment):
    """Add or update UID entry"""
    data = get_whitelist_data()
    
    existing_index = -1
    for i, entry in enumerate(data):
        if entry.get("uid") == uid:
            existing_index = i
            break
    
    new_entry = {
        "uid": uid,
        "expiry_date": expiry,
        "comment": comment
    }
    
    if existing_index >= 0:
        data[existing_index] = new_entry
    else:
        data.append(new_entry)
    
    return update_whitelist_data(data)

def remove_uid_entry(uid):
    """Remove UID entry"""
    data = get_whitelist_data()
    new_data = [entry for entry in data if entry.get("uid") != uid]
    
    if len(new_data) != len(data):
        return update_whitelist_data(new_data)
    return False

def change_uid_entry(old_uid, new_uid):
    """Change UID from old to new while keeping expiry and comment"""
    data = get_whitelist_data()
    
    # Check if new UID already exists
    for entry in data:
        if entry.get("uid") == new_uid:
            return False, "NEW_UID_EXISTS"
    
    # Find and update old UID
    for entry in data:
        if entry.get("uid") == old_uid:
            entry["uid"] = new_uid
            if update_whitelist_data(data):
                return True, "SUCCESS"
            else:
                return False, "UPDATE_FAILED"
    
    return False, "OLD_UID_NOT_FOUND"

def get_all_uids():
    """Get all UID entries"""
    return get_whitelist_data()

# ============================
# LOGGING SYSTEM
# ============================
async def send_log(bot, action: str, uid: str, user: discord.User, expiry: str = None, comment: str = None, old_uid: str = None):
    """Enhanced logging function with formatted messages"""
    if not LOG_CHANNEL_ID:
        return
        
    ch = bot.get_channel(LOG_CHANNEL_ID)
    if not ch:
        return

    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if action == "ADD":
        embed = discord.Embed(
            title="🔴 UID ADDED",
            color=COLOR_SUCCESS,
            timestamp=datetime.now()
        )
        embed.add_field(name="UID", value=f"`{uid}`", inline=True)
        embed.add_field(name="Expiry", value=f"`{expiry}`", inline=True)
        embed.add_field(name="Comment", value=f"`{comment}`", inline=True)
        embed.add_field(name="Added By", value=f"`{user.name}`\n(`{user.id}`)", inline=True)
        embed.add_field(name="Timestamp", value=f"`{current_time}`", inline=True)
        
    elif action == "REMOVE":
        embed = discord.Embed(
            title="❌ UID REMOVED",
            color=COLOR_ERROR,
            timestamp=datetime.now()
        )
        embed.add_field(name="UID", value=f"`{uid}`", inline=True)
        embed.add_field(name="Removed By", value=f"`{user.name}`\n(`{user.id}`)", inline=True)
        embed.add_field(name="Timestamp", value=f"`{current_time}`", inline=True)
        
    elif action == "CHANGE":
        embed = discord.Embed(
            title="🔄 UID CHANGED",
            color=COLOR_WARNING,
            timestamp=datetime.now()
        )
        embed.add_field(name="Old UID", value=f"`{old_uid}`", inline=True)
        embed.add_field(name="New UID", value=f"`{uid}`", inline=True)
        embed.add_field(name="Changed By", value=f"`{user.name}`\n(`{user.id}`)", inline=True)
        embed.add_field(name="Timestamp", value=f"`{current_time}`", inline=True)
        
    elif action == "PAUSE":
        embed = discord.Embed(
            title="⏸️ SYSTEM PAUSED",
            color=COLOR_WARNING,
            timestamp=datetime.now()
        )
        embed.add_field(name="Action By", value=f"`{user.name}`\n(`{user.id}`)", inline=True)
        embed.add_field(name="Timestamp", value=f"`{current_time}`", inline=True)
        
    elif action == "RESUME":
        embed = discord.Embed(
            title="▶️ SYSTEM RESUMED",
            color=COLOR_SUCCESS,
            timestamp=datetime.now()
        )
        embed.add_field(name="Action By", value=f"`{user.name}`\n(`{user.id}`)", inline=True)
        embed.add_field(name="Timestamp", value=f"`{current_time}`", inline=True)
    
    embed.set_footer(text="🔴 Whitelist System")
    await ch.send(embed=embed)

async def send_simple_log(bot, message: str):
    """Simple text-based log"""
    if not LOG_CHANNEL_ID:
        return
        
    ch = bot.get_channel(LOG_CHANNEL_ID)
    if ch:
        await ch.send(f"`{datetime.now().strftime('%H:%M:%S')}` {message}")

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
    uid_input = ui.TextInput(
        label="UID",
        placeholder="กรอก UID ที่ต้องการตรวจสอบ",
        required=True,
        max_length=50
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        uid = self.uid_input.value.strip()
        
        # Defer response ก่อนเพื่อป้องกัน timeout (3 วินาที)
        await interaction.response.defer(ephemeral=True)
        
        entry = get_uid_entry(uid)
        
        if not entry:
            embed = discord.Embed(
                title="❌ ไม่พบ UID",
                description=f"UID `{uid}` ไม่อยู่ในระบบ",
                color=COLOR_ERROR
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        pretty = format_box_date(entry["expiry_date"])
        embed = discord.Embed(
            title="📦 ข้อมูล WHITELIST",
            color=COLOR_PRIMARY
        )
        embed.add_field(name="🔑 UID", value=f"`{entry['uid']}`", inline=False)
        embed.add_field(name="📅 วันหมดอายุ", value=f"`{pretty}`", inline=True)
        embed.add_field(name="📝 หมายเหตุ", value=f"`{entry['comment']}`", inline=True)
        embed.set_footer(text="🔴 Whitelist System")
        
        await interaction.followup.send(embed=embed, ephemeral=True)


class AddUIDModal(ui.Modal, title="➕ เพิ่ม UID"):
    uid_input = ui.TextInput(
        label="UID",
        placeholder="กรอก UID",
        required=True,
        max_length=50
    )
    days_input = ui.TextInput(
        label="จำนวนวัน",
        placeholder="เช่น 30 (จะหมดอายุอีก 30 วันจากวันนี้)",
        required=True,
        max_length=5
    )
    comment_input = ui.TextInput(
        label="หมายเหตุ (Comment)",
        placeholder="กรอกหมายเหตุ",
        required=True,
        max_length=100
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        global WHITELIST_PAUSED
        
        if WHITELIST_PAUSED:
            embed = discord.Embed(
                title="⚠️ ระบบถูกหยุดชั่วคราว",
                description="ไม่สามารถเพิ่ม UID ได้ในขณะนี้",
                color=COLOR_WARNING
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            uid = self.uid_input.value.strip()
            days = int(self.days_input.value.strip())
            comment = self.comment_input.value.strip()
            
            if days <= 0:
                embed = discord.Embed(
                    title="❌ จำนวนวันไม่ถูกต้อง",
                    description="กรุณากรอกจำนวนวันมากกว่า 0",
                    color=COLOR_ERROR
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Defer response ก่อนเพื่อป้องกัน timeout (3 วินาที)
            await interaction.response.defer(ephemeral=True)
            
            # คำนวณวันหมดอายุจากวันนี้ + จำนวนวัน
            expiry_date = datetime.now() + timedelta(days=days)
            expiry = expiry_date.strftime("%Y-%m-%d")
            
            existing_entry = get_uid_entry(uid)
            action = "updated" if existing_entry else "added"
            
            success = add_uid_entry(uid, expiry, comment)
            
            if success:
                if action == "added":
                    embed = discord.Embed(
                        title="✅ เพิ่ม UID สำเร็จ",
                        description=f"UID `{uid}` ถูกเพิ่มเรียบร้อยแล้ว",
                        color=COLOR_SUCCESS
                    )
                else:
                    embed = discord.Embed(
                        title="🔄 อัพเดท UID สำเร็จ",
                        description=f"UID `{uid}` ถูกอัพเดทเรียบร้อยแล้ว",
                        color=COLOR_WARNING
                    )
                embed.add_field(name="📅 วันหมดอายุ", value=f"`{format_box_date(expiry)}`", inline=True)
                embed.add_field(name="⏱️ จำนวนวัน", value=f"`{days} วัน`", inline=True)
                embed.add_field(name="📝 หมายเหตุ", value=f"`{comment}`", inline=True)
                embed.set_footer(text="🔴 Whitelist System")
                
                await interaction.followup.send(embed=embed, ephemeral=True)
                await send_log(interaction.client, "ADD", uid, interaction.user, expiry, comment)
            else:
                embed = discord.Embed(
                    title="❌ เกิดข้อผิดพลาด",
                    description="ไม่สามารถบันทึกข้อมูลได้",
                    color=COLOR_ERROR
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                
        except ValueError:
            embed = discord.Embed(
                title="❌ รูปแบบไม่ถูกต้อง",
                description="กรุณากรอกจำนวนวันเป็นตัวเลข",
                color=COLOR_ERROR
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)


class RemoveUIDModal(ui.Modal, title="🗑️ ลบ UID"):
    uid_input = ui.TextInput(
        label="UID",
        placeholder="กรอก UID ที่ต้องการลบ",
        required=True,
        max_length=50
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        global WHITELIST_PAUSED
        
        if WHITELIST_PAUSED:
            embed = discord.Embed(
                title="⚠️ ระบบถูกหยุดชั่วคราว",
                description="ไม่สามารถลบ UID ได้ในขณะนี้",
                color=COLOR_WARNING
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        uid = self.uid_input.value.strip()
        
        # Defer response ก่อนเพื่อป้องกัน timeout (3 วินาที)
        await interaction.response.defer(ephemeral=True)
        
        success = remove_uid_entry(uid)
        
        if success:
            embed = discord.Embed(
                title="🗑️ ลบ UID สำเร็จ",
                description=f"UID `{uid}` ถูกลบเรียบร้อยแล้ว",
                color=COLOR_SUCCESS
            )
            embed.set_footer(text="🔴 Whitelist System")
            await interaction.followup.send(embed=embed, ephemeral=True)
            await send_log(interaction.client, "REMOVE", uid, interaction.user)
        else:
            embed = discord.Embed(
                title="❌ ไม่พบ UID",
                description=f"UID `{uid}` ไม่อยู่ในระบบ",
                color=COLOR_ERROR
            )
            await interaction.followup.send(embed=embed, ephemeral=True)


class ChangeUIDModal(ui.Modal, title="🔄 เปลี่ยน UID"):
    old_uid_input = ui.TextInput(
        label="UID เก่า",
        placeholder="กรอก UID เก่าที่ต้องการเปลี่ยน",
        required=True,
        max_length=50
    )
    new_uid_input = ui.TextInput(
        label="UID ใหม่",
        placeholder="กรอก UID ใหม่",
        required=True,
        max_length=50
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        global WHITELIST_PAUSED
        
        if WHITELIST_PAUSED:
            embed = discord.Embed(
                title="⚠️ ระบบถูกหยุดชั่วคราว",
                description="ไม่สามารถเปลี่ยน UID ได้ในขณะนี้",
                color=COLOR_WARNING
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        old_uid = self.old_uid_input.value.strip()
        new_uid = self.new_uid_input.value.strip()
        
        if old_uid == new_uid:
            embed = discord.Embed(
                title="❌ ข้อผิดพลาด",
                description="UID เก่าและใหม่ต้องไม่เหมือนกัน",
                color=COLOR_ERROR
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Defer response ก่อนเพื่อป้องกัน timeout (3 วินาที)
        await interaction.response.defer(ephemeral=True)
        
        success, status = change_uid_entry(old_uid, new_uid)
        
        if success:
            embed = discord.Embed(
                title="✅ เปลี่ยน UID สำเร็จ",
                description=f"เปลี่ยน UID จาก `{old_uid}` เป็น `{new_uid}` เรียบร้อยแล้ว",
                color=COLOR_SUCCESS
            )
            embed.set_footer(text="🔴 Whitelist System")
            await interaction.followup.send(embed=embed, ephemeral=True)
            await send_log(interaction.client, "CHANGE", new_uid, interaction.user, old_uid=old_uid)
        else:
            if status == "OLD_UID_NOT_FOUND":
                embed = discord.Embed(
                    title="❌ ไม่พบ UID เก่า",
                    description=f"UID `{old_uid}` ไม่อยู่ในระบบ",
                    color=COLOR_ERROR
                )
            elif status == "NEW_UID_EXISTS":
                embed = discord.Embed(
                    title="❌ UID ใหม่มีอยู่แล้ว",
                    description=f"UID `{new_uid}` มีอยู่ในระบบแล้ว",
                    color=COLOR_ERROR
                )
            else:
                embed = discord.Embed(
                    title="❌ เกิดข้อผิดพลาด",
                    description="ไม่สามารถเปลี่ยน UID ได้",
                    color=COLOR_ERROR
                )
            await interaction.followup.send(embed=embed, ephemeral=True)


# ============================
# MAIN MENU VIEW (BUTTONS)
# ============================

class MainMenuView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @ui.button(label="🔍 ตรวจสอบ UID", style=discord.ButtonStyle.danger, custom_id="check_uid", row=0)
    async def check_uid_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(CheckUIDModal())
    
    @ui.button(label="📋 ดู UID ทั้งหมด", style=discord.ButtonStyle.danger, custom_id="list_uids", row=0)
    async def list_uids_button(self, interaction: discord.Interaction, button: ui.Button):
        # Defer response ก่อนเพื่อป้องกัน timeout (3 วินาที)
        await interaction.response.defer(ephemeral=True)
        
        try:
            data = get_all_uids()
            
            if not data:
                embed = discord.Embed(
                    title="📋 รายการ UID",
                    description="ไม่มี UID ในระบบ",
                    color=COLOR_INFO
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            embed = discord.Embed(
                title="📋 รายการ UID ทั้งหมด",
                color=COLOR_PRIMARY
            )
            
            # แบ่งเป็นหลาย field ถ้ามีข้อมูลมาก
            uid_list = ""
            for i, entry in enumerate(data):
                line = f"`{entry['uid']}` - {format_box_date(entry['expiry_date'])} - {entry['comment']}\n"
                if len(uid_list) + len(line) > 1000:
                    embed.add_field(name="📦 UIDs", value=uid_list, inline=False)
                    uid_list = line
                else:
                    uid_list += line
            
            if uid_list:
                embed.add_field(name="📦 UIDs", value=uid_list, inline=False)
            
            embed.set_footer(text=f"🔴 ทั้งหมด {len(data)} รายการ")
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = discord.Embed(
                title="❌ เกิดข้อผิดพลาด",
                description="ไม่สามารถเชื่อมต่อฐานข้อมูลได้",
                color=COLOR_ERROR
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    @ui.button(label="➕ เพิ่ม UID", style=discord.ButtonStyle.danger, custom_id="add_uid", row=1)
    async def add_uid_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(AddUIDModal())
    
    @ui.button(label="🔄 เปลี่ยน UID", style=discord.ButtonStyle.danger, custom_id="change_uid", row=1)
    async def change_uid_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(ChangeUIDModal())
    
    @ui.button(label="🗑️ ลบ UID", style=discord.ButtonStyle.secondary, custom_id="remove_uid", row=2)
    async def remove_uid_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(RemoveUIDModal())
    
    @ui.button(label="⏸️ หยุดระบบ", style=discord.ButtonStyle.secondary, custom_id="pause_system", row=2)
    async def pause_button(self, interaction: discord.Interaction, button: ui.Button):
        global WHITELIST_PAUSED
        
        if interaction.user.id != DEV_ID:
            embed = discord.Embed(
                title="❌ ไม่มีสิทธิ์",
                description="เฉพาะเจ้าของบอทเท่านั้นที่สามารถหยุดระบบได้",
                color=COLOR_ERROR
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        WHITELIST_PAUSED = True
        embed = discord.Embed(
            title="⏸️ หยุดระบบชั่วคราว",
            description="ระบบ Whitelist ถูกหยุดชั่วคราวแล้ว",
            color=COLOR_WARNING
        )
        embed.set_footer(text="🔴 Whitelist System")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await send_log(interaction.client, "PAUSE", "", interaction.user)
    
    @ui.button(label="▶️ เปิดระบบ", style=discord.ButtonStyle.secondary, custom_id="resume_system", row=2)
    async def resume_button(self, interaction: discord.Interaction, button: ui.Button):
        global WHITELIST_PAUSED
        
        if interaction.user.id != DEV_ID:
            embed = discord.Embed(
                title="❌ ไม่มีสิทธิ์",
                description="เฉพาะเจ้าของบอทเท่านั้นที่สามารถเปิดระบบได้",
                color=COLOR_ERROR
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        WHITELIST_PAUSED = False
        embed = discord.Embed(
            title="▶️ เปิดระบบ",
            description="ระบบ Whitelist กลับมาทำงานแล้ว",
            color=COLOR_SUCCESS
        )
        embed.set_footer(text="🔴 Whitelist System")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await send_log(interaction.client, "RESUME", "", interaction.user)


# ============================
# BOT CLASS
# ============================
class MyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def on_ready(self):
        print(f"[READY] Logged in as {self.user}")
        
        # Register persistent view
        self.add_view(MainMenuView())
        
        try:
            cmds = await self.tree.sync()
            print(f"Synced {len(cmds)} commands.")
            await send_simple_log(self, "🔴 **Bot Started Successfully**")
        except Exception as e:
            print(f"Error syncing commands: {e}")

    async def setup_hook(self):
        print("[SETUP] Bot is starting up...")

bot = MyBot()

# ============================
# /menu - SHOW MAIN MENU WITH BUTTONS
# ============================
@bot.tree.command(name="menu", description="แสดงเมนูหลัก Whitelist System")
async def menu_cmd(interaction: discord.Interaction):
    if ALLOWED_CHANNEL and interaction.channel_id != ALLOWED_CHANNEL:
        await interaction.response.send_message(
            "❌ คุณสามารถใช้คำสั่งได้เฉพาะในช่องที่กำหนดเท่านั้น",
            ephemeral=True
        )
        return
    
    embed = discord.Embed(
        title="🔴 WHITELIST SYSTEM",
        description=(
            "**ยินดีต้อนรับสู่ระบบจัดการ Whitelist**\n\n"
            "กรุณาเลือกการดำเนินการจากปุ่มด้านล่าง:\n\n"
            "🔍 **ตรวจสอบ UID** - ค้นหาข้อมูล UID\n"
            "📋 **ดู UID ทั้งหมด** - แสดงรายการ UID ทั้งหมด\n"
            "➕ **เพิ่ม UID** - เพิ่ม UID ใหม่เข้าระบบ\n"
            "🔄 **เปลี่ยน UID** - เปลี่ยน UID เก่าเป็น UID ใหม่\n"
            "🗑️ **ลบ UID** - ลบ UID ออกจากระบบ\n"
            "⏸️ **หยุดระบบ** - หยุดระบบชั่วคราว (Owner)\n"
            "▶️ **เปิดระบบ** - เปิดระบบอีกครั้ง (Owner)"
        ),
        color=COLOR_PRIMARY
    )
    embed.set_footer(text="🔴 Whitelist System | เลือกปุ่มด้านล่างเพื่อดำเนินการ")
    
    # Check system status
    if WHITELIST_PAUSED:
        embed.add_field(name="⚠️ สถานะระบบ", value="**หยุดชั่วคราว**", inline=False)
    else:
        embed.add_field(name="✅ สถานะระบบ", value="**ทำงานปกติ**", inline=False)
    
    await interaction.response.send_message(embed=embed, view=MainMenuView())


# ============================
# RUN BOT
# ============================
if __name__ == "__main__":
    bot.run(BOT_TOKEN)
