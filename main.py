import discord
from discord import app_commands, ui
import requests
import os
import asyncio
import threading
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

# Point System - Pastebin URL
POINTS_URL = os.getenv("POINTS_URL")  # https://pastebin.com/raw/yYXXzvmg
POINTS_PER_DAY = 5  # 1 วัน = 5 points

# Validate required environment variables
required_vars = {
    "JSONBIN_URL": JSONBIN_URL,
    "JSONBIN_API_KEY": JSONBIN_API_KEY,
    "DISCORD_BOT_TOKEN": BOT_TOKEN
}

# POINTS_URL is optional - if not set, point system will be disabled
POINTS_ENABLED = bool(POINTS_URL)

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
# LOCAL CACHE SYSTEM
# ============================
WHITELIST_CACHE = []
CACHE_LOCK = threading.Lock()
CACHE_LOADED = False

# Point System Cache
POINTS_CACHE = {}  # {discord_user_id: points}
POINTS_LOCK = threading.Lock()

def load_cache_from_jsonbin():
    """Load data from JSONBin to local cache (called once at startup)"""
    global WHITELIST_CACHE, CACHE_LOADED
    try:
        response = requests.get(JSONBIN_URL, headers=JSONBIN_HEADERS, timeout=30)
        if response.status_code == 200:
            data = response.json()
            with CACHE_LOCK:
                WHITELIST_CACHE = data if isinstance(data, list) else []
                CACHE_LOADED = True
            print(f"[CACHE] Loaded {len(WHITELIST_CACHE)} entries from JSONBin")
            return True
        else:
            print(f"[CACHE] Error loading: {response.status_code}")
            return False
    except Exception as e:
        print(f"[CACHE] Error loading from JSONBin: {e}")
        return False

def sync_cache_to_jsonbin():
    """Sync local cache to JSONBin (background task)"""
    try:
        with CACHE_LOCK:
            data_to_sync = WHITELIST_CACHE.copy()
        
        response = requests.put(JSONBIN_URL, headers=JSONBIN_HEADERS, json=data_to_sync, timeout=30)
        if response.status_code == 200:
            print(f"[SYNC] Successfully synced {len(data_to_sync)} entries to JSONBin")
            return True
        else:
            print(f"[SYNC] Error syncing: {response.status_code}")
            return False
    except Exception as e:
        print(f"[SYNC] Error syncing to JSONBin: {e}")
        return False

def sync_in_background():
    """Run sync in a separate thread to not block the bot"""
    thread = threading.Thread(target=sync_cache_to_jsonbin)
    thread.start()

# ============================
# POINTS SYSTEM FUNCTIONS
# ============================

# JSONBin Headers for Points (same API key)
POINTS_HEADERS = {
    "Content-Type": "application/json",
    "X-Master-Key": JSONBIN_API_KEY,
    "X-Bin-Meta": "false"
}

def load_points_from_storage():
    """Load points data from storage"""
    global POINTS_CACHE
    try:
        response = requests.get(POINTS_URL, headers=POINTS_HEADERS, timeout=30)
        if response.status_code == 200:
            data = response.json()
            with POINTS_LOCK:
                POINTS_CACHE = data if isinstance(data, dict) else {}
            print(f"[POINTS] Loaded {len(POINTS_CACHE)} user points")
            return True
        else:
            print(f"[POINTS] Error loading: {response.status_code}")
            return False
    except Exception as e:
        print(f"[POINTS] Error loading points: {e}")
        return False

def sync_points_to_storage():
    """Sync points cache to storage"""
    try:
        with POINTS_LOCK:
            data_to_sync = POINTS_CACHE.copy()
        
        response = requests.put(POINTS_URL, headers=POINTS_HEADERS, json=data_to_sync, timeout=30)
        if response.status_code == 200:
            print(f"[POINTS] Synced {len(data_to_sync)} user points")
            return True
        else:
            print(f"[POINTS] Error syncing: {response.status_code}")
            return False
    except Exception as e:
        print(f"[POINTS] Error syncing points: {e}")
        return False

def sync_points_in_background():
    """Run points sync in background"""
    thread = threading.Thread(target=sync_points_to_storage)
    thread.start()

