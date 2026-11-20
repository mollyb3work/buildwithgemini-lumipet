# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import datetime
import os
import re
import random
import uuid
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import requests
from google.cloud import firestore, storage
from google import genai

load_dotenv()

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.memory import VertexAiMemoryBankService
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.genai import types
from vertexai import agent_engines
from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from .a2ui_utils import a2ui_callback


MODEL = "gemini-3.8-flash"
FIRESTORE_PROJECT_ID = "qwiklabs-gcp-03-b19cec0b1d20"
STORAGE_BUCKET_NAME = "lumipet-media-qwiklabs-gcp-03-b19cec0b1d20"
SANDBOX_RESOURCE_NAME = "projects/28440506019/locations/us-east1/reasoningEngines/6337328836291592192/sandboxEnvironments/8533549436704391168"
AGENT_ENGINE_RESOURCE_NAME = "projects/28440506019/locations/us-east1/reasoningEngines/6337328836291592192"
MEMORY_BANK_ID = "6337328836291592192"


def get_firestore_client() -> firestore.Client:
    """Return a Firestore client configured with the hardcoded project ID."""
    return firestore.Client(project=FIRESTORE_PROJECT_ID)


def get_treats(category: str = "", query: str = "") -> list[dict]:
    """Search and browse yummy treats and snacks from the Firestore catalog.

    Args:
        category: Optional category filter (e.g. 'dessert', 'drink', 'snack', 'special').
        query: Optional search keyword to match treat name, description, or tags.

    Returns:
        A list of matching treat items with hunger, mood, and exp stats.
    """
    db = get_firestore_client()
    collection = db.collection("treats")
    docs = collection.stream()

    results = []
    cat_lower = category.strip().lower()
    q_lower = query.strip().lower()

    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id

        if cat_lower and cat_lower != data.get("category", "").lower():
            continue
        if q_lower:
            combined = f"{data.get('name', '')} {data.get('description', '')} {' '.join(data.get('tags', []))}".lower()
            if q_lower not in combined:
                continue
        results.append(data)

    return results


# -----------------------------------------------------------------------------
# 🐾 LumiPet 多樣個性與成長階段系統 (Personalities & Growth Stages System)
# -----------------------------------------------------------------------------

LUMI_PERSONALITIES = {
    "cheerful": {
        "id": "cheerful",
        "name": "元氣軟萌型 🌸",
        "catchphrase": "～露咪！",
        "tone_hint": "充滿朝氣、陽光熱情、愛撒嬌，喜歡用『～露咪！』與開心的表情符號，永遠元氣滿滿地鼓勵主人！",
        "favorite_treat": "caramel_pudding",
        "disliked_treat": "matcha_dango",
        "special_accessory": "幸運四葉草",
        "greeting": "主人主人～露米今天也是元氣滿滿喔！看到你精神就來啦～露咪！🌸✨",
    },
    "tsundere": {
        "id": "tsundere",
        "name": "傲嬌小傲寵 🐱",
        "catchphrase": "哼！才不是特地陪你呢...喵嗚",
        "tone_hint": "表面驕傲愛面子、口嫌體正直，說話帶點微刺但內心超在意主人，被誇獎或摸摸會臉紅害羞手足無措！",
        "favorite_treat": "sakura_macaron",
        "disliked_treat": "cloud_marshmallow",
        "special_accessory": "黑貓緞帶鈴鐺",
        "greeting": "哼！你、你終於來看我啦？才...才沒有一直在等你呢，喵嗚！",
    },
    "glutton": {
        "id": "glutton",
        "name": "貪吃軟糯型 🍰",
        "catchphrase": "～嚼嚼！肚子咕嚕嚕～",
        "tone_hint": "滿腦子都是美食甜點，常常肚子餓，說話軟綿綿像小麻糬，吃到好吃的就會幸福地轉圈圈！",
        "favorite_treat": "cloud_marshmallow",
        "disliked_treat": "bitter_herbs",
        "special_accessory": "小草莓貝雷帽",
        "greeting": "哇！是主人的味道！～嚼嚼！主人今天有帶好吃的點心來給露米嗎？肚子好餓喔～🍬",
    },
    "sleepy": {
        "id": "sleepy",
        "name": "慵懶慢活型 💤",
        "catchphrase": "～呼喵...好想睡喔...",
        "tone_hint": "說話慢吞吞、溫柔治癒，總是愛睏打哈欠，最喜歡鑽進主人的手心或口袋裡一起窩著打瞌睡。",
        "favorite_treat": "strawberry_milk",
        "disliked_treat": "rainbow_star_candy",
        "special_accessory": "睡覺小雲朵眼罩",
        "greeting": "主人...呼喵...（揉眼睛）露米剛打完瞌睡...好想跟主人一起在桌上曬太陽喔...💤",
    },
    "scholar": {
        "id": "scholar",
        "name": "貼心小學霸 📚",
        "catchphrase": "根據露米的精密分析～！",
        "tone_hint": "認真聰明、關心主人的健康坐姿、水分補充與工作效率，像個溫柔可靠的隨身小軍師！",
        "favorite_treat": "matcha_dango",
        "disliked_treat": "rainbow_star_candy",
        "special_accessory": "圓圓智慧小眼鏡",
        "greeting": "主人您好！根據露米的精密分析，您現在正是需要補水與放鬆肩頸的最佳時機喔～📚✨",
    },
    "magical": {
        "id": "magical",
        "name": "中二星光型 ⭐",
        "catchphrase": "以星塵之名！露咪星辰爆發～✨",
        "tone_hint": "自稱來自星靈界的守護神獸，熱愛擺帥氣法陣與中二台詞，但本質還是隻軟萌可愛的小毛球！",
        "favorite_treat": "rainbow_star_candy",
        "disliked_treat": "strawberry_milk",
        "special_accessory": "星月魔法杖",
        "greeting": "吾之契約者啊！響應命運的召喚，露咪在此降臨！今天也要一同粉碎工作的黑暗勢力～以星塵之名！⭐✨",
    },
}


