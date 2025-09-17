import os
import math
import asyncio
import aiosqlite
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

import discord
from discord.ext import commands, tasks
from discord import app_commands

# ===================== CONFIG =====================
TOKEN = os.getenv("DISCORD_TOKEN")
DB_PATH = os.getenv("DB_PATH", "data.sqlite3")
CHECK_INTERVAL_SEC = int(os.getenv("CHECK_INTERVAL_SEC", "30"))
DEFAULT_TZ = os.getenv("DEFAULT_TZ", "UTC")

EPHEMERAL = True  # dashboard responses private to user

intents = discord.Intents.default()
intents.message_content = False
bot = commands.Bot(command_prefix="!", intents=intents)

def now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)

def eta_str(ms: int) -> str:
    if ms <= 0:
        return "0m"
    s = ms // 1000
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, _ = divmod(s, 60)
    parts=[]
    if d: parts.append(f"{d}d")
    if h or d: parts.append(f"{h}h")
    parts.append(f"{m}m")
    return " ".join(parts)

# ===================== MINION DATA =====================
# TBA (seconds for one action) per tier pattern
T12_FAST  = [14,14,12,12,10,10,9,9,8,8,7,6]
T12_MID   = [17,17,15,15,13,13,12,12,10,10,9,8]
T12_SLOW  = [29,29,27,27,25,25,23,23,21,21,19,19]
INTERNALS = [64,192,192,384,384,576,576,768,768,960,960,960]  # items held internally

def tiers_from(speeds: List[int]) -> Dict[int, Dict[str, int]]:
    return {i+1: {"tba": speeds[i], "internal": INTERNALS[i]} for i in range(12)}

@dataclass
class Drop:
    id: str
    per_product: float   # expected amount if drop happens
    prob: float          # chance per product (0..1)
    stack: int = 64      # stack size

DEFAULT_AP = 2  # actions per product (2 actions -> 1 product)