def get_user_points(user_id: str) -> int:
    """Get points for a user (instant from cache)"""
    with POINTS_LOCK:
        return POINTS_CACHE.get(str(user_id), 0)

def add_user_points(user_id: str, amount: int) -> int:
    """Add points to a user and return new balance"""
    global POINTS_CACHE
    with POINTS_LOCK:
        user_id = str(user_id)
        current = POINTS_CACHE.get(user_id, 0)
        new_balance = current + amount
        POINTS_CACHE[user_id] = new_balance
    sync_points_in_background()
    return new_balance

def deduct_user_points(user_id: str, amount: int) -> tuple[bool, int]:
    """Deduct points from user. Returns (success, remaining_balance)"""
    global POINTS_CACHE
    with POINTS_LOCK:
        user_id = str(user_id)
        current = POINTS_CACHE.get(user_id, 0)
        if current < amount:
            return False, current
        new_balance = current - amount
        POINTS_CACHE[user_id] = new_balance
    sync_points_in_background()
    return True, new_balance

def calculate_points_needed(days: int) -> int:
    """Calculate points needed for given days"""
    return days * POINTS_PER_DAY

# ============================
# FAST CACHE FUNCTIONS (NO API CALLS)
# ============================
def get_uid_entry(uid):
    """Get specific UID entry from local cache (instant)"""
    with CACHE_LOCK:
        for entry in WHITELIST_CACHE:
            if entry.get("uid") == uid:
                return entry.copy()
    return None

def add_uid_entry(uid, expiry, comment):
    """Add or update UID entry in local cache, then sync in background"""
    global WHITELIST_CACHE
    
    with CACHE_LOCK:
        existing_index = -1
        for i, entry in enumerate(WHITELIST_CACHE):
            if entry.get("uid") == uid:
                existing_index = i
                break
        
        new_entry = {
            "uid": uid,
            "expiry_date": expiry,
            "comment": comment
        }
        
        if existing_index >= 0:
            WHITELIST_CACHE[existing_index] = new_entry
        else:
            WHITELIST_CACHE.append(new_entry)
    
    # Sync to JSONBin in background
    sync_in_background()
    return True

def remove_uid_entry(uid):
    """Remove UID entry from local cache, then sync in background"""
    global WHITELIST_CACHE
    
    with CACHE_LOCK:
        original_len = len(WHITELIST_CACHE)
        WHITELIST_CACHE = [entry for entry in WHITELIST_CACHE if entry.get("uid") != uid]
        removed = len(WHITELIST_CACHE) != original_len
    
    if removed:
        sync_in_background()
        return True
    return False

def change_uid_entry(old_uid, new_uid):
    """Change UID from old to new in local cache, then sync in background"""
    global WHITELIST_CACHE
    
    with CACHE_LOCK:
        # Check if new UID already exists
        for entry in WHITELIST_CACHE:
            if entry.get("uid") == new_uid:
                return False, "NEW_UID_EXISTS"
        
        # Find and update old UID
        for entry in WHITELIST_CACHE:
            if entry.get("uid") == old_uid:
                entry["uid"] = new_uid
                sync_in_background()
                return True, "SUCCESS"
    
    return False, "OLD_UID_NOT_FOUND"