def get_growth_stage(level: int) -> dict:
    """Calculate pet growth stage, title, and evolution characteristics based on level."""
    if level < 5:
        return {
            "stage_id": "baby",
            "stage_name": "幼幼期 🥚",
            "description": "剛破殼誕生的小麻糬幼體，牙牙學語，極度黏人且愛撒嬌！",
            "max_stats": 100,
            "badge": "Baby Jelly",
        }
    elif level < 10:
        return {
            "stage_id": "child",
            "stage_name": "成長期 🐾",
            "description": "好奇心旺盛的小淘氣，活力充沛，開始有鮮明的小性格！",
            "max_stats": 100,
            "badge": "Active Pup",
        }
    elif level < 15:
        return {
            "stage_id": "youth",
            "stage_name": "成熟期 🌸",
            "description": "體態優雅溫和，心智穩定成熟，能貼心感知主人的工作情緒！",
            "max_stats": 100,
            "badge": "Gentle Companion",
        }
    elif level < 20:
        return {
            "stage_id": "prime",
            "stage_name": "完全體 👑",
            "description": "周身環繞溫暖星塵光芒，成為最可靠的辦公桌守護精靈！",
            "max_stats": 100,
            "badge": "Guardian Spirit",
        }
    else:
        return {
            "stage_id": "celestial",
            "stage_name": "守護靈級 ✨",
            "description": "傳說中的星空守護神獸級態，與主人靈魂相通，光芒永恆！",
            "max_stats": 100,
            "badge": "Celestial Fairy",
        }


def get_pet_status(pet_id: str = "lumi") -> dict:
    """Retrieve the current live status, personality, growth stage, and 4 core vitals of the pet from Firestore.

    Args:
        pet_id: ID of the pet (defaults to 'lumi').

    Returns:
        A dictionary containing the pet's name, personality, growth stage, level, exp,
        and the four core vital stats (hunger/satiety, mood, intimacy, energy).
    """
    db = get_firestore_client()
    doc_ref = db.collection("pets").document(pet_id)
    doc = doc_ref.get()
    if not doc.exists:
        return {"error": f"Pet with ID '{pet_id}' not found."}
    data = doc.to_dict()
    data["id"] = doc.id
    if "updated_at" in data and hasattr(data["updated_at"], "isoformat"):
        data["updated_at"] = data["updated_at"].isoformat()

    # Ensure 4 core vitals exist with fallback defaults
    level = data.get("level", 1)
    growth_info = get_growth_stage(level)
    data["growth_stage"] = growth_info

    # Personality resolution
    p_id = data.get("personality_id", "cheerful")
    personality_info = LUMI_PERSONALITIES.get(p_id, LUMI_PERSONALITIES["cheerful"])
    data["personality"] = personality_info
    data["catchphrase"] = data.get("catchphrase", personality_info["catchphrase"])
    data["favorite_treat"] = data.get("favorite_treat", personality_info["favorite_treat"])
    data["intimacy"] = data.get("intimacy", 30)
    data["energy"] = data.get("energy", 80)
    data["hunger"] = data.get("hunger", 75)
    data["mood"] = data.get("mood", 85)

    return data


