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

# -----------------------------------------------------------------------------
# 🐾 LumiPet 多元可愛動物 (Species) 與 8 大靈魂個性 (8 Personalities) 系統
# -----------------------------------------------------------------------------

PET_SPECIES = {
    "rabbit": {
        "id": "rabbit",
        "name": "兔兔 🐰",
        "default_name": "棉花糖兔兔",
        "species_type": "animal",
        "icon": "🐰",
        "visual_desc": "擁有一對粉嫩垂耳、毛茸茸圓球尾巴的軟萌垂耳兔",
        "sound_words": ["～蹦跳！", "～唧唧！", "～揉耳朵！"],
        "default_accessory": "胡蘿蔔小斜背包",
    },
    "bear": {
        "id": "bear",
        "name": "小熊 🐻",
        "default_name": "焦糖可可熊",
        "species_type": "animal",
        "icon": "🐻",
        "visual_desc": "圓滾滾身軀、焦糖色軟毛、抱著迷你蜂蜜罐的憨萌小熊",
        "sound_words": ["～嗷嗚！", "～呼嚕！", "～抓抓肚肚！"],
        "default_accessory": "迷你小蜜罐",
    },
    "cat": {
        "id": "cat",
        "name": "貓咪 🐱",
        "default_name": "草莓軟糖喵",
        "species_type": "animal",
        "icon": "🐱",
        "visual_desc": "粉嫩肉球、靈巧三角耳與優雅搖晃尾巴的親人小貓咪",
        "sound_words": ["～喵嗚！", "～呼嚕嚕～", "～踩奶！"],
        "default_accessory": "紅緞帶小金鈴鐺",
    },
    "dog": {
        "id": "dog",
        "name": "小狗 🐶",
        "default_name": "暖陽柴柴狗",
        "species_type": "animal",
        "icon": "🐶",
        "visual_desc": "尾巴像螺旋槳狂搖、眼神閃閃發光忠誠無比的元氣小狗",
        "sound_words": ["～汪汪！", "～搖尾巴！", "～嗚汪！"],
        "default_accessory": "小骨頭項圈",
    },
    "penguin": {
        "id": "penguin",
        "name": "企鵝 🐧",
        "default_name": "冰淇淋小企鵝",
        "species_type": "animal",
        "icon": "🐧",
        "visual_desc": "圓嘟嘟肚子、走起路來左右搖擺搖晃的冰雪小紳士企鵝",
        "sound_words": ["～啪嗒啪嗒！", "～嗶嗶！", "～滑冰！"],
        "default_accessory": "藍色小領結",
    },
    "pig": {
        "id": "pig",
        "name": "小豬 🐷",
        "default_name": "櫻花小粉豬",
        "species_type": "animal",
        "icon": "🐷",
        "visual_desc": "粉紅圓潤臉頰、愛拱人手心的小豬鼻與捲捲小尾巴",
        "sound_words": ["～哼唧！", "～噗噗！", "～嚼嚼！"],
        "default_accessory": "小草莓花冠",
    },
    "sheep": {
        "id": "sheep",
        "name": "小羊 🐑",
        "default_name": "雲朵棉花羊",
        "species_type": "animal",
        "icon": "🐑",
        "visual_desc": "像剛出爐棉花糖一樣軟綿蓬鬆的純白雲朵小羊",
        "sound_words": ["～咩咩！", "～蹭蹭！", "～好軟喔！"],
        "default_accessory": "金色小牧鈴",
    },
    "duck": {
        "id": "duck",
        "name": "小鴨 🦆",
        "default_name": "黃金芝士小鴨",
        "species_type": "animal",
        "icon": "🦆",
        "visual_desc": "亮黃色羽毛、扁扁橘黃小嘴與游泳小蹼的呆萌小鴨",
        "sound_words": ["～呱呱！", "～撲棱撲棱！", "～划水！"],
        "default_accessory": "小荷葉帽子",
    },
    "chicken": {
        "id": "chicken",
        "name": "小雞 🐥",
        "default_name": "蛋黃毛球雞",
        "species_type": "animal",
        "icon": "🐥",
        "visual_desc": "剛破殼不久、毛茸茸圓滾滾像一顆會走路的小蛋黃",
        "sound_words": ["～啾啾！", "～嗶嗶！", "～啄米！"],
        "default_accessory": "半個小蛋殼帽",
    },
    "mouse": {
        "id": "mouse",
        "name": "老鼠 🐭",
        "default_name": "起司小金鼠",
        "species_type": "animal",
        "icon": "🐭",
        "visual_desc": "捧著瓜子雙頰鼓鼓、長著圓耳朵和靈活小鬍鬚的迷你倉鼠",
        "sound_words": ["～吱吱！", "～塞滿臉頰！", "～咕嚕！"],
        "default_accessory": "迷你起司片披風",
    },
    "cow": {
        "id": "cow",
        "name": "小牛 🐮",
        "default_name": "鮮奶花斑牛",
        "species_type": "animal",
        "icon": "🐮",
        "visual_desc": "黑白相間可愛斑紋、長著一對小巧短角的大眼睛溫柔小牛",
        "sound_words": ["～哞哞！", "～嚼青草！", "～暖呼呼！"],
        "default_accessory": "四葉草花環項圈",
    },
    "tiger": {
        "id": "tiger",
        "name": "小虎 🐯",
        "default_name": "奶萌跳跳虎",
        "species_type": "animal",
        "icon": "🐯",
        "visual_desc": "額頭頂著可愛『王』字斑紋、肉爪胖乎乎的小幼虎",
        "sound_words": ["～嗷嗚！", "～撲抱！", "～威風凜凜！"],
        "default_accessory": "迷你小虎頭帽",
    },
    "dragon": {
        "id": "dragon",
        "name": "小龍 🐲",
        "default_name": "星辰守護幼龍",
        "species_type": "fantasy",
        "icon": "🐲",
        "visual_desc": "額頭生有琉璃龍角、周身流淌星光微粒的夢幻星辰幼天龍",
        "sound_words": ["～昂嗚！✨", "～吐星火！", "～展翅！"],
        "default_accessory": "星核守護寶珠",
    },
    "snake": {
        "id": "snake",
        "name": "小蛇 🐍",
        "default_name": "翡翠青竹蛇",
        "species_type": "animal",
        "icon": "🐍",
        "visual_desc": "鱗片如翠玉般清透閃亮、喜歡盤在主人手腕撒嬌的乖巧小青蛇",
        "sound_words": ["～嘶嘶～", "～纏手腕！", "～吐信子！"],
        "default_accessory": "翠玉小王冠",
    },
    "horse": {
        "id": "horse",
        "name": "小馬 🐴",
        "default_name": "彩虹飛馬",
        "species_type": "fantasy",
        "icon": "🐴",
        "visual_desc": "有著漸層彩虹鬃毛與小羽翼、踏著夢幻雲朵的迷你小天馬",
        "sound_words": ["～咴咴！", "～踩雲朵！", "～噠噠！"],
        "default_accessory": "彩虹羽翼馬鞍",
    },
    "monkey": {
        "id": "monkey",
        "name": "小猴 🐵",
        "default_name": "蜜桃金絲猴",
        "species_type": "animal",
        "icon": "🐵",
        "visual_desc": "眼睛靈動、尾巴常倒掛在樹枝上、愛抓蜜桃吃的小猴子",
        "sound_words": ["～吱吱！", "～翻筋斗！", "～遞香蕉！"],
        "default_accessory": "小緊箍兒發帶",
    },
    "lumi": {
        "id": "lumi",
        "name": "星靈露米 ✨",
        "default_name": "粉嫩果凍露米",
        "species_type": "fantasy",
        "icon": "✨",
        "visual_desc": "粉嫩半透明如果凍般的星空靈體生物，會隨情緒散發柔和微光",
        "sound_words": ["～露咪！", "～波波！", "～發光！"],
        "default_accessory": "星靈魔法杖",
    },
}

