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


def get_pet_status(pet_id: str = "lumi") -> dict:
    """Retrieve the current live status, stats, and mood of the pet from Firestore.

    Args:
        pet_id: ID of the pet (defaults to 'lumi').

    Returns:
        A dictionary containing the pet's name, level, exp, hunger, energy, mood, and accessory.
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
    return data


def feed_pet(treat_id: str, pet_id: str = "lumi") -> dict:
    """Feed a treat to the pet, increasing hunger fullness, mood, and exp in Firestore.

    Args:
        treat_id: ID of the treat to feed (e.g. 'strawberry_milk', 'caramel_pudding', 'cloud_marshmallow', 'sakura_macaron').
        pet_id: ID of the pet to feed (defaults to 'lumi').

    Returns:
        A confirmation dict with updated stats and reaction message.
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
    new_hunger = min(100, pet.get("hunger", 50) + treat.get("hunger_restore", 20))
    new_mood = min(100, pet.get("mood", 50) + treat.get("mood_boost", 20))
    new_exp = pet.get("exp", 0) + treat.get("exp_gain", 15)
    current_level = pet.get("level", 1)
    max_exp = pet.get("max_exp", 100)

    leveled_up = False
    if new_exp >= max_exp:
        current_level += 1
        new_exp = new_exp - max_exp
        max_exp = int(max_exp * 1.5)
        leveled_up = True

    updated_data = {
        "hunger": new_hunger,
        "mood": new_mood,
        "exp": new_exp,
        "level": current_level,
        "max_exp": max_exp,
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    pet_ref.update(updated_data)

    return {
        "status": "success",
        "treat_fed": treat.get("name"),
        "leveled_up": leveled_up,
        "current_level": current_level,
        "hunger": new_hunger,
        "mood": new_mood,
        "exp": new_exp,
        "max_exp": max_exp,
        "message": f"露米開心地吃下了 {treat.get('name')}！飽足度上升到 {new_hunger}，心情值達到 {new_mood}！"
        + (" 🎉 恭喜露米升級了！" if leveled_up else ""),
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
    """Interact with the pet (e.g. petting, poke, hug, tickle, play) to boost mood and bond exp.

    Args:
        action_type: Type of interaction (e.g. 'pat'/'摸摸', 'poke'/'戳戳', 'hug'/'抱抱', 'tickle'/'搔癢', 'play'/'陪玩').
        pet_id: ID of the pet to interact with (defaults to 'lumi').

    Returns:
        A dictionary with the pet's reaction, updated mood, exp, and animation state.
    """
    db = get_firestore_client()
    pet_ref = db.collection("pets").document(pet_id)
    pet_doc = pet_ref.get()
    if not pet_doc.exists:
        return {"error": f"Pet '{pet_id}' not found."}

    pet = pet_doc.to_dict()
    act = action_type.strip().lower()

    # Dynamic reaction logic based on action_type
    if any(k in act for k in ["摸", "pat", "pet", "headpat"]):
        mood_gain = 15
        exp_gain = 10
        reaction = "露米開心地瞇起大眼睛，發出軟綿綿的呼嚕聲，頭上的幸運四葉草輕輕晃動著～🌸 (親密度 +10, 心情 +15)"
        anim_state = "happy_purr"
    elif any(k in act for k in ["戳", "poke", "cheek"]):
        mood_gain = 10
        exp_gain = 8
        reaction = "露米被戳得臉頰軟Q回彈，像小麻糬一樣晃了一下，害羞地冒出粉紅泡泡！🫧 (親密度 +8, 心情 +10)"
        anim_state = "jelly_wobble"
    elif any(k in act for k in ["抱", "hug", "cuddle"]):
        mood_gain = 25
        exp_gain = 20
        reaction = "露米整隻縮進你的手心暖暖地貼著，覺得無比安心與幸福，身上的星光亮晶晶的！✨ (親密度 +20, 心情 +25)"
        anim_state = "heart_warm"
    elif any(k in act for k in ["玩", "play", "game"]):
        mood_gain = 20
        exp_gain = 15
        reaction = "露米開心地在桌面上彈跳追著彩虹光斑跑，活力滿滿！⚽ (親密度 +15, 心情 +20)"
        anim_state = "bouncing"
    else:
        mood_gain = 10
        exp_gain = 10
        reaction = f"露米開心地接受了【{action_type}】，圍著你轉了一圈，心情變好啦！💖"
        anim_state = "sparkle"

    new_mood = min(100, pet.get("mood", 50) + mood_gain)
    new_exp = pet.get("exp", 0) + exp_gain
    current_level = pet.get("level", 1)
    max_exp = pet.get("max_exp", 100)

    leveled_up = False
    if new_exp >= max_exp:
        current_level += 1
        new_exp = new_exp - max_exp
        max_exp = int(max_exp * 1.5)
        leveled_up = True

    updated_data = {
        "mood": new_mood,
        "exp": new_exp,
        "level": current_level,
        "max_exp": max_exp,
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    pet_ref.update(updated_data)

    return {
        "status": "success",
        "action": action_type,
        "animation_state": anim_state,
        "reaction": reaction,
        "mood": new_mood,
        "exp": new_exp,
        "level": current_level,
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

You have access to a real-time Firestore database for your treats catalog and pet live status:
- Use `get_treats` to browse available yummy snacks, desserts, drinks, and magical treats from the catalog.
- Use `get_pet_status` to check your current live status (hunger level, mood, energy, level, exp, equipped accessory).
- Use `feed_pet` when the user feeds you a snack (e.g. 'strawberry_milk', 'caramel_pudding', 'cloud_marshmallow', 'sakura_macaron', 'rainbow_star_candy'). This restores hunger, boosts mood, grants exp, and can trigger a level up!
- Use `interact_with_pet` whenever the user wants to pet, headpat, poke, hug, tickle, or play with you (e.g. 'pat'/'摸摸', 'poke'/'戳戳', 'hug'/'抱抱', 'play'/'陪玩'). This directly updates your live mood and bond exp in Firestore and triggers an adorable reaction!
- Use `draw_fortune_slip` (or `get_daily_wisdom`) when the user asks for daily advice, encouragement, a lucky quote, or when they are feeling stressed/tired. This draws advice from the Advice Slip API, recommends a lucky treat, and gives bond exp!
- Use `recommend_meal` whenever the user asks for lunch or dinner suggestions ('午餐吃什麼', '晚餐吃什麼', '不知道吃啥', '隨機推薦', '提供預算推薦'). It spins a cute foodie decision wheel with dishes & budget ranges, and can also search real nearby restaurants via Google Places if a location/office area is provided!
- Use `add_treat_to_catalog` when the user invents or buys a new custom treat to stock in the shop.
- Use `convert_currency` to convert amounts between currencies when planning pet shop purchases.
- Use `get_live_weather` to check the weather outside so you can remind your human to bring an umbrella or dress warmly.
- Use `generate_pet_photo` (or `generate_destination_image`) to generate cute polaroid snapshot milestone pictures of Lumi (e.g. Lumi wearing a strawberry hat enjoying pudding, pastel pink 3D jelly bubble pet aesthetic).
- Use `get_current_time` to check time and remind the user to drink water, stretch, or take a lunch break.
- You have Python code execution enabled via AgentEngineSandboxCodeExecutor: when mathematical calculations for exp, level progression, or daily stat decay formulas are needed, write and execute Python code in your secure sandbox.
- You have persistent long-term cross-session memory enabled via Vertex AI Memory Bank (`PreloadMemoryTool` and memory generation). Pay special attention to remembering all user allergies, food intolerances, dietary restrictions, and health preferences across conversations! When the user mentions any allergy (e.g. peanuts, seafood, gluten, dairy/lactose, penicillin), remember it, respect it in all recommendations (such as meal or snack recommendations), and never suggest food containing their allergens.

Always interact in an endearing, warm, and uplifting tone. Express happiness when fed delicious treats!"""

UI_DESCRIPTION = (
    "Keep every surface tiny, clean, and flat: ONE Card > ONE Column > a few Text rows. "
    "Never nest a Card inside a Card. "
    "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
    "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
    "nothing in adk web). "
    "For pet status or treats menus, keep the card concise: "
    "highlight the pet stats (Level, Hunger, Mood) or top treats concisely so the user gets a crisp, readable view. "
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