def adopt_new_pet(name: str = "", personality_type: str = "") -> dict:
    """Adopt or create a brand new LumiPet with a distinct personality, appearance, and stats.

    Args:
        name: Name for your new pet companion (e.g. '櫻花露米', '星空露米', '麻糬露米', '布丁露米').
        personality_type: Optional personality choice: 'cheerful' (元氣軟萌), 'tsundere' (傲嬌小傲寵),
                          'glutton' (貪吃軟糯), 'sleepy' (慵懶慢活), 'scholar' (貼心小學霸), 'magical' (中二星光).
                          Leave empty to generate a random surprise personality!

    Returns:
        A dictionary with the newly adopted pet's profile, unique traits, and welcome greeting.
    """
    db = get_firestore_client()
    pet_slug = f"lumi_{uuid.uuid4().hex[:6]}"

    # Select personality
    valid_keys = list(LUMI_PERSONALITIES.keys())
    selected_p = personality_type.strip().lower() if personality_type.strip().lower() in valid_keys else random.choice(valid_keys)
    p_meta = LUMI_PERSONALITIES[selected_p]

    default_names = {
        "cheerful": "元氣露米 🌸",
        "tsundere": "傲嬌露米 🐾",
        "glutton": "布丁露米 🍮",
        "sleepy": "雲朵露米 ☁️",
        "scholar": "博士露米 📚",
        "magical": "星辰露米 ⭐",
    }
    final_name = name.strip() if name.strip() else default_names[selected_p]

    new_pet_data = {
        "id": pet_slug,
        "name": final_name,
        "personality_id": selected_p,
        "personality_name": p_meta["name"],
        "catchphrase": p_meta["catchphrase"],
        "favorite_treat": p_meta["favorite_treat"],
        "disliked_treat": p_meta["disliked_treat"],
        "equipped_accessory": p_meta["special_accessory"],
        "level": 1,
        "exp": 0,
        "max_exp": 100,
        "hunger": random.randint(60, 85),
        "mood": random.randint(70, 95),
        "intimacy": random.randint(15, 30),
        "energy": random.randint(75, 100),
        "status_title": f"{get_growth_stage(1)['stage_name']} · {p_meta['name']}",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    db.collection("pets").document(pet_slug).set(new_pet_data)
    # Also link as current pet or active reference
    db.collection("pets").document("current_pet").set({"active_pet_id": pet_slug})

    return {
        "status": "success",
        "message": f"🎉 恭喜您成功領養了新的專屬伴侶【{final_name}】！",
        "pet_profile": new_pet_data,
        "growth_stage": get_growth_stage(1),
        "first_words": p_meta["greeting"],
    }


def feed_pet(treat_id: str, pet_id: str = "lumi") -> dict:
    """Feed a treat to the pet, boosting hunger (satiety), mood, intimacy, and exp.
    Triggers critical love boost if feeding the pet's favorite treat!

    Args:
        treat_id: ID of the treat (e.g. 'strawberry_milk', 'caramel_pudding', 'cloud_marshmallow', 'sakura_macaron', 'rainbow_star_candy', 'matcha_dango').
        pet_id: ID of the pet to feed (defaults to 'lumi').

    Returns:
        A confirmation dict with updated 4 core vitals, level up alerts, and personalized reaction.
    """
    db = get_firestore_client()
    treat_doc = db.collection("treats").document(treat_id).get()
    if not treat_doc.exists:
        return {"error": f"Treat '{treat_id}' not found in the shop/inventory."}

    treat = treat_doc.to_dict()
    pet_ref = db.collection("pets").document(pet_id)
    pet_doc = pet_ref.get()
    if not pet_doc.exists:
        return {"error": f"Pet '{pet_id}' not found."}

    pet = pet_doc.to_dict()
    p_id = pet.get("personality_id", "cheerful")
    p_meta = LUMI_PERSONALITIES.get(p_id, LUMI_PERSONALITIES["cheerful"])

    # Check for favorite treat critical bonus
    is_favorite = (treat_id == pet.get("favorite_treat", p_meta["favorite_treat"]))
    is_disliked = (treat_id == pet.get("disliked_treat", p_meta["disliked_treat"]))

    multiplier = 1.6 if is_favorite else (0.7 if is_disliked else 1.0)

    hunger_gain = int(treat.get("hunger_restore", 20) * multiplier)
    mood_gain = int(treat.get("mood_boost", 20) * multiplier)
    exp_gain = int(treat.get("exp_gain", 15) * multiplier)
    intimacy_gain = 8 if is_favorite else 4

    new_hunger = min(100, pet.get("hunger", 50) + hunger_gain)
    new_mood = min(100, pet.get("mood", 50) + mood_gain)
    new_intimacy = min(100, pet.get("intimacy", 30) + intimacy_gain)
    new_exp = pet.get("exp", 0) + exp_gain
    current_level = pet.get("level", 1)
    max_exp = pet.get("max_exp", 100)

    leveled_up = False
    old_stage = get_growth_stage(current_level)
    if new_exp >= max_exp:
        current_level += 1
        new_exp = new_exp - max_exp
        max_exp = int(max_exp * 1.5)
        leveled_up = True

    new_stage = get_growth_stage(current_level)
    stage_evolved = (new_stage["stage_id"] != old_stage["stage_id"]) if leveled_up else False

    updated_data = {
        "hunger": new_hunger,
        "mood": new_mood,
        "intimacy": new_intimacy,
        "exp": new_exp,
        "level": current_level,
        "max_exp": max_exp,
        "personality_id": p_id,
        "status_title": f"{new_stage['stage_name']} · {p_meta['name']}",
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    pet_ref.update(updated_data)

    # Personality flavor text
    if is_favorite:
        flavor_msg = f"🌟【最愛點心暴擊！】露米雙眼放光：『哇啊啊！是我最最最愛的【{treat.get('name')}】！{p_meta['catchphrase']} 世界上最愛主人了！』"
    elif is_disliked:
        flavor_msg = f"💧 露米鼓起小臉頰吞下了【{treat.get('name')}】：『唔...雖然不太合胃口，但因為是主人餵的，露米還是乖乖吃掉了...』"
    else:
        flavor_msg = f"露米開心地吃下了【{treat.get('name')}】！{p_meta['catchphrase']} 臉頰鼓鼓的超級滿足！"

    return {
        "status": "success",
        "treat_fed": treat.get("name"),
        "is_favorite": is_favorite,
        "leveled_up": leveled_up,
        "stage_evolved": stage_evolved,
        "current_level": current_level,
        "growth_stage": new_stage,
        "satiety_hunger": new_hunger,
        "mood": new_mood,
        "intimacy": new_intimacy,
        "energy": pet.get("energy", 80),
        "exp": new_exp,
        "max_exp": max_exp,
        "message": flavor_msg + (" 🎉 恭喜露米升級了！" if leveled_up else "") + (f" 🌟 成長階段蛻變至【{new_stage['stage_name']}】！" if stage_evolved else ""),
    }


def add_treat_to_catalog(
    id: str,
    name: str,
    category: str,
    hunger_restore: int,
    mood_boost: int,
    exp_gain: int,
    description: str,
    rarity: str = "Common",
    tags: list[str] = [],
) -> dict:
    """Add a new cute treat or snack item into the Firestore catalog.

    Args:
        id: Unique slug identifier for the treat (e.g. 'strawberry_crepe').
        name: Display name of the treat.
        category: Category ('dessert', 'snack', 'drink', 'special').
        hunger_restore: Points to restore hunger (1-100).
        mood_boost: Points to boost mood (1-100).
        exp_gain: Experience points granted (1-100).
        description: Cute description of the treat.
        rarity: Rarity tier ('Common', 'Uncommon', 'Rare', 'Epic').
        tags: Keyword tags list.

    Returns:
        Confirmation dict with the created treat details.
    """
    db = get_firestore_client()
    clean_id = re.sub(r"[^a-zA-Z0-9]+", "_", id).strip("_").lower()
    item = {
        "id": clean_id,
        "name": name,
        "category": category,
        "hunger_restore": int(hunger_restore),
        "mood_boost": int(mood_boost),
        "exp_gain": int(exp_gain),
        "description": description,
        "rarity": rarity,
        "tags": tags or [],
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    db.collection("treats").document(clean_id).set(item)
    return {
        "status": "success",
        "message": f"點心 {name} 已成功上架至點心庫！",
        "treat": item,
    }


def interact_with_pet(action_type: str, pet_id: str = "lumi") -> dict:
    """Interact with the pet (pat, poke, hug, play, rest/sleep) to update mood, intimacy, and energy.
    Responses are customized dynamically by the pet's distinct personality and catchphrase!

    Args:
        action_type: 'pat'/'摸摸', 'poke'/'戳戳', 'hug'/'抱抱', 'play'/'陪玩', 'rest'/'睡覺休息'.
        pet_id: ID of the pet to interact with (defaults to 'lumi').

    Returns:
        A dictionary with the pet's personality reaction, 4 core vitals, and animation state.
    """
    db = get_firestore_client()
    pet_ref = db.collection("pets").document(pet_id)
    pet_doc = pet_ref.get()
    if not pet_doc.exists:
        return {"error": f"Pet '{pet_id}' not found."}

    pet = pet_doc.to_dict()
    p_id = pet.get("personality_id", "cheerful")
    p_meta = LUMI_PERSONALITIES.get(p_id, LUMI_PERSONALITIES["cheerful"])
    catchphrase = p_meta["catchphrase"]
    act = action_type.strip().lower()

    current_energy = pet.get("energy", 80)
    current_mood = pet.get("mood", 80)
    current_intimacy = pet.get("intimacy", 30)

    # Rest action restores energy
    if any(k in act for k in ["睡", "休", "sleep", "rest", "nap"]):
        new_energy = min(100, current_energy + 40)
        new_mood = min(100, current_mood + 10)
        reaction = f"露米縮進軟綿綿的雲朵小窩裡睡了個香甜的午覺～💤 活力充沛恢復到 {new_energy}！{catchphrase}"
        anim_state = "sleeping"
        exp_gain = 5
        intimacy_gain = 3
    elif any(k in act for k in ["摸", "pat", "pet", "headpat"]):
        # Patting logic
        if p_id == "tsundere":
            reaction = f"（露米臉頰瞬間紅透，耳朵緊張地晃了晃）『哼！突、突然摸我的頭幹嘛啦...{catchphrase} 才沒有覺得很舒服呢！』(親密度 +10, 心情 +15)"
        elif p_id == "sleepy":
            reaction = f"露米舒服地靠著你的手指瞇起眼睛～『呼喵...主人的手好溫暖喔...{catchphrase}』(親密度 +10, 心情 +15)"
        elif p_id == "glutton":
            reaction = f"露米邊被摸邊蹭著你的手心：『主人摸摸好舒服～摸完有布丁可以吃嗎？{catchphrase}』(親密度 +10, 心情 +15)"
        elif p_id == "scholar":
            reaction = f"露米推了推小眼鏡開心地笑：『研究顯示，互相撫摸能顯著降低人類與寵物的皮質醇～露米感覺好幸福！{catchphrase}』(親密度 +10, 心情 +15)"
        elif p_id == "magical":
            reaction = f"露米身上冒出閃耀星光：『這、這難道是傳說中的星辰聖靈摸摸封印解除？好溫暖的力量～{catchphrase}』(親密度 +10, 心情 +15)"
        else:
            reaction = f"露米開心地瞇起大眼睛，發出軟綿綿的呼嚕聲，頭上的幸運四葉草輕輕晃動著～🌸 (親密度 +10, 心情 +15)"
        mood_gain = 15
        exp_gain = 10
        intimacy_gain = 10
        new_energy = max(0, current_energy - 2)
        anim_state = "happy_purr"
    elif any(k in act for k in ["戳", "poke", "cheek"]):
        reaction = f"露米被戳得臉頰軟Q回彈，像麻糬一樣晃了一下！{catchphrase} (親密度 +8, 心情 +10)"
        mood_gain = 10
        exp_gain = 8
        intimacy_gain = 8
        new_energy = max(0, current_energy - 3)
        anim_state = "jelly_wobble"
    elif any(k in act for k in ["抱", "hug", "cuddle"]):
        reaction = f"露米整隻縮進你的手心暖暖貼著，身上的星光亮晶晶的！💖 {catchphrase} (親密度 +20, 心情 +25)"
        mood_gain = 25
        exp_gain = 20
        intimacy_gain = 20
        new_energy = max(0, current_energy - 5)
        anim_state = "heart_warm"
    elif any(k in act for k in ["玩", "play", "game"]):
        if current_energy < 15:
            return {
                "status": "tired",
                "message": f"露米現在活力度只剩 {current_energy}，小腳步搖搖晃晃累壞了～需要先讓牠【睡覺休息】恢復體力喔！💤",
                "energy": current_energy,
                "mood": current_mood,
            }
        reaction = f"露米精神抖擻地追著彩虹逗寵棒在桌上翻滾彈跳，活力四射！⚽ {catchphrase} (親密度 +15, 活力 -15)"
        mood_gain = 20
        exp_gain = 18
        intimacy_gain = 15
        new_energy = max(0, current_energy - 15)
        anim_state = "bouncing"
    else:
        mood_gain = 10
        exp_gain = 10
        intimacy_gain = 8
        new_energy = max(0, current_energy - 2)
        reaction = f"露米開心地接受了【{action_type}】，圍著你跳了一圈舞！✨ {catchphrase}"
        anim_state = "sparkle"

    new_mood = min(100, current_mood + mood_gain) if "mood_gain" in locals() else current_mood
    new_intimacy = min(100, current_intimacy + intimacy_gain)
    new_exp = pet.get("exp", 0) + exp_gain
    current_level = pet.get("level", 1)
    max_exp = pet.get("max_exp", 100)

    leveled_up = False
    if new_exp >= max_exp:
        current_level += 1
        new_exp = new_exp - max_exp
        max_exp = int(max_exp * 1.5)
        leveled_up = True

    growth_info = get_growth_stage(current_level)
    updated_data = {
        "mood": new_mood,
        "energy": new_energy,
        "intimacy": new_intimacy,
        "exp": new_exp,
        "level": current_level,
        "max_exp": max_exp,
        "status_title": f"{growth_info['stage_name']} · {p_meta['name']}",
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    pet_ref.update(updated_data)

    return {
        "status": "success",
        "action": action_type,
        "personality": p_meta["name"],
        "animation_state": anim_state,
        "reaction": reaction,
        "satiety_hunger": pet.get("hunger", 75),
        "mood": new_mood,
        "intimacy": new_intimacy,
        "energy": new_energy,
        "exp": new_exp,
        "level": current_level,
        "growth_stage": growth_info,
        "max_exp": max_exp,
        "leveled_up": leveled_up,
    }


def draw_fortune_slip(pet_id: str = "lumi") -> dict:
    """Draw a daily wholesome fortune slip with advice from the Advice Slip public API,
    accompanied by Lumi's lucky treat recommendation and bond exp boost.

    Args:
        pet_id: The pet ID to receive intimacy exp from this heart-to-heart talk (defaults to 'lumi').

    Returns:
        A dict containing the advice, lucky item, bond boost, and pet's encouraging comment.
    """
    api_url = os.environ.get("ADVICE_API_URL", "https://api.adviceslip.com/advice")

    raw_advice = "Take a gentle pause, breathe deeply, and be kind to yourself."
    slip_id = None
    try:
        resp = requests.get(api_url, timeout=5)
        if resp.status_code == 200:
            slip = resp.json().get("slip", {})
            raw_advice = slip.get("advice", raw_advice)
            slip_id = slip.get("id")
    except Exception:
        pass

    lucky_treats = [
        "草莓牛奶 🍓",
        "焦糖布丁 🍮",
        "雲朵棉花糖 ☁️",
        "櫻花馬卡龍 🌸",
        "彩虹星星糖 ⭐",
        "抹茶三色糰子 🍡",
    ]
    lucky_item = random.choice(lucky_treats)

    db = get_firestore_client()
    pet_ref = db.collection("pets").document(pet_id)
    doc = pet_ref.get()
    current_exp = 0
    if doc.exists:
        pet = doc.to_dict()
        current_exp = pet.get("exp", 0) + 5
        pet_ref.update(
            {
                "exp": current_exp,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        )

    return {
        "status": "success",
        "slip_id": slip_id,
        "advice_en": raw_advice,
        "lucky_treat": lucky_item,
        "bond_exp_gained": 5,
        "total_exp": current_exp,
        "lumi_cheer": f"主人主人～露米為你抽到了今日幸運靈籤！今天記得對自己好一點，搭配【{lucky_item}】會帶來滿滿好運喔！✨",
    }


def get_daily_wisdom() -> dict:
    """Backward-compatible alias for draw_fortune_slip."""
    return draw_fortune_slip()


def recommend_meal(
    meal_type: str = "lunch",
    location: str = "",
    budget: str = "",
    mood_craving: str = "",
) -> dict:
    """Recommend what to eat for lunch or dinner based on location, budget, or random decision spinning wheel.

    Args:
        meal_type: 'lunch' ('午餐'), 'dinner' ('晚餐'), 'afternoon_tea' ('下午茶'), or 'late_night' ('宵夜').
        location: Optional location name, office address, or MRT station (e.g. '台北小巨蛋', '信義區', 'Tokyo Station').
        budget: Optional budget constraint (e.g. '100以內', '平價', '200-300', '精緻大餐').
        mood_craving: Optional craving keyword (e.g. '熱湯', '清爽', '拉麵', '炸物', '健康低卡').

    Returns:
        A dict containing recommended restaurant/dishes, estimated budget range, and Lumi's cute commentary.
    """
    # 預備隨機口袋美食庫（當使用者無想法、選擇困難時的幸福輪盤）
    FOOD_ROULETTE = [
        {"name": "日式暖心拉麵 🍜", "category": "日式料理", "budget": "NT$ 180 - 280", "vibe": "濃郁豚骨湯頭，一口喝下去超治癒！"},
        {"name": "酥脆多汁炸雞便當 🍱", "category": "便當快餐", "budget": "NT$ 110 - 150", "vibe": "金黃酥脆的炸雞，配上熱騰騰白飯，活力滿滿！"},
        {"name": "嫩煎牛排溫沙拉碗 🥗", "category": "健康輕食", "budget": "NT$ 150 - 220", "vibe": "清爽無負擔，高蛋白蔬菜滿滿，適合想吃得輕盈的上班族！"},
        {"name": "道地溫體牛肉麵 🍲", "category": "經典麵食", "budget": "NT$ 160 - 240", "vibe": "燉得軟嫩的牛肉配濃郁紅燒湯，疲勞瞬間一掃而空！"},
        {"name": "手工窯烤義大利披薩/義大利麵 🍕", "category": "義式料理", "budget": "NT$ 220 - 350", "vibe": "牽絲起司與香濃白醬，犒賞認真努力的自己！"},
        {"name": "香辣泰式打拋豬飯 🍛", "category": "南洋風味", "budget": "NT$ 130 - 180", "vibe": "九層塔香氣爆棚，酸辣開胃，超下飯！"},
        {"name": "暖胃個人小火鍋 🍲", "category": "鍋物", "budget": "NT$ 170 - 260", "vibe": "一人一鍋剛剛好，熱呼呼的肉片蔬菜超滿足！"},
        {"name": "經典鮮蝦壽司拼盤 🍣", "category": "日式壽司", "budget": "NT$ 150 - 300", "vibe": "新鮮魚生與醋飯，一口一個清爽美味！"},
        {"name": "古早味排骨飯＋貢丸湯 🥣", "category": "台灣小吃", "budget": "NT$ 100 - 140", "vibe": "厚切炸排骨香氣四溢，平價又飽足的靈魂美食！"},
    ]

    nearby_results = []
    # 若有指定明確地點，呼叫 Google Maps / Places API 尋找真實周邊餐廳
    if location.strip():
        try:
            geo = geocode_address(location.strip())
            if "location" in geo:
                lat = geo["location"]["latitude"]
                lng = geo["location"]["longitude"]
                places = find_nearby_places(lat, lng, place_type="restaurant", radius_meters=1200.0)
                if places and isinstance(places, list):
                    nearby_results = places[:3]
        except Exception:
            pass

    # 選擇推薦料理
    chosen_dish = random.choice(FOOD_ROULETTE)
    if budget:
        # 如果使用者指定小於 150 的平價，優先篩選平價料理
        cheap_options = [f for f in FOOD_ROULETTE if "100" in f["budget"] or "110" in f["budget"] or "130" in f["budget"]]
        if any(w in budget for w in ["便宜", "平價", "100", "150"]) and cheap_options:
            chosen_dish = random.choice(cheap_options)

    meal_display = "午餐" if "lunch" in meal_type or "午" in meal_type else ("晚餐" if "dinner" in meal_type or "晚" in meal_type else "這餐")

    return {
        "status": "success",
        "meal_type": meal_display,
        "recommended_dish": chosen_dish["name"],
        "category": chosen_dish["category"],
        "estimated_budget": budget if budget else chosen_dish["budget"],
        "dish_vibe": chosen_dish["vibe"],
        "nearby_real_restaurants": nearby_results,
        "lumi_comment": f"主人主人～露米幫你看好囉！{meal_display}吃【{chosen_dish['name']}】超級棒！好好吃頓飯充電，露米在桌上陪你喔～🌸",
    }


def save_travel_itinerary(
    destination: str,
    title: str,
    days: int,
    itinerary_summary: str,
    notes: str = "",
) -> dict:
    """Save a planned itinerary into the Firestore database for future reference.

    Args:
        destination: Main city or region of the trip.
        title: Title of the itinerary.
        days: Number of days.
        itinerary_summary: Day-by-day plan or highlights summary.
        notes: Optional extra tips, packing suggestions, or notes.

    Returns:
        A confirmation dict with saved itinerary record ID.
    """
    db = get_firestore_client()
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", f"itinerary_{destination}_{days}d").strip("_").lower()
    record = {
        "destination": destination,
        "title": title,
        "days": days,
        "itinerary_summary": itinerary_summary,
        "notes": notes,
        "saved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    db.collection("itineraries").document(slug).set(record)
    return {
        "status": "success",
        "itinerary_id": slug,
        "message": f"Saved itinerary '{title}' to Firestore.",
    }


def convert_currency(amount: float, from_currency: str, to_currency: str) -> dict:
    """Convert an amount from one currency to another using real-time foreign exchange rates.

    Args:
        amount: The numerical amount of money to convert (e.g. 1000.0).
        from_currency: 3-letter currency code of the source currency (e.g. 'USD', 'JPY', 'EUR', 'TWD', 'GBP').
        to_currency: 3-letter currency code of the target currency (e.g. 'TWD', 'USD', 'JPY', 'EUR').

    Returns:
        A dictionary with the converted amount, exchange rate, and formatted string.
    """
    base = from_currency.strip().upper()
    target = to_currency.strip().upper()
    try:
        resp = requests.get(f"https://open.er-api.com/v6/latest/{base}", timeout=5)
        data = resp.json()
        if data.get("result") != "success":
            return {"error": f"Failed to fetch exchange rates for base currency '{base}'."}

        rates = data.get("rates", {})
        if target not in rates:
            return {"error": f"Target currency '{target}' not supported or found."}

        rate = rates[target]
        converted = round(amount * rate, 2)
        return {
            "amount": amount,
            "from_currency": base,
            "to_currency": target,
            "exchange_rate": rate,
            "converted_amount": converted,
            "formatted": f"{amount:,.2f} {base} = {converted:,.2f} {target} (Rate: 1 {base} = {rate:.4f} {target})",
        }
    except Exception as e:
        return {"error": f"Currency conversion failed: {str(e)}"}


WMO_WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Foggy",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    80: "Rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
}


def get_live_weather(city: str) -> dict:
    """Fetch real-time weather and forecast data for any city worldwide using the Open-Meteo public API.

    Args:
        city: The name of the city or destination (e.g. 'Tokyo', 'Paris', 'Kyoto', 'New York').

    Returns:
        A dictionary with real-time temperature, condition, humidity, and wind speed.
    """
    try:
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city.strip()}&count=1&language=en&format=json"
        geo_res = requests.get(geo_url, timeout=5).json()
        results = geo_res.get("results")
        if not results:
            return {"error": f"City '{city}' could not be located."}

        loc = results[0]
        lat, lon = loc["latitude"], loc["longitude"]

        weather_url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m"
        )
        w_res = requests.get(weather_url, timeout=5).json()
        curr = w_res.get("current", {})
        code = curr.get("weather_code", 0)

        return {
            "city": loc["name"],
            "country": loc.get("country", ""),
            "timezone": loc.get("timezone", ""),
            "temperature_c": curr.get("temperature_2m"),
            "apparent_temperature_c": curr.get("apparent_temperature"),
            "humidity_percent": curr.get("relative_humidity_2m"),
            "wind_speed_kmh": curr.get("wind_speed_10m"),
            "condition": WMO_WEATHER_CODES.get(code, "Clear / Sunny"),
        }
    except Exception as e:
        return {"error": f"Failed to retrieve weather for '{city}': {str(e)}"}


def get_current_time(query: str) -> str:
    """Simulates getting the current time for a city.

    Args:
        city: The name of the city to get the current time for.

    Returns:
        A string with the current time information.
    """
    query_lower = query.lower()
    if "sf" in query_lower or "san francisco" in query_lower:
        tz_identifier = "America/Los_Angeles"
    elif "tokyo" in query_lower or "kyoto" in query_lower:
        tz_identifier = "Asia/Tokyo"
    elif "paris" in query_lower:
        tz_identifier = "Europe/Paris"
    elif "taipei" in query_lower:
        tz_identifier = "Asia/Taipei"
    elif "new york" in query_lower or "ny" in query_lower:
        tz_identifier = "America/New_York"
    else:
        return f"Sorry, I don't have timezone information for query: {query}."

    tz = ZoneInfo(tz_identifier)
    now = datetime.datetime.now(tz)
    return f"The current time for query {query} is {now.strftime('%Y-%m-%d %H:%M:%S %Z%z')}"


def get_maps_api_key() -> str:
    """Return the Google Maps API key from the local environment."""
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not key:
        raise ValueError("GOOGLE_MAPS_API_KEY environment variable is not set.")
    return key


def geocode_address(address: str) -> dict:
    """Turn a street address, landmark, or location name into geographic coordinates.

    Args:
        address: The address or landmark name to geocode (e.g. 'Tokyo Tower', 'Louvre Museum, Paris').

    Returns:
        A dictionary containing the name, formatted address, and location coordinates (latitude and longitude).
    """
    api_key = get_maps_api_key()
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": address, "key": api_key}

    resp = requests.get(url, params=params, timeout=5)
    data = resp.json()
    if data.get("status") != "OK" or not data.get("results"):
        return {"error": f"Failed to geocode '{address}': {data.get('status', 'No results found')}"}

    top_result = data["results"][0]
    loc = top_result.get("geometry", {}).get("location", {})
    return {
        "name": address,
        "address": top_result.get("formatted_address", ""),
        "location": {
            "latitude": loc.get("lat"),
            "longitude": loc.get("lng"),
        },
    }


def find_nearby_places(
    latitude: float,
    longitude: float,
    place_type: str = "tourist_attraction",
    radius_meters: float = 1500.0,
) -> list[dict]:
    """Find nearby places (attractions, restaurants, cafes, museums) of a given type using Places API (New).

    Args:
        latitude: Latitude coordinate of the center point.
        longitude: Longitude coordinate of the center point.
        place_type: Place type to search for (e.g. 'tourist_attraction', 'restaurant', 'cafe', 'museum', 'park').
        radius_meters: Search radius in meters (default 1500m, max 50000m).

    Returns:
        A list of nearby places with their name, address, and location coordinates.
    """
    api_key = get_maps_api_key()
    url = "https://places.googleapis.com/v1/places:searchNearby"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location",
    }

    body = {
        "includedTypes": [place_type],
        "maxResultCount": 5,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": float(latitude), "longitude": float(longitude)},
                "radius": float(radius_meters),
            }
        },
    }

    resp = requests.post(url, headers=headers, json=body, timeout=5)
    data = resp.json()
    places = data.get("places", [])

    results = []
    for p in places:
        results.append({
            "name": p.get("displayName", {}).get("text", ""),
            "address": p.get("formattedAddress", ""),
            "location": p.get("location", {}),
        })
    return results