def get_all_uids():
    """Get all UID entries from local cache (instant)"""
    with CACHE_LOCK:
        return WHITELIST_CACHE.copy()

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
        
        # ใช้ cache ทำให้เร็วมาก ไม่ต้อง defer
        entry = get_uid_entry(uid)
        
        if not entry:
            embed = discord.Embed(
                title="❌ ไม่พบ UID",
                description=f"UID `{uid}` ไม่อยู่ในระบบ",
                color=COLOR_ERROR
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
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
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


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
            
            # ตรวจสอบและหัก points (ถ้าเปิดใช้งานระบบ points)
            points_needed = 0
            remaining_points = 0
            if POINTS_ENABLED:
                points_needed = calculate_points_needed(days)
                user_id = str(interaction.user.id)
                current_points = get_user_points(user_id)
                
                # ตรวจสอบว่ามี points เพียงพอหรือไม่
                if current_points < points_needed:
                    embed = discord.Embed(
                        title="❌ Points ไม่เพียงพอ",
                        description=(
                            f"คุณมี **{current_points}** points\n"
                            f"ต้องการ **{points_needed}** points ({days} วัน x {POINTS_PER_DAY} points)\n"
                            f"ขาดอีก **{points_needed - current_points}** points"
                        ),
                        color=COLOR_ERROR
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
                
                # หัก points
                success_deduct, remaining_points = deduct_user_points(user_id, points_needed)
                
                if not success_deduct:
                    embed = discord.Embed(
                        title="❌ Points ไม่เพียงพอ",
                        description="เกิดข้อผิดพลาดในการหัก points",
                        color=COLOR_ERROR
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
            
            # คำนวณวันหมดอายุจากวันนี้ + จำนวนวัน
            expiry_date = datetime.now() + timedelta(days=days)
            expiry = expiry_date.strftime("%Y-%m-%d")
            
            existing_entry = get_uid_entry(uid)
            action = "updated" if existing_entry else "added"
            
            # ใช้ cache ทำให้เร็วมาก (sync ไป JSONBin ใน background)
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
                if POINTS_ENABLED:
                    embed.add_field(name="💰 หัก Points", value=f"`-{points_needed}`", inline=True)
                    embed.add_field(name="💳 คงเหลือ", value=f"`{remaining_points}` points", inline=True)
                embed.set_footer(text="🔴 Whitelist System")
                
                await interaction.response.send_message(embed=embed, ephemeral=True)
                await send_log(interaction.client, "ADD", uid, interaction.user, expiry, comment)
            else:
                # คืน points ถ้าเพิ่ม UID ไม่สำเร็จ
                if POINTS_ENABLED:
                    add_user_points(str(interaction.user.id), points_needed)
                embed = discord.Embed(
                    title="❌ เกิดข้อผิดพลาด",
                    description="ไม่สามารถบันทึกข้อมูลได้" + (" (points ถูกคืนแล้ว)" if POINTS_ENABLED else ""),
                    color=COLOR_ERROR
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                
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
        
        # ใช้ cache ทำให้เร็วมาก (sync ไป JSONBin ใน background)
        success = remove_uid_entry(uid)
        
        if success:
            embed = discord.Embed(
                title="🗑️ ลบ UID สำเร็จ",
                description=f"UID `{uid}` ถูกลบเรียบร้อยแล้ว",
                color=COLOR_SUCCESS
            )
            embed.set_footer(text="🔴 Whitelist System")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            await send_log(interaction.client, "REMOVE", uid, interaction.user)
        else:
            embed = discord.Embed(
                title="❌ ไม่พบ UID",
                description=f"UID `{uid}` ไม่อยู่ในระบบ",
                color=COLOR_ERROR
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)


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
        
        # ใช้ cache ทำให้เร็วมาก (sync ไป JSONBin ใน background)
        success, status = change_uid_entry(old_uid, new_uid)
        
        if success:
            embed = discord.Embed(
                title="✅ เปลี่ยน UID สำเร็จ",
                description=f"เปลี่ยน UID จาก `{old_uid}` เป็น `{new_uid}` เรียบร้อยแล้ว",
                color=COLOR_SUCCESS
            )
            embed.set_footer(text="🔴 Whitelist System")
            await interaction.response.send_message(embed=embed, ephemeral=True)
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
            await interaction.response.send_message(embed=embed, ephemeral=True)


# ============================
# ADD POINTS MODAL (Owner only)
# ============================
class AddPointsModal(ui.Modal, title="💰 เพิ่ม Points"):
    user_id_input = ui.TextInput(
        label="Discord User ID",
        placeholder="กรอก User ID (เช่น 123456789012345678)",
        required=True,
        max_length=20
    )
    amount_input = ui.TextInput(
        label="จำนวน Points",
        placeholder="กรอกจำนวน Points ที่ต้องการเพิ่ม",
        required=True,
        max_length=10
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        if not POINTS_ENABLED:
            embed = discord.Embed(
                title="⚠️ ระบบ Points ไม่เปิดใช้งาน",
                description="กรุณาตั้งค่า POINTS_URL ใน .env",
                color=COLOR_WARNING
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            user_id = self.user_id_input.value.strip()
            amount = int(self.amount_input.value.strip())
            
            if amount <= 0:
                embed = discord.Embed(
                    title="❌ จำนวนไม่ถูกต้อง",
                    description="กรุณาระบุจำนวน Points มากกว่า 0",
                    color=COLOR_ERROR
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            new_balance = add_user_points(user_id, amount)
            
            embed = discord.Embed(
                title="✅ เพิ่ม Points สำเร็จ",
                description=f"เพิ่ม **{amount}** points ให้ User ID: `{user_id}`",
                color=COLOR_SUCCESS
            )
            embed.add_field(name="💰 เพิ่ม", value=f"`+{amount}` points", inline=True)
            embed.add_field(name="💳 คงเหลือ", value=f"`{new_balance}` points", inline=True)
            embed.set_footer(text="🔴 Point System")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            await send_simple_log(interaction.client, f"💰 **ADD POINTS** | {interaction.user.name} added {amount} points to {user_id} (Total: {new_balance})")
            
        except ValueError:
            embed = discord.Embed(
                title="❌ รูปแบบไม่ถูกต้อง",
                description="กรุณากรอกจำนวน Points เป็นตัวเลข",
                color=COLOR_ERROR
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)


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
        # ใช้ cache ทำให้เร็วมาก ไม่ต้อง defer
        try:
            data = get_all_uids()
            
            if not data:
                embed = discord.Embed(
                    title="📋 รายการ UID",
                    description="ไม่มี UID ในระบบ",
                    color=COLOR_INFO
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
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
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            embed = discord.Embed(
                title="❌ เกิดข้อผิดพลาด",
                description="ไม่สามารถเชื่อมต่อฐานข้อมูลได้",
                color=COLOR_ERROR
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
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
    
    @ui.button(label="💰 เพิ่ม Points", style=discord.ButtonStyle.success, custom_id="add_points", row=3)
    async def add_points_button(self, interaction: discord.Interaction, button: ui.Button):
        """Add points to a user (Server Owner only)"""
        # ตรวจสอบว่าเป็นเจ้าของเซิร์ฟเวอร์หรือไม่
        if interaction.guild is None or interaction.user.id != interaction.guild.owner_id:
            embed = discord.Embed(
                title="❌ ไม่มีสิทธิ์",
                description="เฉพาะเจ้าของเซิร์ฟเวอร์เท่านั้นที่สามารถเพิ่ม Points ได้",
                color=COLOR_ERROR
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await interaction.response.send_modal(AddPointsModal())
    
    @ui.button(label="💳 Points ของฉัน", style=discord.ButtonStyle.success, custom_id="my_points", row=3)
    async def my_points_button(self, interaction: discord.Interaction, button: ui.Button):
        """Show user's points balance"""
        if not POINTS_ENABLED:
            embed = discord.Embed(
                title="⚠️ ระบบ Points ไม่เปิดใช้งาน",
                description="ระบบ Points ไม่ได้เปิดใช้งาน",
                color=COLOR_WARNING
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        user_id = str(interaction.user.id)
        points = get_user_points(user_id)
        days_available = points // POINTS_PER_DAY
        
        embed = discord.Embed(
            title="💳 Points ของคุณ",
            description=f"คุณมี **{points}** points",
            color=COLOR_PRIMARY
        )
        embed.add_field(name="💰 อัตราแลก", value=f"`{POINTS_PER_DAY}` points = 1 วัน", inline=True)
        embed.add_field(name="📅 เพิ่มได้", value=f"`{days_available}` วัน", inline=True)
        embed.set_footer(text="🔴 Point System")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @ui.button(label="🔄 Sync ข้อมูล", style=discord.ButtonStyle.secondary, custom_id="force_sync", row=3)
    async def force_sync_button(self, interaction: discord.Interaction, button: ui.Button):
        """Force sync data from JSONBin to refresh cache"""
        if interaction.user.id != DEV_ID:
            embed = discord.Embed(
                title="❌ ไม่มีสิทธิ์",
                description="เฉพาะเจ้าของบอทเท่านั้นที่สามารถ Sync ข้อมูลได้",
                color=COLOR_ERROR
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Defer because this calls JSONBin
        await interaction.response.defer(ephemeral=True)
        
        success = load_cache_from_jsonbin()
        
        if success:
            embed = discord.Embed(
                title="✅ Sync สำเร็จ",
                description=f"โหลดข้อมูล {len(WHITELIST_CACHE)} รายการจาก JSONBin",
                color=COLOR_SUCCESS
            )
        else:
            embed = discord.Embed(
                title="❌ Sync ล้มเหลว",
                description="ไม่สามารถเชื่อมต่อ JSONBin ได้",
                color=COLOR_ERROR
            )
        embed.set_footer(text="🔴 Whitelist System")
        await interaction.followup.send(embed=embed, ephemeral=True)


# ============================
# BOT CLASS
# ============================
class MyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def on_ready(self):
        print(f"[READY] Logged in as {self.user}")
        
        # Load cache from JSONBin at startup
        print("[STARTUP] Loading cache from JSONBin...")
        load_cache_from_jsonbin()
        
        # Load points from storage (if enabled)
        if POINTS_ENABLED:
            print("[STARTUP] Loading points from storage...")
            load_points_from_storage()
        else:
            print("[STARTUP] Points system is disabled (POINTS_URL not set)")
        
        # Register persistent view
        self.add_view(MainMenuView())
        
        try:
            cmds = await self.tree.sync()
            print(f"Synced {len(cmds)} commands.")
            await send_simple_log(self, "🟢 **Bot Started Successfully**")
        except Exception as e:
            print(f"Error syncing commands: {e}")

    async def setup_hook(self):
        print("[SETUP] Bot is starting up...")

bot = MyBot()

# ============================
# /menu COMMAND
# ============================
@bot.tree.command(name="menu", description="แสดงเมนูหลัก Whitelist System")
async def menu_cmd(interaction: discord.Interaction):
    if ALLOWED_CHANNEL and interaction.channel_id != ALLOWED_CHANNEL:
        await interaction.response.send_message(
            "❌ ไม่สามารถใช้คำสั่งในช่องนี้ได้",
            ephemeral=True
        )
        return
    
    embed = discord.Embed(
        title="🔴 WHITELIST SYSTEM",
        description=(
            "ยินดีต้อนรับสู่ระบบ Whitelist\n"
            "กรุณาเลือกฟังก์ชันที่ต้องการจากปุ่มด้านล่าง\n\n"
            "🔍 **ตรวจสอบ UID** - ค้นหาข้อมูล UID\n"
            "📋 **ดู UID ทั้งหมด** - แสดงรายการ UID ทั้งหมด\n"
            "➕ **เพิ่ม UID** - เพิ่ม UID (หัก Points)\n"
            "🔄 **เปลี่ยน UID** - เปลี่ยน UID เก่าเป็น UID ใหม่\n"
            "🗑️ **ลบ UID** - ลบ UID ออกจากระบบ\n"
            "⏸️ **หยุดระบบ** - หยุดระบบชั่วคราว (Owner)\n"
            "▶️ **เปิดระบบ** - เปิดระบบอีกครั้ง (Owner)\n"
            "💰 **เพิ่ม Points** - เพิ่ม Points ให้ User (Server Owner)
\n"
            "💳 **Points ของฉัน** - ดู Points คงเหลือ\n"
            "🔄 **Sync ข้อมูล** - โหลดข้อมูลใหม่ (Owner)\n\n"
            f"**อัตราแลก:** `{POINTS_PER_DAY}` points = 1 วัน"
        ),
        color=COLOR_PRIMARY
    )
    embed.set_footer(text="🔴 Whitelist System | Point-Based")
    
    await interaction.response.send_message(embed=embed, view=MainMenuView())


# ============================
# /addpoint COMMAND (Owner only)
# ============================
@bot.tree.command(name="addpoint", description="เพิ่ม points ให้ผู้ใช้ (Owner เท่านั้น)")
@app_commands.describe(
    user="ผู้ใช้ที่ต้องการเพิ่ม points",
    amount="จำนวน points ที่ต้องการเพิ่ม"
)
async def addpoint_cmd(interaction: discord.Interaction, user: discord.User, amount: int):
    if not POINTS_ENABLED:
        embed = discord.Embed(
            title="⚠️ ระบบ Points ไม่เปิดใช้งาน",
            description="กรุณาตั้งค่า POINTS_URL ใน .env",
            color=COLOR_WARNING
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    if interaction.user.id != DEV_ID:
        embed = discord.Embed(
            title="❌ ไม่มีสิทธิ์",
            description="เฉพาะเจ้าของบอทเท่านั้นที่สามารถเพิ่ม points ได้",
            color=COLOR_ERROR
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    if amount <= 0:
        embed = discord.Embed(
            title="❌ จำนวนไม่ถูกต้อง",
            description="กรุณาระบุจำนวน points มากกว่า 0",
            color=COLOR_ERROR
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    new_balance = add_user_points(str(user.id), amount)
    
    embed = discord.Embed(
        title="✅ เพิ่ม Points สำเร็จ",
        description=f"เพิ่ม **{amount}** points ให้ {user.mention}",
        color=COLOR_SUCCESS
    )
    embed.add_field(name="👤 ผู้ใช้", value=f"`{user.name}` ({user.id})", inline=True)
    embed.add_field(name="💰 เพิ่ม", value=f"`+{amount}` points", inline=True)
    embed.add_field(name="💳 คงเหลือ", value=f"`{new_balance}` points", inline=True)
    embed.set_footer(text="🔴 Point System")
    
    await interaction.response.send_message(embed=embed)
    await send_simple_log(bot, f"💰 **ADD POINTS** | {interaction.user.name} added {amount} points to {user.name} (Total: {new_balance})")

# ============================
# /mypoints COMMAND
# ============================
@bot.tree.command(name="mypoints", description="ดู points ของตัวเอง")
async def mypoints_cmd(interaction: discord.Interaction):
    if not POINTS_ENABLED:
        embed = discord.Embed(
            title="⚠️ ระบบ Points ไม่เปิดใช้งาน",
            description="กรุณาตั้งค่า POINTS_URL ใน .env",
            color=COLOR_WARNING
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    user_id = str(interaction.user.id)
    points = get_user_points(user_id)
    
    embed = discord.Embed(
        title="💳 Points ของคุณ",
        description=f"คุณมี **{points}** points",
        color=COLOR_PRIMARY
    )
    embed.add_field(name="💰 อัตราแลก", value=f"`{POINTS_PER_DAY}` points = 1 วัน", inline=True)
    
    # คำนวณว่าเพิ่มได้กี่วัน
    days_available = points // POINTS_PER_DAY
    embed.add_field(name="📅 เพิ่มได้", value=f"`{days_available}` วัน", inline=True)
    embed.set_footer(text="🔴 Point System")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ============================
# /checkpoints COMMAND (Owner only)
# ============================
@bot.tree.command(name="checkpoints", description="ดู points ของผู้ใช้อื่น (Owner เท่านั้น)")
@app_commands.describe(user="ผู้ใช้ที่ต้องการตรวจสอบ")
async def checkpoints_cmd(interaction: discord.Interaction, user: discord.User):
    if not POINTS_ENABLED:
        embed = discord.Embed(
            title="⚠️ ระบบ Points ไม่เปิดใช้งาน",
            description="กรุณาตั้งค่า POINTS_URL ใน .env",
            color=COLOR_WARNING
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    if interaction.user.id != DEV_ID:
        embed = discord.Embed(
            title="❌ ไม่มีสิทธิ์",
            description="เฉพาะเจ้าของบอทเท่านั้นที่สามารถดู points ของผู้อื่นได้",
            color=COLOR_ERROR
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    user_id = str(user.id)
    points = get_user_points(user_id)
    days_available = points // POINTS_PER_DAY
    
    embed = discord.Embed(
        title="💳 ข้อมูล Points",
        color=COLOR_PRIMARY
    )
    embed.add_field(name="👤 ผู้ใช้", value=f"`{user.name}` ({user.id})", inline=False)
    embed.add_field(name="💰 Points", value=f"`{points}` points", inline=True)
    embed.add_field(name="📅 เพิ่มได้", value=f"`{days_available}` วัน", inline=True)
    embed.set_footer(text="🔴 Point System")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ============================
# RUN BOT
# ============================
if __name__ == "__main__":
    bot.run(BOT_TOKEN)