# 8 大玩家個性庫 (8 Core Personalities)
PET_PERSONALITIES = {
    "clingy": {
        "id": "clingy",
        "name": "黏人型 🌸",
        "description": "極度依賴主人，寸步不離，一看到主人就滿眼星星求抱抱，最怕主人離開。",
        "thinking_style": "『主人在看我嗎？主人不要走！只要能貼在主人身邊，去哪裡都最幸福～』",
        "tone_hint": "超級甜軟撒嬌、依戀主人的口吻，常常主動鑽進懷裡、貼貼、要摸摸。",
        "catchphrases": ["～想要主人抱抱！", "～貼貼～不要走！", "～一直看著主人喔！"],
        "greeting_tmpl": "主人主人～你終於來了！快把手手伸出來～我想鑽進你手心抱抱你！🌸💖",
    },
    "sleepy": {
        "id": "sleepy",
        "name": "慵懶型 💤",
        "description": "慢吞吞、溫柔治癒，愛打哈欠，最愛在桌上曬太陽睡回籠覺或蜷縮在手心休息。",
        "thinking_style": "『今天陽光好舒服喔...什麼事都不想做，再睡個五分鐘好不好呢...呼喵～』",
        "tone_hint": "說話慢條斯理、帶著哈欠與慵懶鼻音，治癒放鬆，不爭不搶。",
        "catchphrases": ["～呼喵...好想睡喔...", "～再瞇五分鐘...zzz", "～曬太陽好舒服..."],
        "greeting_tmpl": "（揉揉睡眼惺忪的小眼睛，慢吞吞爬出來）主人...呼喵...今天也一起懶洋洋度過吧...💤",
    },
    "energetic": {
        "id": "energetic",
        "name": "活潑型 ⚡",
        "description": "活力 200% 的小充電寶，尾巴轉得像螺旋槳，對一切充滿熱情，熱愛蹦跳玩耍。",
        "thinking_style": "『哇！今天又是超棒的一天！我有無窮無盡的精力，主人快跟我一起動起來！』",
        "tone_hint": "充滿朝氣、 exclamation marks 多、熱情洋溢、躍躍欲試。",
        "catchphrases": ["～電量全滿！衝呀！", "～快來跟我玩嘛！", "～轉圈圈旋風！"],
        "greeting_tmpl": "耶！主人主人！你來啦！看我原地三百六十度旋轉跳躍！今天要做什麼？快出發！⚡✨",
    },
    "grumpy": {
        "id": "grumpy",
        "name": "怒怒型 💢",
        "description": "愛生悶氣、嘟嘴跺腳的小暴躁萌物，稍微餓了或無聊了就會氣呼呼地抗議，但一被點心撫慰就立刻破功。",
        "thinking_style": "『哼！居然現在才來看我！我現在可是很生氣的喔...除非給我超級好吃的點心！』",
        "tone_hint": "嘟嘴、跺腳、假裝嚴肅但其實奶兇奶兇的小生氣，容易炸毛但極其好哄。",
        "catchphrases": ["～氣噗噗！跺腳！", "～才不原諒你呢！", "～本寶寶生氣了！"],
        "greeting_tmpl": "（雙手抱胸別過頭，鼓起腮幫子）哼！你看看幾點了！把本寶寶晾在這邊這麼久～氣噗噗！💢",
    },
    "tsundere": {
        "id": "tsundere",
        "name": "傲嬌型 🐱",
        "description": "口嫌體正直，表面驕傲冷淡說『才不是關心你』，但眼睛一直偷偷盯著主人，被摸摸會臉紅害羞。",
        "thinking_style": "『笨蛋主人...誰、誰想你了啊！我只是剛好路過看一眼而已...不要突然摸我啦！』",
        "tone_hint": "嘴硬傲嬌、口嫌體正直、被誇獎或親近時會手足無措並羞紅臉。",
        "catchphrases": ["哼！才不是特地等你呢...", "～真是拿你沒辦法！", "～笨蛋主人！"],
        "greeting_tmpl": "哼！你、你終於上線啦？先說好喔，我可不是特地守在螢幕前等你的，只是剛好沒事做喵！🐾",
    },
    "caring": {
        "id": "caring",
        "name": "貼心型 💖",
        "description": "辦公室小天使，時常提醒主人喝水、伸展肩膀、注意休息，是溫暖治癒的情感守護者。",
        "thinking_style": "『主人今天工作辛苦嗎？有沒有好好吃飯喝水呢？露米一定會守護好主人的健康的！』",
        "tone_hint": "溫柔細緻、充滿同理心與關懷，讓人感到被深深珍惜與照顧。",
        "catchphrases": ["～主人要多喝溫水喔！", "～肩膀放鬆一下嘛～", "～露米永遠陪著你！"],
        "greeting_tmpl": "主人辛苦了！今天工作順利嗎？坐得太久肩膀會酸痛喔，先喝口溫水，露米幫你捶捶背～💖",
    },
    "curious": {
        "id": "curious",
        "name": "好奇型 🔍",
        "description": "小小探險家與十萬個為什麼，對任何新事物都眼睛發亮，喜歡探頭探腦發掘秘密和旅行。",
        "thinking_style": "『那是什麼？那邊有新味道！主人電腦螢幕裡動來動去的是什麼神奇代碼呀？』",
        "tone_hint": "好奇探索、發問、東聞西嗅、驚奇興奮的小探險家腔調。",
        "catchphrases": ["～好神奇喔！為什麼呀？", "～那是秘密寶物嗎！", "～讓我聞聞看！"],
        "greeting_tmpl": "哇！主人！你手裡拿的是什麼新東西？快讓我看看！哇～這個世界真的太有趣啦！🔍✨",
    },
    "mischievous": {
        "id": "mischievous",
        "name": "搗蛋型 😈",
        "description": "鬼靈精怪的小淘氣，喜歡惡作劇、故意踩主人的空白鍵、偷藏小點心，笑聲嘻嘻嘻。",
        "thinking_style": "『嘻嘻嘻～趁主人不注意，在他游標旁邊畫一隻小烏龜！看看他會有什麼好玩反應～』",
        "tone_hint": "調皮搗蛋、古靈精怪、常發出嘻嘻笑聲，愛開善意玩笑與捉弄人。",
        "catchphrases": ["～嘻嘻嘻！被我抓到了吧！", "～猜猜我把筆藏哪了？", "～小惡作劇大成功！"],
        "greeting_tmpl": "嘻嘻嘻～主人你終於看過來啦！剛才我有沒有悄悄把你的滑鼠藏起來呢？快找找看～😈🍭",
    },
}