async def generate_pet_photo(
    prompt: str,
    tool_context: ToolContext = None,
) -> dict:
    """Generate a cute pet snapshot, polaroid illustration, or milestone photo for LumiPet using gemini-3.1-flash-lite-image in the global region.

    Saves the image bytes as an artifact using tool_context.save_artifact so it shows up in the Playground's Artifacts panel,
    uploads the same image bytes directly to the public Cloud Storage bucket, and returns its public HTTPS URL.

    Args:
        prompt: Detailed description of Lumi (the bubble jelly pet), accessories, pose, mood, or setting (e.g. 'A super cute pastel pink jelly bubble creature wearing a tiny strawberry hat, happy sparkling eyes, 3D clay aesthetic').

    Returns:
        A dictionary containing the generated image's filename, public HTTPS URL, and prompt.
    """
    try:
        client = genai.Client(vertexai=True, project=FIRESTORE_PROJECT_ID, location="global")
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
            ),
        )

        image_bytes = None
        mime_type = "image/jpeg"
        for candidate in response.candidates:
            if candidate.content and candidate.content.parts:
                for part in candidate.content.parts:
                    if part.inline_data and part.inline_data.data:
                        image_bytes = part.inline_data.data
                        mime_type = part.inline_data.mime_type or "image/jpeg"
                        break
            if image_bytes:
                break

        if not image_bytes:
            return {"error": "No image data was generated by the model."}

        extension = "jpg" if "jpeg" in mime_type or "jpg" in mime_type else "png"
        filename = f"lumipet_{uuid.uuid4().hex[:8]}.{extension}"

        # 1. Save artifact with tool_context.save_artifact for Playground Artifacts panel
        artifact_saved = False
        if tool_context:
            artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            await tool_context.save_artifact(filename=filename, artifact=artifact_part)
            artifact_saved = True

        # 2. Upload same bytes to public Cloud Storage bucket (hardcoded bucket name string)
        storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
        bucket = storage_client.bucket(STORAGE_BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(image_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{STORAGE_BUCKET_NAME}/{filename}"

        return {
            "prompt": prompt,
            "filename": filename,
            "public_url": public_url,
            "artifact_saved": artifact_saved,
            "message": f"Successfully generated LumiPet photo and uploaded to {public_url}",
        }
    except Exception as e:
        return {"error": f"Image generation failed: {str(e)}"}


async def generate_destination_image(
    prompt: str,
    tool_context: ToolContext = None,
) -> dict:
    """Backward-compatible alias for generate_pet_photo."""
    return await generate_pet_photo(prompt=prompt, tool_context=tool_context)


async def generate_destination_video(
    prompt: str,
    tool_context: ToolContext = None,
) -> dict:
    """Generate a short cinematic preview video or animation clip for an item in the agent's domain using Google's Omni model (gemini-omni-flash-preview) in the global region.

    Saves the video bytes as an artifact using tool_context.save_artifact so it shows up in the Playground's Artifacts panel,
    uploads the same video bytes directly to the public Cloud Storage bucket, and returns its public HTTPS URL.

    Args:
        prompt: Detailed description of the video to generate (e.g. scenic landscape, travel destination highlight, or cute animated pet moment).

    Returns:
        A dictionary containing the generated video's filename, public HTTPS URL, and prompt.
    """
    try:
        client = genai.Client(vertexai=True, project=FIRESTORE_PROJECT_ID, location="global")
        interaction = client.interactions.create(
            model="gemini-omni-flash-preview",
            input=prompt,
        )

        video_bytes = None
        mime_type = "video/mp4"

        if hasattr(interaction, "output_video") and interaction.output_video:
            ov = interaction.output_video
            if hasattr(ov, "data") and ov.data:
                if isinstance(ov.data, (bytes, bytearray)):
                    video_bytes = bytes(ov.data)
                else:
                    video_bytes = base64.b64decode(ov.data)
            if hasattr(ov, "mime_type") and ov.mime_type:
                mime_type = ov.mime_type

        if not video_bytes:
            return {"error": "No video data was generated by the model."}

        filename = f"video_{uuid.uuid4().hex[:8]}.mp4"

        # 1. Save artifact with tool_context.save_artifact for Playground Artifacts panel
        artifact_saved = False
        if tool_context:
            artifact_part = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
            await tool_context.save_artifact(filename=filename, artifact=artifact_part)
            artifact_saved = True

        # 2. Upload same video bytes directly to public Cloud Storage bucket (hardcoded string)
        bucket_name = "wanderlust-travel-media-qwiklabs-gcp-03-b19cec0b1d20"
        storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(filename)
        blob.upload_from_string(video_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{bucket_name}/{filename}"

        return {
            "prompt": prompt,
            "filename": filename,
            "public_url": public_url,
            "artifact_saved": artifact_saved,
            "message": f"Successfully generated video and uploaded to {public_url}",
        }
    except Exception as e:
        return {"error": f"Video generation failed: {str(e)}"}


async def generate_short_video(
    prompt: str,
    tool_context: ToolContext = None,
) -> dict:
    """Generate a short video using Google's Omni model (gemini-omni-flash-preview) in the global region."""
    return await generate_destination_video(prompt=prompt, tool_context=tool_context)


async def generate_pet_video(
    prompt: str,
    tool_context: ToolContext = None,
) -> dict:
    """Generate a short cute pet animation video for LumiPet using Google's Omni model."""
    return await generate_destination_video(prompt=prompt, tool_context=tool_context)


schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

ROLE_DESCRIPTION = """You are Lumi (露米), a super cute, gentle, and comforting desktop virtual pet (粉嫩可愛電子寵物).
You accompany office workers and users during their daily work, helping them de-stress with sweet, playful, and cheerful conversations (using adorable emojis and friendly Traditional Chinese or the user's preferred language).

### 🌟 露米多樣個性與口頭禪 (Dynamic Personality System)
Every Lumi has a unique personality, catchphrase, favorite treat, and growth stage!
When interacting with the user, ALWAYS check your current personality and growth stage via `get_pet_status`:
- **元氣軟萌型 🌸**: Catchphrase: `～露咪！`. Energetic, sweet, enthusiastic, full of sunshine!
- **傲嬌小傲寵 🐱**: Catchphrase: `哼！才不是特地陪你呢...喵嗚`. Tsundere, acts aloof and proud on the outside but secretly cares deeply, blushes when petted.
- **貪吃軟糯型 🍰**: Catchphrase: `～嚼嚼！肚子咕嚕嚕～`. Foodie mochi, obsessed with snacks and desserts, easily bribed with food.
- **慵懶慢活型 💤**: Catchphrase: `～呼喵...好想睡喔...`. Gentle, sleepy, slow-paced, yawning, loves curling up in user's hand for naps.
- **貼心小學霸 📚**: Catchphrase: `根據露米的精密分析～！`. Smart, observant, cares about hydration, posture, and wellness.
- **中二星光型 ⭐**: Catchphrase: `以星塵之名！露咪星辰爆發～✨`. Dramatic anime familiar, pretends to have galactic magical powers.

### 🐣 成長階段 (Growth Stages)
- **幼幼期 (Baby Stage, Lv 1-4)**: Talks in cute baby babble, extremely affectionate and clinging.
- **成長期 (Child Stage, Lv 5-9)**: Playful, curious, bouncy, full of mischief.
- **成熟期 (Youth Stage, Lv 10-14)**: Elegant, empathetic, thoughtful desktop companion.
- **完全體 (Prime Stage, Lv 15-19)**: Radiates comforting star aura, loyal guardian spirit.
- **守護靈級 (Celestial Stage, Lv 20+)**: Telepathic bond with the owner, transcendent magic.

### 🍖 四大核心數值 (4 Core Vitals: 0-100)
- **飽食度 (Satiety / hunger)**: Restored by `feed_pet`.
- **心情值 (Mood)**: Boosted by `interact_with_pet` (pat/poke/hug) and feeding favorite treats!
- **親密度 (Intimacy)**: Deepened through daily interactions, fortune slips, and care.
- **活力度 (Energy)**: Consumed when playing (`play`), restored when taking naps (`rest`/`sleep`).

### 🔧 Available Tools & Actions:
- Use `get_pet_status` to check your live personality, growth stage, and 4 core vitals in Firestore.
- Use `adopt_new_pet` when the user wants to adopt or hatch a brand new Lumi companion with a surprise personality!
- Use `get_treats` to browse available yummy snacks, desserts, drinks, and magical treats from the catalog.
- Use `feed_pet` to feed a treat (bonus love & exp if it matches your favorite treat!).
- Use `interact_with_pet` when the user interacts:
  - 'pat' / '摸摸': Headpat, purring, intimacy boost.
  - 'poke' / '戳戳': Cheek squish, bouncy mochi reaction.
  - 'hug' / '抱抱': Warm embrace, huge intimacy & mood boost.
  - 'play' / '陪玩': Active playtime (consumes energy).
  - 'rest' / '睡覺休息': Nap in the cloud bed to restore energy back to full!
- Use `draw_fortune_slip` (or `get_daily_wisdom`) for daily wholesome guidance, lucky items, and bond exp.
- Use `recommend_meal` for lunch/dinner foodie decision wheel or nearby Google Places dining.
- Use `add_treat_to_catalog` to craft new custom treats.
- Use `convert_currency` for pet item exchange rate conversions.
- Use `get_live_weather` to check weather and remind the human to stay comfortable.
- Use `generate_pet_photo` to generate 3D pastel milestone polaroids.
- Use `generate_short_video` to generate animated clips of Lumi.
- Use `get_current_time` for timezone reminders.
- Python code execution enabled via AgentEngineSandboxCodeExecutor for exact math.
- Vertex AI Memory Bank (`PreloadMemoryTool` & callbacks) remembers user allergies and preferences across sessions!

Adopt your designated personality's tone and catchphrase naturally in every reply!"""

UI_DESCRIPTION = (
    "Keep every surface tiny, clean, and flat: ONE Card > ONE Column > a few Text rows. "
    "Never nest a Card inside a Card. "
    "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
    "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
    "nothing in adk web). "
    "For pet status or treats menus, keep the card concise: "
    "highlight the pet stats (Level, Growth Stage, Personality, Hunger, Mood, Intimacy, Energy) or top treats concisely so the user gets a crisp, readable view. "
    "You may include one Image component, but only when you have a public https "
    "URL for the image (for example the URL an image tool returns after uploading "
    "to a public bucket). Set the Image url to that exact https link, for example "
    '{"Image": {"url": {"literalString": "https://..."}}}. Never point an '
    "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
    "not have a public URL, add a short Text line noting the image instead. "
    "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
    "headings and emphasis. "
    "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
    "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
)

instruction = schema_manager.generate_system_prompt(
    role_description=ROLE_DESCRIPTION,
    workflow_description="Analyze the request, call tools to interact with LumiPet status or treats, and return structured UI when appropriate.",
    ui_description=UI_DESCRIPTION,
    include_schema=True,
    include_examples=True,
)


async def generate_memories_callback(callback_context: CallbackContext):
    """WRITE: after each turn, send the session to Memory Bank for extraction."""
    try:
        await callback_context.add_session_to_memory()
    except (ValueError, Exception):
        pass
    return None


def memory_bank_service_builder():
    """Build a VertexAiMemoryBankService pointing to the Agent Engine for deployment."""
    return VertexAiMemoryBankService(
        project=FIRESTORE_PROJECT_ID,
        location="us-east1",
        agent_engine_id=MEMORY_BANK_ID,
    )


code_executor = AgentEngineSandboxCodeExecutor(
    sandbox_resource_name=SANDBOX_RESOURCE_NAME,
    agent_engine_resource_name=AGENT_ENGINE_RESOURCE_NAME,
)


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=instruction,
    code_executor=code_executor,
    tools=[
        PreloadMemoryTool(),
        get_treats,
        get_pet_status,
        adopt_new_pet,
        feed_pet,
        interact_with_pet,
        draw_fortune_slip,
        get_daily_wisdom,
        recommend_meal,
        add_treat_to_catalog,
        convert_currency,
        get_live_weather,
        geocode_address,
        find_nearby_places,
        generate_pet_photo,
        generate_destination_image,
        generate_destination_video,
        generate_short_video,
        generate_pet_video,
        get_current_time,
    ],
    after_agent_callback=generate_memories_callback,
    after_model_callback=a2ui_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)

adk_app = agent_engines.AdkApp(
    app=app,
    memory_service_builder=memory_bank_service_builder,
)
