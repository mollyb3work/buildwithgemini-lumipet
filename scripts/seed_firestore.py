#!/usr/bin/env python3
"""Seed Firestore with curated treats and items for LumiPet."""

from google.cloud import firestore

PROJECT_ID = "qwiklabs-gcp-03-b19cec0b1d20"

SEED_TREATS = [
    {
        "id": "strawberry_milk",
        "name": "草莓牛奶 (Strawberry Milk)",
        "category": "drink",
        "hunger_restore": 20,
        "mood_boost": 25,
        "exp_gain": 15,
        "description": "濃郁香甜的冰涼草莓牛奶，粉嫩可口，露米喝了會開心地冒粉紅泡泡。",
        "rarity": "Common",
        "tags": ["sweet", "drink", "comfort", "pink"]
    },
    {
        "id": "caramel_pudding",
        "name": "焦糖布丁 (Caramel Pudding)",
        "category": "dessert",
        "hunger_restore": 35,
        "mood_boost": 30,
        "exp_gain": 25,
        "description": "Q彈滑嫩的烤布丁，上面淋滿微苦回甘的手工焦糖醬，是露米的最愛！",
        "rarity": "Uncommon",
        "tags": ["dessert", "pudding", "favorite", "sweet"]
    },
    {
        "id": "cloud_marshmallow",
        "name": "雲朵棉花糖 (Cloud Marshmallow)",
        "category": "snack",
        "hunger_restore": 15,
        "mood_boost": 20,
        "exp_gain": 10,
        "description": "像天空雲朵般蓬鬆柔軟的棉花糖，入口即化，帶有一點點香草氣息。",
        "rarity": "Common",
        "tags": ["fluffy", "snack", "light"]
    },
    {
        "id": "sakura_macaron",
        "name": "櫻花馬卡龍 (Sakura Macaron)",
        "category": "dessert",
        "hunger_restore": 25,
        "mood_boost": 40,
        "exp_gain": 35,
        "description": "帶有淡淡櫻花香與白巧克力甘納許的精緻法式馬卡龍，吃完心情值大增！",
        "rarity": "Rare",
        "tags": ["macaron", "sakura", "luxury", "sweet"]
    },
    {
        "id": "rainbow_star_candy",
        "name": "彩虹星星糖 (Rainbow Star Candy)",
        "category": "special",
        "hunger_restore": 10,
        "mood_boost": 50,
        "exp_gain": 50,
        "description": "在夜空中摘下的星塵製成的糖果，會散發微弱光芒，能瞬間治癒疲憊的心情。",
        "rarity": "Epic",
        "tags": ["magical", "candy", "shiny", "energy"]
    },
    {
        "id": "matcha_dango",
        "name": "抹茶三色糰子 (Matcha Dango)",
        "category": "dessert",
        "hunger_restore": 30,
        "mood_boost": 25,
        "exp_gain": 20,
        "description": "粉、白、綠三色軟糯小糰子，散發宇治抹茶的淡雅茶香，適合下午茶時間。",
        "rarity": "Common",
        "tags": ["japanese", "matcha", "chewy"]
    }
]

SEED_PET_STATE = {
    "name": "露米 (Lumi)",
    "personality_id": "cheerful",
    "personality_name": "元氣軟萌型 🌸",
    "catchphrase": "～露咪！",
    "favorite_treat": "caramel_pudding",
    "disliked_treat": "matcha_dango",
    "level": 1,
    "exp": 25,
    "max_exp": 100,
    "hunger": 85,
    "energy": 90,
    "mood": 95,
    "intimacy": 35,
    "status_title": "幼幼期 🥚 · 元氣軟萌型 🌸",
    "equipped_accessory": "幸運四葉草",
    "updated_at": firestore.SERVER_TIMESTAMP
}


def seed():
    print(f"Connecting to Firestore for project: {PROJECT_ID}...")
    db = firestore.Client(project=PROJECT_ID)

    # 1. Seed treats catalog
    collection = db.collection("treats")
    print(f"Seeding {len(SEED_TREATS)} treats...")
    for item in SEED_TREATS:
        doc_ref = collection.document(item["id"])
        doc_ref.set(item)
        print(f"  ✓ Seeded treat: {item['name']} ({item['category']})")

    # 2. Seed initial pet status
    print("Seeding initial pet profile (pets/lumi)...")
    db.collection("pets").document("lumi").set(SEED_PET_STATE)
    print("  ✓ Seeded pet profile: 露米 (Lumi) with personality, growth stage, and 4 vitals!")

    print("Seeding completed successfully!")


if __name__ == "__main__":
    seed()