# --- Minions: include major categories & multi-drops ---
MINION_DATA: Dict[str, Dict[str, Any]] = {
    # Mining
    "cobblestone": {"name":"Cobblestone","category":"mining","tiers":tiers_from(T12_FAST),"actions_per_product":DEFAULT_AP,"drops":[Drop("cobblestone",1,1.0)]},
    "coal":        {"name":"Coal","category":"mining","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,"drops":[Drop("coal",1,1.0)]},
    "iron":        {"name":"Iron","category":"mining","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,"drops":[Drop("iron_ore",1,1.0)]},
    "gold":        {"name":"Gold","category":"mining","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,"drops":[Drop("gold_ore",1,1.0)]},
    "diamond":     {"name":"Diamond","category":"mining","tiers":tiers_from(T12_FAST),"actions_per_product":DEFAULT_AP,"drops":[Drop("diamond",1,1.0)]},
    "lapis":       {"name":"Lapis","category":"mining","tiers":tiers_from(T12_SLOW),"actions_per_product":DEFAULT_AP,"drops":[Drop("lapis_lazuli",4,1.0)]},
    "redstone":    {"name":"Redstone","category":"mining","tiers":tiers_from(T12_SLOW),"actions_per_product":DEFAULT_AP,"drops":[Drop("redstone",4,1.0)]},
    "emerald":     {"name":"Emerald","category":"mining","tiers":tiers_from(T12_SLOW),"actions_per_product":DEFAULT_AP,"drops":[Drop("emerald",1,1.0)]},
    "quartz":      {"name":"Quartz","category":"mining","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,"drops":[Drop("quartz",1,1.0)]},
    "glowstone":   {"name":"Glowstone","category":"mining","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,"drops":[Drop("glowstone_dust",3,1.0)]},
    "obsidian":    {"name":"Obsidian","category":"mining","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,"drops":[Drop("obsidian",1,1.0)]},
    "end_stone":   {"name":"End Stone","category":"mining","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,"drops":[Drop("end_stone",1,1.0)]},
    "mithril":     {"name":"Mithril","category":"mining","tiers":tiers_from(T12_SLOW),"actions_per_product":DEFAULT_AP,"drops":[Drop("mithril",1,1.0)]},

    # Foraging
    "oak":       {"name":"Oak","category":"foraging","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,"drops":[Drop("oak_wood",1,1.0)]},
    "spruce":    {"name":"Spruce","category":"foraging","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,"drops":[Drop("spruce_wood",1,1.0)]},
    "birch":     {"name":"Birch","category":"foraging","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,"drops":[Drop("birch_wood",1,1.0)]},
    "jungle":    {"name":"Jungle","category":"foraging","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,"drops":[Drop("jungle_wood",1,1.0)]},
    "acacia":    {"name":"Acacia","category":"foraging","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,"drops":[Drop("acacia_wood",1,1.0)]},
    "dark_oak":  {"name":"Dark Oak","category":"foraging","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,"drops":[Drop("dark_oak_wood",1,1.0)]},

    # Farming
    "wheat":       {"name":"Wheat","category":"farming","tiers":tiers_from(T12_FAST),"actions_per_product":DEFAULT_AP,"drops":[Drop("wheat",1,1.0),Drop("seeds",1,1.0)]},
    "carrot":      {"name":"Carrot","category":"farming","tiers":tiers_from(T12_FAST),"actions_per_product":DEFAULT_AP,"drops":[Drop("carrot",2,1.0)]},
    "potato":      {"name":"Potato","category":"farming","tiers":tiers_from(T12_FAST),"actions_per_product":DEFAULT_AP,"drops":[Drop("potato",2,1.0)]},
    "pumpkin":     {"name":"Pumpkin","category":"farming","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,"drops":[Drop("pumpkin",1,1.0)]},
    "melon":       {"name":"Melon","category":"farming","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,"drops":[Drop("melon",4,1.0)]},
    "sugar_cane":  {"name":"Sugar Cane","category":"farming","tiers":tiers_from(T12_FAST),"actions_per_product":DEFAULT_AP,"drops":[Drop("sugar_cane",2,1.0)]},
    "cactus":      {"name":"Cactus","category":"farming","tiers":tiers_from(T12_FAST),"actions_per_product":DEFAULT_AP,"drops":[Drop("cactus",1,1.0)]},
    "cocoa":       {"name":"Cocoa","category":"farming","tiers":tiers_from(T12_FAST),"actions_per_product":DEFAULT_AP,"drops":[Drop("cocoa_beans",2,1.0)]},
    "mushroom":    {"name":"Mushroom","category":"farming","tiers":tiers_from(T12_FAST),"actions_per_product":DEFAULT_AP,"drops":[Drop("mushroom",1,1.0)]},
    "nether_wart": {"name":"Nether Wart","category":"farming","tiers":tiers_from(T12_FAST),"actions_per_product":DEFAULT_AP,"drops":[Drop("nether_wart",2,1.0)]},

    # Combat (multi-drops)
    "zombie": {
        "name":"Zombie","category":"combat","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,
        "drops":[Drop("rotten_flesh",1,1.0), Drop("carrot",1,0.02), Drop("potato",1,0.02)]
    },
    "skeleton": {
        "name":"Skeleton","category":"combat","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,
        "drops":[Drop("bone",1,1.0), Drop("arrow",1,1.0)]
    },
    "spider": {
        "name":"Spider","category":"combat","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,
        "drops":[Drop("string",1,1.0), Drop("spider_eye",1,0.5)]
    },
    "cave_spider": {
        "name":"Cave Spider","category":"combat","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,
        "drops":[Drop("string",1,1.0), Drop("spider_eye",1,0.8)]
    },
    "enderman": {
        "name":"Enderman","category":"combat","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,
        "drops":[Drop("ender_pearl",1,0.6)]
    },
    "slime": {
        "name":"Slime","category":"combat","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,
        "drops":[Drop("slimeball",2,1.0)]
    },
    "magma_cube": {
        "name":"Magma Cube","category":"combat","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,
        "drops":[Drop("magma_cream",1,1.0)]
    },
    "blaze": {
        "name":"Blaze","category":"combat","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,
        "drops":[Drop("blaze_rod",1,0.9)]
    },
    "ghast": {
        "name":"Ghast","category":"combat","tiers":tiers_from(T12_SLOW),"actions_per_product":DEFAULT_AP,
        "drops":[Drop("gunpowder",1,1.0), Drop("ghast_tear",1,0.05)]
    },
    "cow": {
        "name":"Cow","category":"combat","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,
        "drops":[Drop("raw_beef",1,1.0), Drop("leather",1,0.7)]
    },
    "chicken": {
        "name":"Chicken","category":"combat","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,
        "drops":[Drop("raw_chicken",1,1.0), Drop("feather",1,1.0)]
    },

    # Fishing-like
    "clay": {"name":"Clay","category":"fishing","tiers":tiers_from(T12_MID),"actions_per_product":DEFAULT_AP,"drops":[Drop("clay_ball",1,1.0)]},
    "fishing": {"name":"Fishing (generic)","category":"fishing","tiers":tiers_from(T12_SLOW),"actions_per_product":DEFAULT_AP,"drops":[Drop("fish",1,0.8),Drop("salmon",1,0.2),Drop("treasure",1,0.02)]},
}

STORAGE_BONUS = {"none":0,"small":192,"medium":576,"large":960}

FUEL_CHOICES = {
    "1.00":1.00,"1.05":1.05,"1.10":1.10,"1.20":1.20,"1.25":1.25,"1.35":1.35,"1.90":1.90,"3.00":3.00,"4.00":4.00
}

def speed_multiplier(fuel: float, expander: bool, flycatchers: int, crystal: bool) -> float:
    m = fuel
    if expander: m *= 1.05
    if flycatchers > 0: m *= (1.10 ** min(flycatchers, 2))
    if crystal: m *= 1.10
    return m

def production_slots_per_hour(
    minion_key: str, tier: int, fuel_mult: float, expander: bool, flycatchers: int,
    crystal: bool, diamond_spreading: bool, super_compactor: bool
) -> float:
    data = MINION_DATA[minion_key]
    tba = data["tiers"][tier]["tba"]
    ap = data.get("actions_per_product", DEFAULT_AP)

    mult = speed_multiplier(fuel_mult, expander, flycatchers, crystal)
    actions_per_sec = mult / tba
    products_per_sec = actions_per_sec / ap
    products_per_hour = products_per_sec * 3600.0

    drops: List[Drop] = list(data["drops"])
    if diamond_spreading:
        drops.append(Drop("diamond", 1.0, 0.10, 64))

    comp_div = 160 if super_compactor else 1
    slots_per_hour = 0.0
    for d in drops:
        items_per_hour = products_per_hour * (d.per_product * d.prob)
        slots = items_per_hour / (d.stack * comp_div)
        slots_per_hour += slots
    return slots_per_hour

def capacity_slots(minion_key: str, tier: int, storage_key: str) -> float:
    internal = MINION_DATA[minion_key]["tiers"][tier]["internal"]
    extra = STORAGE_BONUS.get(storage_key, 0)
    return (internal + extra) / 64.0

def due_time_ms(
    minion_key: str, tier: int, fuel_mult: float, expander: bool, flycatchers: int,
    crystal: bool, diamond_spreading: bool, super_compactor: bool, storage_key: str, start_ms_val: int
) -> Tuple[int, float, float]:
    sph = production_slots_per_hour(
        minion_key, tier, fuel_mult, expander, flycatchers, crystal, diamond_spreading, super_compactor
    )
    cap_slots = capacity_slots(minion_key, tier, storage_key)
    if sph <= 0: return start_ms_val, 0.0, sph
    hours = cap_slots / sph
    return int(start_ms_val + hours * 3600_000), hours, sph

# ===================== DATABASE LAYER =====================
CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY,
  timezone TEXT NOT NULL DEFAULT 'UTC',
  default_notify TEXT NOT NULL DEFAULT 'dm'
);
"""
CREATE_TIMERS = """
CREATE TABLE IF NOT EXISTS timers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  guild_id TEXT,
  channel_id TEXT,
  minion_key TEXT NOT NULL,
  tier INTEGER NOT NULL,
  storage_key TEXT NOT NULL,
  fuel_key TEXT NOT NULL,
  expander INTEGER NOT NULL DEFAULT 0,
  flycatchers INTEGER NOT NULL DEFAULT 0,
  crystal INTEGER NOT NULL DEFAULT 0,
  diamond_spreading INTEGER NOT NULL DEFAULT 0,
  super_compactor INTEGER NOT NULL DEFAULT 0,
  nickname TEXT,
  start_ms INTEGER NOT NULL,
  due_ms INTEGER NOT NULL,
  notified INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
"""

class DB:
    def __init__(self, path: str):
        self.path = path
        self.conn: Optional[aiosqlite.Connection] = None

    async def init(self):
        self.conn = await aiosqlite.connect(self.path)
        await self.conn.execute(CREATE_USERS)
        await self.conn.execute(CREATE_TIMERS)
        await self.conn.commit()

    async def get_user(self, user_id: int) -> Dict[str, Any]:
        async with self.conn.execute("SELECT timezone, default_notify FROM users WHERE user_id=?", (str(user_id),)) as cur:
            row = await cur.fetchone()
        if row:
            return {"timezone": row[0], "default_notify": row[1]}
        await self.conn.execute("INSERT INTO users (user_id, timezone, default_notify) VALUES (?, ?, ?)", (str(user_id), DEFAULT_TZ, "dm"))
        await self.conn.commit()
        return {"timezone": DEFAULT_TZ, "default_notify": "dm"}

    async def set_user(self, user_id: int, tz: str, notify: str):
        await self.conn.execute(
            "INSERT INTO users (user_id, timezone, default_notify) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET timezone=excluded.timezone, default_notify=excluded.default_notify",
            (str(user_id), tz, notify)
        )
        await self.conn.commit()

    async def add_timer(self, t: Dict[str, Any]) -> int:
        now = now_ms()
        await self.conn.execute(
            """INSERT INTO timers
            (user_id, guild_id, channel_id, minion_key, tier, storage_key, fuel_key,
             expander, flycatchers, crystal, diamond_spreading, super_compactor,
             nickname, start_ms, due_ms, notified, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
            (
                str(t["user_id"]), t.get("guild_id"), t.get("channel_id"),
                t["minion_key"], t["tier"], t["storage_key"], t["fuel_key"],
                int(t["expander"]), int(t["flycatchers"]), int(t["crystal"]),
                int(t["diamond_spreading"]), int(t["super_compactor"]),
                t.get("nickname"), t["start_ms"], t["due_ms"], now, now
            )
        )
        await self.conn.commit()
        async with self.conn.execute("SELECT last_insert_rowid()") as cur:
            rid = await cur.fetchone()
        return int(rid[0])

    async def list_timers(self, user_id: int) -> List[Dict[str, Any]]:
        async with self.conn.execute(
            "SELECT id, minion_key, tier, storage_key, fuel_key, expander, flycatchers, crystal, diamond_spreading, super_compactor, nickname, start_ms, due_ms, notified, channel_id, guild_id "
            "FROM timers WHERE user_id=? ORDER BY due_ms ASC",
            (str(user_id),)
        ) as cur:
            rows = await cur.fetchall()
        out=[]
        for r in rows:
            out.append({
                "id": r[0], "minion_key": r[1], "tier": r[2], "storage_key": r[3], "fuel_key": r[4],
                "expander": bool(r[5]), "flycatchers": int(r[6]), "crystal": bool(r[7]),
                "diamond_spreading": bool(r[8]), "super_compactor": bool(r[9]),
                "nickname": r[10], "start_ms": r[11], "due_ms": r[12], "notified": bool(r[13]),
                "channel_id": r[14], "guild_id": r[15]
            })
        return out

    async def get_timer(self, user_id: int, timer_id: int) -> Optional[Dict[str, Any]]:
        async with self.conn.execute(
            "SELECT id, minion_key, tier, storage_key, fuel_key, expander, flycatchers, crystal, diamond_spreading, super_compactor, nickname, start_ms, due_ms, notified, channel_id, guild_id "
            "FROM timers WHERE user_id=? AND id=?",
            (str(user_id), timer_id)
        ) as cur:
            r = await cur.fetchone()
        if not r:
            return None
        return {
            "id": r[0], "minion_key": r[1], "tier": r[2], "storage_key": r[3], "fuel_key": r[4],
            "expander": bool(r[5]), "flycatchers": int(r[6]), "crystal": bool(r[7]),
            "diamond_spreading": bool(r[8]), "super_compactor": bool(r[9]),
            "nickname": r[10], "start_ms": r[11], "due_ms": r[12], "notified": bool(r[13]),
            "channel_id": r[14], "guild_id": r[15]
        }

    async def update_timer(self, user_id: int, timer_id: int, updates: Dict[str, Any]):
        sets=[]; vals=[]
        for k,v in updates.items():
            sets.append(f"{k}=?"); vals.append(v)
        sets.append("updated_at=?"); vals.append(now_ms())
        vals.extend([str(user_id), timer_id])
        await self.conn.execute(f"UPDATE timers SET {', '.join(sets)} WHERE user_id=? AND id=?", tuple(vals))
        await self.conn.commit()

    async def delete_timer(self, user_id: int, timer_id: int):
        await self.conn.execute("DELETE FROM timers WHERE user_id=? AND id=?", (str(user_id), timer_id))
        await self.conn.commit()

    async def due_unnotified(self, ts_ms: int) -> List[Dict[str, Any]]:
        async with self.conn.execute(
            "SELECT id, user_id, minion_key, tier, storage_key, fuel_key, expander, flycatchers, crystal, diamond_spreading, super_compactor, nickname, start_ms, due_ms, channel_id, guild_id "
            "FROM timers WHERE due_ms<=? AND notified=0",
            (ts_ms,)
        ) as cur:
            rows = await cur.fetchall()
        out=[]
        for r in rows:
            out.append({
                "id": r[0], "user_id": int(r[1]), "minion_key": r[2], "tier": r[3], "storage_key": r[4],
                "fuel_key": r[5], "expander": bool(r[6]), "flycatchers": int(r[7]), "crystal": bool(r[8]),
                "diamond_spreading": bool(r[9]), "super_compactor": bool(r[10]),
                "nickname": r[11], "start_ms": r[12], "due_ms": r[13],
                "channel_id": r[14], "guild_id": r[15]
            })
        return out

    async def mark_notified(self, timer_id: int):
        await self.conn.execute("UPDATE timers SET notified=1, updated_at=? WHERE id=?", (now_ms(), timer_id))
        await self.conn.commit()

db = DB(DB_PATH)

# ===================== UI HELPERS =====================
def timer_row_line(t: Dict[str, Any]) -> str:
    name = MINION_DATA[t["minion_key"]]["name"]
    due = t["due_ms"]
    rel = f"<t:{due//1000}:R>"
    due_abs = f"<t:{due//1000}:F>"
    fuel = t["fuel_key"]
    comp = "Super" if t["super_compactor"] else "None"
    fx_bits = []
    if t["expander"]: fx_bits.append("Exp")
    if t["flycatchers"]>0: fx_bits.append(f"Fly×{t['flycatchers']}")
    if t["crystal"]: fx_bits.append("Cry")
    if t["diamond_spreading"]: fx_bits.append("DS")
    fx = f" [{', '.join(fx_bits)}]" if fx_bits else ""
    nick = f" — {t['nickname']}" if t["nickname"] else ""
    return f"• **{name} T{t['tier']}**{nick}\n   Storage: *{t['storage_key']}*, Fuel **x{fuel}**, Compactor: **{comp}**{fx}\n   Due: {rel} • {due_abs}"

def dashboard_embed(user: discord.User | discord.Member, timers: List[Dict[str, Any]]) -> discord.Embed:
    e = discord.Embed(title=f"{user.display_name}'s Minion Timers", colour=discord.Colour.blurple())
    if not timers:
        e.description = "You have no active timers.\nUse **➕ Create** to add one."
        return e
    e.description = "\n\n".join(timer_row_line(t) for t in timers)
    return e

class DashboardView(discord.ui.View):
    def __init__(self, owner_id: int, timers: List[Dict[str, Any]]):
        super().__init__(timeout=180)
        self.owner_id = owner_id
        # Global buttons
        self.add_item(discord.ui.Button(label="➕ Create", style=discord.ButtonStyle.primary, custom_id="create"))
        self.add_item(discord.ui.Button(label="⚙️ Settings", style=discord.ButtonStyle.secondary, custom_id="settings"))
        self.add_item(discord.ui.Button(label="🔄 Refresh", style=discord.ButtonStyle.secondary, custom_id="refresh"))
        # Timer selector
        if timers:
            opts = [discord.SelectOption(label=f"#{t['id']} {MINION_DATA[t['minion_key']]['name']} T{t['tier']}", value=str(t["id"])) for t in timers]
            sel = discord.ui.Select(placeholder="Manage a timer (Edit/Restart/Delete)", options=opts, min_values=1, max_values=1, custom_id="pick_timer")
            self.add_item(sel)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.owner_id

# ===================== MODALS (NO add_item CALLS) =====================
class CreateTimerModal(discord.ui.Modal, title="Create Minion Timer"):
    def __init__(self, user_id: int, default_notify: str):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.minion_key = discord.ui.TextInput(label="Minion key", placeholder="e.g. cobblestone, skeleton", required=True, max_length=32)
        self.tier = discord.ui.TextInput(label="Tier (1-12)", default="11", required=True, max_length=2)
        self.storage = discord.ui.TextInput(label="Storage (none/small/medium/large)", default="medium", required=True, max_length=10)
        self.fuel = discord.ui.TextInput(label="Fuel (1.00,1.25,1.90,3.00,4.00)", default="1.00", required=True, max_length=4)
        self.super_compactor = discord.ui.TextInput(label="Super Compactor? (yes/no)", default="no", required=True, max_length=3)
        self.expander = discord.ui.TextInput(label="Minion Expander? (yes/no)", default="no", required=True, max_length=3)
        self.flycatchers = discord.ui.TextInput(label="Flycatchers (0-2)", default="0", required=True, max_length=1)
        self.crystal = discord.ui.TextInput(label="Crystal bonus? (yes/no)", default="no", required=True, max_length=3)
        self.diamond_spreading = discord.ui.TextInput(label="Diamond Spreading? (yes/no)", default="no", required=True, max_length=3)
        self.nickname = discord.ui.TextInput(label="Nickname (optional)", required=False, max_length=30)
        self.notify = discord.ui.TextInput(label="Notify (dm/here)", default=default_notify, required=True, max_length=4)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            mkey = self.minion_key.value.strip().lower()
            if mkey not in MINION_DATA: raise ValueError("Unknown minion key.")
            tier = int(self.tier.value.strip())
            if not 1 <= tier <= 12: raise ValueError("Tier 1..12.")
            storage = self.storage.value.strip().lower()
            if storage not in STORAGE_BONUS: raise ValueError("Invalid storage.")
            fuel_key = f"{float(self.fuel.value.strip()):.2f}"
            if fuel_key not in FUEL_CHOICES: raise ValueError("Invalid fuel.")
            sc = self.super_compactor.value.strip().lower() in ("y","yes","true","1")
            exp = self.expander.value.strip().lower() in ("y","yes","true","1")
            fc = max(0, min(2, int(self.flycatchers.value.strip())))
            cry = self.crystal.value.strip().lower() in ("y","yes","true","1")
            ds = self.diamond_spreading.value.strip().lower() in ("y","yes","true","1")
            nick = (self.nickname.value or "").strip()
            notify = self.notify.value.strip().lower()
            if notify not in ("dm","here"): notify = "dm"

            start = now_ms()
            fuel_mult = FUEL_CHOICES[fuel_key]
            due_ms_val, hours, _ = due_time_ms(
                mkey, tier, fuel_mult, exp, fc, cry, ds, sc, storage, start
            )

            channel_id = interaction.channel_id if notify == "here" else None
            tid = await db.add_timer({
                "user_id": interaction.user.id, "guild_id": interaction.guild_id, "channel_id": channel_id,
                "minion_key": mkey, "tier": tier, "storage_key": storage, "fuel_key": fuel_key,
                "expander": exp, "flycatchers": fc, "crystal": cry, "diamond_spreading": ds,
                "super_compactor": sc, "nickname": nick, "start_ms": start, "due_ms": due_ms_val
            })

            await interaction.response.send_message(
                f"✅ Created timer **#{tid}** for **{MINION_DATA[mkey]['name']} T{tier}** • Due **<t:{due_ms_val//1000}:F>** ({eta_str(due_ms_val-start)})",
                ephemeral=EPHEMERAL
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=EPHEMERAL)

class EditTimerModal(discord.ui.Modal, title="Edit Minion Timer"):
    def __init__(self, timer_id: int, preset: Dict[str, Any]):
        super().__init__(timeout=300)
        self.timer_id = timer_id
        self.minion_key = discord.ui.TextInput(label="Minion key", default=preset["minion_key"], max_length=32)
        self.tier = discord.ui.TextInput(label="Tier (1-12)", default=str(preset["tier"]), max_length=2)
        self.storage = discord.ui.TextInput(label="Storage (none/small/medium/large)", default=preset["storage_key"], max_length=10)
        self.fuel = discord.ui.TextInput(label="Fuel (1.00..4.00)", default=preset["fuel_key"], max_length=4)
        self.super_compactor = discord.ui.TextInput(label="Super Compactor? (yes/no)", default=("yes" if preset["super_compactor"] else "no"), max_length=3)
        self.expander = discord.ui.TextInput(label="Minion Expander? (yes/no)", default=("yes" if preset["expander"] else "no"), max_length=3)
        self.flycatchers = discord.ui.TextInput(label="Flycatchers (0-2)", default=str(preset["flycatchers"]), max_length=1)
        self.crystal = discord.ui.TextInput(label="Crystal? (yes/no)", default=("yes" if preset["crystal"] else "no"), max_length=3)
        self.diamond_spreading = discord.ui.TextInput(label="Diamond Spreading? (yes/no)", default=("yes" if preset["diamond_spreading"] else "no"), max_length=3)
        self.nickname = discord.ui.TextInput(label="Nickname (optional)", default=(preset["nickname"] or ""), required=False, max_length=30)

    async def on_submit(self, interaction: discord.Interaction):
        t = await db.get_timer(interaction.user.id, self.timer_id)
        if not t:
            await interaction.response.send_message("❌ Timer not found.", ephemeral=EPHEMERAL); return
        try:
            mkey = self.minion_key.value.strip().lower()
            if mkey not in MINION_DATA: raise ValueError("Unknown minion.")
            tier = int(self.tier.value.strip())
            if not 1 <= tier <= 12: raise ValueError("Tier 1..12.")
            storage = self.storage.value.strip().lower()
            if storage not in STORAGE_BONUS: raise ValueError("Invalid storage.")
            fuel_key = f"{float(self.fuel.value.strip()):.2f}"
            if fuel_key not in FUEL_CHOICES: raise ValueError("Invalid fuel.")
            sc = self.super_compactor.value.strip().lower() in ("y","yes","true","1")
            exp = self.expander.value.strip().lower() in ("y","yes","true","1")
            fc = max(0, min(2, int(self.flycatchers.value.strip())))
            cry = self.crystal.value.strip().lower() in ("y","yes","true","1")
            ds = self.diamond_spreading.value.strip().lower() in ("y","yes","true","1")
            nick = (self.nickname.value or "").strip()

            due_ms_val, _, _ = due_time_ms(
                mkey, tier, FUEL_CHOICES[fuel_key], exp, fc, cry, ds, sc, storage, t["start_ms"]
            )
            await db.update_timer(interaction.user.id, self.timer_id, {
                "minion_key": mkey, "tier": tier, "storage_key": storage, "fuel_key": fuel_key,
                "expander": int(exp), "flycatchers": int(fc), "crystal": int(cry),
                "diamond_spreading": int(ds), "super_compactor": int(sc),
                "nickname": nick, "due_ms": due_ms_val, "notified": 0
            })
            await interaction.response.send_message(
                f"✅ Updated **#{self.timer_id}** • New due **<t:{due_ms_val//1000}:F>** ({eta_str(due_ms_val-now_ms())})",
                ephemeral=EPHEMERAL
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=EPHEMERAL)

class SettingsModal(discord.ui.Modal, title="Settings"):
    def __init__(self, user_id: int, tz_def: str, notify_def: str):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.tz = discord.ui.TextInput(label="Timezone (IANA)", default=tz_def)
        self.notify = discord.ui.TextInput(label="Default notify (dm/here)", default=notify_def)

    async def on_submit(self, interaction: discord.Interaction):
        tzv = self.tz.value.strip()
        nv = self.notify.value.strip().lower()
        if nv not in ("dm","here"): nv = "dm"
        await db.set_user(interaction.user.id, tzv, nv)
        await interaction.response.send_message("✅ Settings saved.", ephemeral=EPHEMERAL)

# ===================== COMMANDS & HANDLERS =====================
@bot.event
async def on_ready():
    await db.init()
    watcher.start()
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} commands")
    except Exception as e:
        print(f"Sync error: {e}")
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")

@bot.tree.command(name="setup", description="Open your personal minion dashboard")
async def setup_cmd(interaction: discord.Interaction):
    user = await db.get_user(interaction.user.id)
    timers = await db.list_timers(interaction.user.id)
    await interaction.response.send_message(embed=dashboard_embed(interaction.user, timers),
                                            view=DashboardView(interaction.user.id, timers), ephemeral=EPHEMERAL)

@bot.tree.command(name="ping", description="Ping")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 Pong!", ephemeral=True)

@bot.event
async def on_interaction(inter: discord.Interaction):
    if inter.type != discord.InteractionType.component:
        return
    cid = inter.data.get("custom_id")
    if not cid: return

    # Fetch defaults once if needed
    if cid == "create":
        u = await db.get_user(inter.user.id)
        await inter.response.send_modal(CreateTimerModal(inter.user.id, u["default_notify"]))
        return

    if cid == "settings":
        u = await db.get_user(inter.user.id)
        await inter.response.send_modal(SettingsModal(inter.user.id, u["timezone"], u["default_notify"]))
        return

    if cid == "refresh":
        timers = await db.list_timers(inter.user.id)
        await inter.response.edit_message(embed=dashboard_embed(inter.user, timers),
                                          view=DashboardView(inter.user.id, timers))
        return

    if cid == "pick_timer":
        sel = inter.data.get("values", [])
        if not sel:
            await inter.response.send_message("❌ No timer selected.", ephemeral=EPHEMERAL)
            return
        timer_id = int(sel[0])

        class ManageView(discord.ui.View):
            def __init__(self, owner_id: int, tid: int):
                super().__init__(timeout=120)
                self.owner_id = owner_id
                self.tid = tid
                self.add_item(discord.ui.Button(label="✏️ Edit", style=discord.ButtonStyle.primary, custom_id=f"edit:{tid}"))
                self.add_item(discord.ui.Button(label="🔁 Restart", style=discord.ButtonStyle.secondary, custom_id=f"restart:{tid}"))
                self.add_item(discord.ui.Button(label="🗑 Delete", style=discord.ButtonStyle.danger, custom_id=f"delete:{tid}"))

            async def interaction_check(self, i: discord.Interaction) -> bool:
                return i.user.id == self.owner_id

        await inter.response.send_message(f"Managing timer `#{timer_id}` — pick an action:", view=ManageView(inter.user.id, timer_id), ephemeral=EPHEMERAL)
        return

    if cid.startswith("edit:"):
        tid = int(cid.split(":")[1])
        t = await db.get_timer(inter.user.id, tid)
        if not t:
            await inter.response.send_message("❌ Timer not found.", ephemeral=EPHEMERAL); return
        await inter.response.send_modal(EditTimerModal(tid, t))
        return

    if cid.startswith("restart:"):
        tid = int(cid.split(":")[1])
        t = await db.get_timer(inter.user.id, tid)
        if not t:
            await inter.response.send_message("❌ Timer not found.", ephemeral=EPHEMERAL); return
        due, _, _ = due_time_ms(
            t["minion_key"], t["tier"], FUEL_CHOICES[t["fuel_key"]], t["expander"], t["flycatchers"], t["crystal"],
            t["diamond_spreading"], t["super_compactor"], t["storage_key"], now_ms()
        )
        await db.update_timer(inter.user.id, tid, {"start_ms": now_ms(), "due_ms": due, "notified": 0})
        await inter.response.send_message(f"🔁 Restarted **#{tid}** • New due **<t:{due//1000}:F>** ({eta_str(due - now_ms())})", ephemeral=EPHEMERAL)
        return

    if cid.startswith("delete:"):
        tid = int(cid.split(":")[1])
        await db.delete_timer(inter.user.id, tid)
        await inter.response.send_message(f"🗑 Deleted timer **#{tid}**.", ephemeral=EPHEMERAL)
        return

# ===================== NOTIFICATIONS =====================
@tasks.loop(seconds=CHECK_INTERVAL_SEC)
async def watcher():
    due = await db.due_unnotified(now_ms())
    for t in due:
        try:
            dest: Optional[discord.abc.Messageable] = None
            if t["channel_id"]:
                ch = bot.get_channel(int(t["channel_id"]))
                if ch: dest = ch
            if dest is None:
                u = await bot.fetch_user(int(t["user_id"]))
                dest = u
            name = MINION_DATA[t["minion_key"]]["name"]
            nick = f" — {t['nickname']}" if t["nickname"] else ""
            await dest.send(f"⏰ **Minion ready:** {name} T{t['tier']}{nick}\nDue at **<t:{t['due_ms']//1000}:F>**")
            await db.mark_notified(t["id"])
        except Exception:
            await db.mark_notified(t["id"])

# ===================== RUN =====================
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN not set")
    bot.run(TOKEN)