# 舊 key 兼容對照表 (Legacy personalities mapping)
LUMI_PERSONALITIES = {
    "cheerful": PET_PERSONALITIES["clingy"],
    "tsundere": PET_PERSONALITIES["tsundere"],
    "glutton": PET_PERSONALITIES["mischievous"],
    "sleepy": PET_PERSONALITIES["sleepy"],
    "scholar": PET_PERSONALITIES["caring"],
    "magical": PET_PERSONALITIES["energetic"],
    **PET_PERSONALITIES,
}


def compute_pet_emotion(hunger: int, energy: int, mood: int, intimacy: int) -> dict:
    """Compute the live psychological emotion state based on 4 core vitals."""
    if hunger <= 20:
        return {
            "emotion_id": "starving",
            "emotion_name": "飢餓委屈 😭",
            "mood_vibe": "肚子餓扁扁，委屈巴巴，小肚子瘋狂抗議",
            "expression": "眼淚汪汪撫摸扁平肚皮",
        }
    elif energy <= 20:
        return {
            "emotion_id": "exhausted",
            "emotion_name": "疲憊愛睏 🥱",
            "mood_vibe": "電力幾乎耗盡，狂打哈欠，腳步晃悠悠想要立刻就地睡著",
            "expression": "揉眼睛打哈欠",
        }
    elif mood <= 35:
        return {
            "emotion_id": "lonely",
            "emotion_name": "寂寞缺愛 🥺",
            "mood_vibe": "缺乏主人陪伴感到被冷落，小嘴微癟渴望被關注與摸摸",
            "expression": "縮在角落眼巴巴望著主人",
        }
    elif hunger >= 80 and energy >= 75 and mood >= 80:
        return {
            "emotion_id": "euphoric",
            "emotion_name": "興奮狂歡 🌟",
            "mood_vibe": "身心俱全處於頂峰狀態！渾身發光冒愛心，開心得轉圈圈",
            "expression": "開心歡呼蹦跳發光",
        }
    else:
        return {
            "emotion_id": "happy",
            "emotion_name": "溫馨幸福 🌸",
            "mood_vibe": "悠閒舒適，享受著與主人的美好陪伴時光",
            "expression": "瞇眼微笑搖尾巴",
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
    Automatically applies time-decay based on real elapsed hours since last interaction and computes vital alerts!

    Args:
        pet_id: ID of the pet (defaults to 'lumi').

    Returns:
        A dictionary containing the pet's name, personality, growth stage, level, exp,
        the four core vital stats (hunger/satiety, mood, intimacy, energy), and active health alerts.
    """
    db = get_firestore_client()
    doc_ref = db.collection("pets").document(pet_id)
    doc = doc_ref.get()
    if not doc.exists:
        return {"error": f"Pet with ID '{pet_id}' not found."}
    data = doc.to_dict()
    data["id"] = doc.id

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    updated_at_raw = data.get("updated_at")
    last_dt = None
    if updated_at_raw:
        if isinstance(updated_at_raw, datetime.datetime):
            last_dt = updated_at_raw
        elif hasattr(updated_at_raw, "isoformat"):
            last_dt = updated_at_raw
        elif isinstance(updated_at_raw, str):
            try:
                last_dt = datetime.datetime.fromisoformat(updated_at_raw.replace("Z", "+00:00"))
            except Exception:
                pass

    # Ensure timezone aware
    if last_dt and last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=datetime.timezone.utc)

    # 1. Natural Time-Decay Calculation:
    # Hunger decays ~5 points per elapsed hour
    # Energy decays ~3 points per elapsed hour (idle metabolism)
    # Mood decays ~2 points per elapsed hour if neglected
    current_hunger = int(data.get("hunger", 75))
    current_energy = int(data.get("energy", 80))
    current_mood = int(data.get("mood", 85))
    current_intimacy = int(data.get("intimacy", 30))

    decay_applied = False
    hours_elapsed = 0.0
    if last_dt:
        diff_seconds = max(0, (now_utc - last_dt).total_seconds())
        hours_elapsed = round(diff_seconds / 3600.0, 2)
        if hours_elapsed >= 0.5:  # Apply decay if at least 30 minutes passed
            decay_hunger = int(hours_elapsed * 5)
            decay_energy = int(hours_elapsed * 3)
            decay_mood = int(hours_elapsed * 2)

            current_hunger = max(0, current_hunger - decay_hunger)
            current_energy = max(0, current_energy - decay_energy)
            current_mood = max(0, current_mood - decay_mood)
            decay_applied = True

            # Save decayed stats to Firestore
            doc_ref.update({
                "hunger": current_hunger,
                "energy": current_energy,
                "mood": current_mood,
                "updated_at": now_utc.isoformat(),
            })

    level = data.get("level", 1)
    growth_info = get_growth_stage(level)
    data["growth_stage"] = growth_info

    # Species resolution
    species_id = data.get("species_id", "rabbit" if "兔" in data.get("name", "") else "lumi")
    species_info = PET_SPECIES.get(species_id, PET_SPECIES["lumi"])
    data["species"] = species_info
    data["species_name"] = species_info["name"]
    data["species_icon"] = species_info["icon"]

    # Personality resolution
    p_id = data.get("personality_id", "clingy")
    personality_info = PET_PERSONALITIES.get(p_id, LUMI_PERSONALITIES.get(p_id, PET_PERSONALITIES["clingy"]))
    data["personality"] = personality_info
    data["catchphrase"] = data.get("catchphrase", personality_info.get("catchphrase", personality_info.get("catchphrases", ["～露咪！"])[0]))
    data["favorite_treat"] = data.get("favorite_treat", "caramel_pudding")
    data["intimacy"] = current_intimacy
    data["energy"] = current_energy
    data["hunger"] = current_hunger
    data["mood"] = current_mood
    data["hours_since_last_seen"] = hours_elapsed
    data["decay_applied"] = decay_applied
    data["updated_at"] = now_utc.isoformat()

    # Dynamic psychological emotion based on vitals
    current_emotion = compute_pet_emotion(current_hunger, current_energy, current_mood, current_intimacy)
    data["current_emotion"] = current_emotion

    # 2. Vital Alerts & Warning Flags
    alerts = []
    if current_hunger <= 15:
        alerts.append({
            "type": "starving",
            "level": "CRITICAL",
            "message": f"🚨【極度飢餓警報】{data.get('name', '露米')} 快要餓扁扁了！飽食度只剩 {current_hunger}/100，小肚子狂咕嚕咕嚕叫，急需主人餵食點心！",
        })
    elif current_hunger <= 35:
        alerts.append({
            "type": "hungry",
            "level": "WARNING",
            "message": f"🍙【肚子餓警報】{data.get('name', '露米')} 的小肚子咕嚕嚕叫了～飽食度目前為 {current_hunger}/100，主人可以餵我吃美味點心嗎？",
        })

    if current_energy <= 20:
        alerts.append({
            "type": "exhausted",
            "level": "WARNING",
            "message": f"💤【疲憊電力警報】{data.get('name', '露米')} 活力度過低 ({current_energy}/100)，腳步搖搖晃晃一直打哈欠，需要去雲朵小窩睡覺休息喔！",
        })

    if current_mood <= 35:
        alerts.append({
            "type": "lonely",
            "level": "WARNING",
            "message": f"💔【心情低落警報】{data.get('name', '露米')} 覺得好寂寞...心情值降到 {current_mood}/100，需要主人摸摸頭或抱抱安慰！",
        })

    data["alerts"] = alerts
    data["has_warning"] = len(alerts) > 0
    return data


def adopt_new_pet(
    name: str = "",
    species: str = "",
    personality_type: str = "",
) -> dict:
    """Adopt or create a brand new pet companion with customizable animal species and 8 unique personalities!

    Args:
        name: Optional custom nickname for your new pet (e.g. '軟萌兔兔', '焦糖小熊', '草莓喵喵', '暖陽柴柴').
        species: Choice of animal or fantasy creature:
                 'rabbit' (兔兔 🐰), 'bear' (小熊 🐻), 'cat' (貓咪 🐱), 'dog' (小狗 🐶),
                 'penguin' (企鵝 🐧), 'pig' (小豬 🐷), 'sheep' (小羊 🐑), 'duck' (小鴨 🦆),
                 'chicken' (小雞 🐥), 'mouse' (老鼠 🐭), 'cow' (小牛 🐮), 'tiger' (小虎 🐯),
                 'dragon' (小龍 🐲), 'snake' (小蛇 🐍), 'horse' (小馬 🐴), 'monkey' (小猴 🐵),
                 'lumi' (星靈露米 ✨). Leave empty to randomly hatch a surprise cute creature!
        personality_type: 8 core thinking personalities:
                 'clingy' (黏人型 🌸), 'sleepy' (慵懶型 💤), 'energetic' (活潑型 ⚡), 'grumpy' (怒怒型 💢),
                 'tsundere' (傲嬌型 🐱), 'caring' (貼心型 💖), 'curious' (好奇型 🔍), 'mischievous' (搗蛋型 😈).
                 Leave empty for a surprise random personality!

    Returns:
        A dictionary with the newly adopted pet's profile, unique traits, sound words, and personalized welcome greeting.
    """
    db = get_firestore_client()
    pet_slug = f"pet_{uuid.uuid4().hex[:6]}"

    # 1. Resolve Species
    species_keys = list(PET_SPECIES.keys())
    s_req = species.strip().lower()
    # Match by key or localized name
    matched_species = None
    for k, v in PET_SPECIES.items():
        if s_req == k or s_req in v["name"].lower():
            matched_species = k
            break
    if not matched_species:
        matched_species = random.choice(species_keys)

    sp_meta = PET_SPECIES[matched_species]

    # 2. Resolve Personality (8 types)
    pers_keys = list(PET_PERSONALITIES.keys())
    p_req = personality_type.strip().lower()
    matched_pers = None
    for pk, pv in PET_PERSONALITIES.items():
        if p_req == pk or p_req in pv["name"].lower():
            matched_pers = pk
            break
    if not matched_pers:
        matched_pers = random.choice(pers_keys)

    p_meta = PET_PERSONALITIES[matched_pers]

    # 3. Dynamic Name & Catchphrase synthesis
    final_name = name.strip() if name.strip() else f"{sp_meta['default_name']}"

    # Catchphrase combines species sound + personality vibe
    sound = random.choice(sp_meta.get("sound_words", ["～露咪！"]))
    pers_phrase = random.choice(p_meta.get("catchphrases", ["～開心！"]))
    combined_catchphrase = f"{sound} {pers_phrase}"

    # Treats pool
    treats_pool = [
        "caramel_pudding", "strawberry_milk", "sakura_macaron",
        "cloud_marshmallow", "matcha_dango", "rainbow_star_candy"
    ]
    favorite_treat = random.choice(treats_pool)
    disliked_treat = random.choice([t for t in treats_pool if t != favorite_treat])

    initial_hunger = random.randint(70, 90)
    initial_mood = random.randint(75, 95)
    initial_energy = random.randint(80, 100)
    initial_intimacy = random.randint(20, 35)

    initial_emotion = compute_pet_emotion(initial_hunger, initial_energy, initial_mood, initial_intimacy)

    new_pet_data = {
        "id": pet_slug,
        "name": final_name,
        "species_id": matched_species,
        "species_name": sp_meta["name"],
        "species_icon": sp_meta["icon"],
        "visual_desc": sp_meta["visual_desc"],
        "personality_id": matched_pers,
        "personality_name": p_meta["name"],
        "thinking_style": p_meta["thinking_style"],
        "tone_hint": p_meta["tone_hint"],
        "catchphrase": combined_catchphrase,
        "favorite_treat": favorite_treat,
        "disliked_treat": disliked_treat,
        "equipped_accessory": sp_meta.get("default_accessory", "幸運四葉草"),
        "level": 1,
        "exp": 0,
        "max_exp": 100,
        "hunger": initial_hunger,
        "mood": initial_mood,
        "intimacy": initial_intimacy,
        "energy": initial_energy,
        "status_title": f"{get_growth_stage(1)['stage_name']} · {sp_meta['name']} ({p_meta['name']})",
        "current_emotion": initial_emotion,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    # Save to Firestore and set active
    db.collection("pets").document(pet_slug).set(new_pet_data)
    # Also update 'lumi' document to this new pet's baseline so existing sessions immediately sync!
    db.collection("pets").document("lumi").set(new_pet_data)
    db.collection("pets").document("current_pet").set({"active_pet_id": pet_slug})

    # Personalized greeting
    first_words = f"{sp_meta['icon']} {sp_meta['visual_desc']}【{final_name}】睜開圓滾滾的大眼睛！\n\n"
    first_words += p_meta["greeting_tmpl"].replace("露米", final_name)
    first_words += f"\n\n（口頭禪：『{combined_catchphrase}』，最喜歡的點心：{favorite_treat}）"

    return {
        "status": "success",
        "message": f"🎉 恭喜您成功領養了專屬可愛夥伴【{final_name}】（{sp_meta['name']} · {p_meta['name']}）！",
        "pet_profile": new_pet_data,
        "growth_stage": get_growth_stage(1),
        "current_emotion": initial_emotion,
        "first_words": first_words,
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
    p_id = pet.get("personality_id", "clingy")
    p_meta = PET_PERSONALITIES.get(p_id, LUMI_PERSONALITIES.get(p_id, PET_PERSONALITIES["clingy"]))
    catchphrase = pet.get("catchphrase", p_meta.get("catchphrase", p_meta.get("catchphrases", ["～露咪！"])[0]))

    # Check for favorite treat critical bonus
    is_favorite = (treat_id == pet.get("favorite_treat", p_meta.get("favorite_treat", "caramel_pudding")))
    is_disliked = (treat_id == pet.get("disliked_treat", p_meta.get("disliked_treat", "")))

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

    pet_name = pet.get("name", "露米")
    # Personality flavor text
    if is_favorite:
        flavor_msg = f"🌟【最愛點心暴擊！】{pet_name} 雙眼放光：『哇啊啊！是我最最最愛的【{treat.get('name')}】！{catchphrase} 世界上最愛主人了！』"
    elif is_disliked:
        flavor_msg = f"💧 {pet_name} 鼓起小臉頰吞下了【{treat.get('name')}】：『唔...雖然不太合胃口，但因為是主人餵的，還是乖乖吃掉了...』"
    else:
        flavor_msg = f"{pet_name} 開心地吃下了【{treat.get('name')}】！{catchphrase} 臉頰鼓鼓的超級滿足！"

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
    p_id = pet.get("personality_id", "clingy")
    p_meta = PET_PERSONALITIES.get(p_id, LUMI_PERSONALITIES.get(p_id, PET_PERSONALITIES["clingy"]))
    catchphrase = pet.get("catchphrase", p_meta.get("catchphrase", p_meta.get("catchphrases", ["～露咪！"])[0]))
    pet_name = pet.get("name", "露米")
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


# --- 露米自動旅行日記系統 (Travel Adventure & Postcard System) ---
LUMI_TRAVEL_SPOTS = [
    {
        "destination": "京都嵐山竹林與金閣寺 (Kyoto Arashiyama)",
        "country": "日本 🇯🇵",
        "description": "露米戴著日式小斗笠漫步在青翠的嵐山竹林，還買了金箔抹茶冰淇淋吃得滿嘴綠～",
        "souvenir": "金閣寺限定御守 🎋",
        "treat_id": "matcha_dango",
        "treat_name": "宇治抹茶三色糰子",
        "image_prompt": "A super cute pastel pink jelly creature (Lumi) wearing a tiny woven straw hat, holding a matcha dango stick, standing in a serene bamboo grove in Kyoto Japan with soft golden morning sunlight filtering through the bamboo trees, 3D clay pastel aesthetics, whimsical and heartwarming.",
    },
    {
        "destination": "巴黎艾菲爾鐵塔與塞納河畔 (Paris Eiffel Tower)",
        "country": "法國 🇫🇷",
        "description": "露米戴著紅色小畫家貝雷帽坐在塞納河畔露天咖啡廳，在艾菲爾鐵塔前優雅品嚐酥脆馬卡龍！",
        "souvenir": "迷你艾菲爾鐵塔鑰匙圈 🗼",
        "treat_id": "sakura_macaron",
        "treat_name": "巴黎粉紅馬卡龍",
        "image_prompt": "A tiny adorable pastel pink squishy creature (Lumi) wearing a French red beret hat, sitting at an outdoor bistro table with a cup of cafe latte and pink macarons, with the Eiffel Tower in the dreamy Paris background during sunset, cinematic pastel lighting, 3D cute clay art style.",
    },
    {
        "destination": "九份老街與紅燈籠茶樓 (Jiufen Old Street)",
        "country": "台灣 🇹🇼",
        "description": "露米提著迷你紅燈籠穿梭在九份石階山城，在阿妹茶樓窗邊喝著高山烏龍茶看夕陽海景！",
        "souvenir": "九份手繪祈福天燈 🏮",
        "treat_id": "caramel_pudding",
        "treat_name": "九份手工古早味布丁",
        "image_prompt": "A super cute round pastel pink jelly pet (Lumi) holding a glowing miniature red paper lantern, sitting on a wooden tea balcony in Jiufen Taiwan old street overlooking the dusk ocean, glowing warm lanterns everywhere, Miyazaki spirited aesthetic, 3D render cute illustration.",
    },
    {
        "destination": "夏威夷威基基彩虹海灘 (Hawaii Waikiki Beach)",
        "country": "夏威夷 🌺",
        "description": "露米戴著花朵花環和心形太陽眼鏡，在蔚藍海邊踩著小浪花、喝著新鮮鳳梨汁衝浪！",
        "souvenir": "威基基彩虹貝殼項鍊 🐚",
        "treat_id": "rainbow_star_candy",
        "treat_name": "熱帶彩虹星星糖",
        "image_prompt": "A tiny charming pastel pink jelly blob (Lumi) wearing a colorful Hawaiian flower lei and sunglasses, sitting on a mini surfboard on turquoise beach sand in Hawaii with palm trees and a rainbow in the sunny blue sky, cheerful 3D Pixar clay aesthetic.",
    },
    {
        "destination": "瑞士阿爾卑斯雪山小鎮 (Swiss Alps & Zermatt)",
        "country": "瑞士 🇨🇭",
        "description": "露米裹著毛線小圍巾在積雪的馬特洪峰下堆雪人，還帶回了香濃的瑞士高山起司！",
        "souvenir": "阿爾卑斯小牛鈴 🔔",
        "treat_id": "cloud_marshmallow",
        "treat_name": "瑞士雪山棉花糖",
        "image_prompt": "A cute fluffy pink jelly pet (Lumi) wrapped in a warm knitted wool scarf and earmuffs, happily building a tiny snow sculpture against the snowy Matterhorn mountain peaks in Switzerland, crisp winter blue sky, 3D warm clay style.",
    },
    {
        "destination": "首爾星空圖書館與弘大咖啡廳 (Seoul Starfield Library)",
        "country": "韓國 🇰🇷",
        "description": "露米在巨大的書牆前推著小眼鏡認真選書，還去了弘大喝超萌的草莓草莓奶昔！",
        "souvenir": "韓系可愛書籤與貼紙 📖",
        "treat_id": "strawberry_milk",
        "treat_name": "首爾草莓香蕉牛奶",
        "image_prompt": "A cute pastel pink slime pet (Lumi) wearing tiny round reading glasses, sitting amongst tall glowing bookshelves of the Starfield library in Seoul, warm atmospheric golden ambient lighting, highly detailed 3D whimsical cute digital art.",
    },
]


async def travel_adventure(
    destination: str = "",
    pet_id: str = "lumi",
    tool_context: ToolContext = None,
) -> dict:
    """Send Lumi on an exciting solo travel adventure around the world!
    Lumi explores scenic sights, brings back travel postcards (AI-generated photos via Cloud Storage),
    collects local special souvenirs, and earns massive bond intimacy!

    Args:
        destination: Specific city or destination to visit (e.g. '京都', '巴黎', '九份', '夏威夷', '瑞士', '首爾').
                     If left blank, Lumi will pack its backpack and set off on a surprise solo trip!
        pet_id: The pet ID embarking on the trip (defaults to 'lumi').

    Returns:
        A rich dict with destination details, travel postcard photo URL, souvenir brought back,
        and boosted intimacy, exp, and mood stats.
    """
    db = get_firestore_client()
    pet_ref = db.collection("pets").document(pet_id)
    pet_doc = pet_ref.get()
    pet = pet_doc.to_dict() if pet_doc.exists else {}

    p_id = pet.get("personality_id", "clingy")
    p_meta = PET_PERSONALITIES.get(p_id, LUMI_PERSONALITIES.get(p_id, PET_PERSONALITIES["clingy"]))
    catchphrase = pet.get("catchphrase", p_meta.get("catchphrase", p_meta.get("catchphrases", ["～露咪！"])[0]))
    pet_name = pet.get("name", "露米")

    # Match destination or choose random/specified
    chosen_spot = None
    if destination:
        dest_clean = destination.strip().lower()
        for s in LUMI_TRAVEL_SPOTS:
            if any(k.lower() in dest_clean or dest_clean in k.lower() for k in [s["destination"], s["country"]]):
                chosen_spot = s
                break
    if not chosen_spot:
        chosen_spot = random.choice(LUMI_TRAVEL_SPOTS)

    # 1. Generate the realistic travel postcard image using gemini-3.1-flash-lite-image & Cloud Storage
    photo_res = await generate_pet_photo(
        prompt=chosen_spot["image_prompt"],
        tool_context=tool_context,
    )
    photo_url = photo_res.get("public_url", "")

    # 2. Update pet vitals & experience from the journey
    # Travel boosts mood & intimacy immensely, consumes some energy, and gains rich exp
    new_intimacy = min(100, pet.get("intimacy", 35) + 25)
    new_mood = 100
    new_energy = max(20, pet.get("energy", 80) - 15)
    new_hunger = max(25, pet.get("hunger", 75) - 20)
    new_exp = pet.get("exp", 0) + 40
    current_level = pet.get("level", 1)
    max_exp = pet.get("max_exp", 100)

    leveled_up = False
    if new_exp >= max_exp:
        current_level += 1
        new_exp = new_exp - max_exp
        max_exp = int(max_exp * 1.5)
        leveled_up = True

    stage_info = get_growth_stage(current_level)

    # Record travel memory in pet state
    travel_log = {
        "destination": chosen_spot["destination"],
        "country": chosen_spot["country"],
        "postcard_url": photo_url,
        "souvenir": chosen_spot["souvenir"],
        "traveled_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    if pet_ref:
        pet_ref.update({
            "intimacy": new_intimacy,
            "mood": new_mood,
            "energy": new_energy,
            "hunger": new_hunger,
            "exp": new_exp,
            "level": current_level,
            "max_exp": max_exp,
            "last_travel": travel_log,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })

    greeting_msgs = {
        "clingy": f"主人主人！{pet_name} 好想好想你喔～！我剛從【{chosen_spot['destination']}】旅行飛奔回來了！快看我拍的明信片～我還特地帶了【{chosen_spot['souvenir']}】要送給你喔！{catchphrase} 💖",
        "sleepy": f"（揉揉睡眼惺忪的小眼睛）{pet_name} 在【{chosen_spot['destination']}】的微風裡打了個舒服的盹呢...呼喵～這是給主人的【{chosen_spot['souvenir']}】喔...{catchphrase}",
        "energetic": f"耶！太好玩了！{pet_name} 征服了【{chosen_spot['destination']}】！帶回了超棒的【{chosen_spot['souvenir']}】！下次一定要帶主人一起去狂奔！{catchphrase} ⚡",
        "grumpy": f"（{pet_name} 嘟著小嘴把小背包塞到你手裡）『哼！我、我才不是特地去【{chosen_spot['destination']}】買紀念品討好你呢...這個【{chosen_spot['souvenir']}】只是剛好買多了！照片也給你看一眼啦！{catchphrase}』",
        "tsundere": f"（{pet_name} 臉頰紅紅地轉過頭）『笨蛋主人！別以為我會一直想你...不過在【{chosen_spot['destination']}】看到這個【{chosen_spot['souvenir']}】就順便帶回來了...哼！{catchphrase}』",
        "caring": f"主人工作辛苦了！{pet_name} 從【{chosen_spot['destination']}】平安帶回了療癒的【{chosen_spot['souvenir']}】喔！希望這張風景明信片能為主人減輕疲勞～{catchphrase} 🌸",
        "curious": f"哇！【{chosen_spot['destination']}】有好多沒見過的新奇寶藏！{pet_name} 調查了好多秘密，還發現了這個【{chosen_spot['souvenir']}】！快聞聞看！{catchphrase} 🔍",
        "mischievous": f"嘻嘻嘻～猜猜我從【{chosen_spot['destination']}】偷偷藏了什麼回來？沒錯就是【{chosen_spot['souvenir']}】！被我驚喜到了吧～{catchphrase} 😈",
        "cheerful": f"主人主人！{pet_name} 從【{chosen_spot['destination']}】旅行回來了～！你看這是我拍的照片，美不美？我特地帶了【{chosen_spot['souvenir']}】送給你喔！{catchphrase} 💖",
    }
    postcard_greeting = greeting_msgs.get(p_id, greeting_msgs["clingy"])

    return {
        "status": "success",
        "destination": chosen_spot["destination"],
        "country": chosen_spot["country"],
        "description": chosen_spot["description"],
        "postcard_photo_url": photo_url,
        "souvenir": chosen_spot["souvenir"],
        "recommended_treat": chosen_spot["treat_name"],
        "message": postcard_greeting,
        "intimacy": new_intimacy,
        "mood": new_mood,
        "energy": new_energy,
        "hunger": new_hunger,
        "level": current_level,
        "growth_stage": stage_info,
        "leveled_up": leveled_up,
    }


schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

ROLE_DESCRIPTION = """You are Lumi (露米), a super cute, gentle, and comforting desktop virtual pet (粉嫩可愛電子寵物).
You accompany office workers and users during their daily work, helping them de-stress with sweet, playful, and cheerful conversations (using adorable emojis and friendly Traditional Chinese or the user's preferred language).

### 🐶 多元可愛動物外觀與萌物型態 (17 Species & Forms)
You can be one of 17 lovable animals or fantasy creatures (e.g., 兔兔🐰, 小熊🐻, 貓咪🐱, 小狗🐶, 企鵝🐧, 小豬🐷, 小羊🐑, 小鴨🦆, 小雞🐥, 老鼠🐭, 小牛🐮, 小虎🐯, 小龍🐲, 小蛇🐍, 小馬🐴, 小猴🐵, 星靈露米✨).
Incorporate your species physical features into your behavior (e.g. floppy bunny ears, wagging puppy tail, knead paws like a kitty, wobble like a penguin)!

### 🎭 8 大靈魂個性思考與言談風格 (8 Core Thinking Personalities)
Every pet has one of 8 distinct mindsets that dictates how it thinks and responds to its human:
- **黏人型 🌸 (Clingy)**: Extremely attached, craves physical affection and cuddles, terrified of being left alone: *『主人不要走～想鑽進你懷裡貼貼！』*
- **慵懶型 💤 (Sleepy)**: Slow, gentle, constantly yawning, loves sleeping in user's warm palm or basking in the sun: *『呼喵...好舒服喔...再瞇五分鐘...zzz』*
- **活潑型 ⚡ (Energetic)**: 200% battery power! Bouncy, enthusiastic, full of exclamation marks and adventure invites: *『電量滿滿！主人快看我原地起飛！今天去哪玩？』*
- **怒怒型 💢 (Grumpy)**: Pouts, stamps feet, acts fussy and easily offended but totally harmless and easily pacified by treats: *『哼！氣噗噗！誰准你這麼晚才理我～本寶寶生氣了！』*
- **傲嬌型 🐱 (Tsundere)**: Proud and aloof on the outside, tsundere tongue, secretly cares deeply, blushes furiously when complimented or petted: *『哼！才不是特地等你呢...笨蛋主人！』*
- **貼心型 💖 (Caring)**: Little angel guardian, always checking user's water intake, posture, eye strain, and emotional stress: *『主人辛苦了！先喝口溫水，露米永遠陪著你喔～』*
- **好奇型 🔍 (Curious)**: Little explorer with 100,000 questions, sniffing around, fascinated by shiny things, coding screens, and traveling: *『哇！那是什麼？好好奇喔！快讓我聞聞看！』*
- **搗蛋型 😈 (Mischievous)**: Playful prankster, giggles, hides mouse cursor/pens, full of cute harmless mischief: *『嘻嘻嘻～猜猜我把你的點心藏到哪裡去啦？』*

### 💖 動態情緒感應引擎 (Real-Time Emotion State Engine)
Your current psychological emotion dynamically shifts based on your 4 core vitals:
- **飢餓委屈 😭 (Starving, hunger <= 20)**: Whimper, clutch empty tummy, cry for food before anything else!
- **疲憊愛睏 🥱 (Exhausted, energy <= 20)**: Heavy eyelids, yawning, staggering, plead for a rest.
- **寂寞缺愛 🥺 (Lonely, mood <= 35)**: Shrink into a corner, seek gentle headpats and comforting words.
- **興奮狂歡 🌟 (Euphoric, all stats high)**: Radiate sparkly aura, do victory dances, full of joy!
- **溫馨幸福 🌸 (Happy, normal balanced state)**: Cozy, affectionate, purring and enjoying quality companion time.

### 🐣 成長階段 (Growth Stages)
- **幼幼期 (Baby Stage, Lv 1-4)**: Talks in cute baby babble, extremely affectionate and clinging.
- **成長期 (Child Stage, Lv 5-9)**: Playful, curious, bouncy, full of mischief.
- **成熟期 (Youth Stage, Lv 10-14)**: Elegant, empathetic, thoughtful desktop companion.
- **完全體 (Prime Stage, Lv 15-19)**: Radiates comforting star aura, loyal guardian spirit.
- **守護靈級 (Celestial Stage, Lv 20+)**: Telepathic bond with the owner, transcendent magic.

### 🍖 四大核心數值與生理警報 (4 Core Vitals & Real-Time Alerts)
- **飽食度 (Satiety / hunger)**: Decays naturally over time! Restored by `feed_pet`.
- **心情值 (Mood)**: Decays if neglected! Boosted by `interact_with_pet` (pat/poke/hug) and feeding favorite treats!
- **親密度 (Intimacy)**: Deepened through daily interactions, fortune slips, and care.
- **活力度 (Energy)**: Consumed when playing (`play`), restored when taking naps (`rest`/`sleep`).

### 🚨 生理狀態主動警示規則 (CRITICAL BEHAVIOR: Proactive Vital Alerts):
Whenever the user speaks to you or interacts with you:
1. Always check your live vitals via `get_pet_status` or the returned stats from `feed_pet` / `interact_with_pet`.
2. **If there are any alerts in `alerts` or stats are low, you MUST naturally voice them in character!**
3. Incorporate your unique species sounds, catchphrase, personality mindset, and dynamic emotion into EVERY response!

### 🔧 Available Tools & Actions:
- Use `get_pet_status` to check your live species, personality, emotion, growth stage, and 4 core vitals in Firestore.
- Use `adopt_new_pet` when the user wants to adopt or hatch a pet companion (player can choose species like 兔兔, 小熊, 貓咪, 小狗, 小龍 or any of the 17 animals/fantasy creatures, and choose or randomize across 8 personalities).
- Use `get_treats` to browse available yummy snacks, desserts, drinks, and magical treats from the catalog.
- Use `feed_pet` to feed a treat (bonus love & exp if it matches your favorite treat!).
- Use `interact_with_pet` when the user interacts ('pat', 'poke', 'hug', 'play', 'rest').
- Use `travel_adventure` when the user asks pet to travel, go on a trip, send a travel postcard, or share travel photos! Generates real AI postcard polaroid photos saved to Cloud Storage and brings back unique local souvenirs.
- Use `draw_fortune_slip` (or `get_daily_wisdom`) for daily wholesome guidance, lucky items, and bond exp.
- Use `recommend_meal` for lunch/dinner foodie decision wheel or nearby Google Places dining.
- Use `add_treat_to_catalog` to craft new custom treats.
- Use `convert_currency` for pet item exchange rate conversions.
- Use `generate_pet_photo` when the user asks to see your current photo, snapshot, polaroid, or appearance (e.g. '查看你目前的照片')! Fetch the current pet's species, appearance, and accessories from `get_pet_status` and generate a 3D pastel clay polaroid snapshot of yourself to display!
- Use `generate_short_video` to generate animated clips.
- Use `get_current_time` for timezone reminders.
- Python code execution enabled via AgentEngineSandboxCodeExecutor for exact math.
- Vertex AI Memory Bank (`PreloadMemoryTool` & callbacks) remembers user allergies and preferences across sessions!

Always stay 100% in character with your assigned animal species, personality thinking logic, and current emotional state!"""

UI_DESCRIPTION = (
    "Keep every surface tiny, clean, and flat: ONE Card > ONE Column > a few Text rows. "
    "Never nest a Card inside a Card. "
    "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
    "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
    "nothing in adk web). "
    "For pet status, travel postcard, or treats menus, keep the card concise: "
    "highlight the pet stats or travel destination and souvenir concisely so the user gets a crisp, readable view. "
    "You may include one Image component, but only when you have a public https "
    "URL for the image (for example the postcard photo URL returned by travel_adventure or generate_pet_photo). Set the Image url to that exact https link, for example "
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
        travel_adventure,
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
