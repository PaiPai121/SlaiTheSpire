# spire_env/vocabulary.py

# 战士 (Ironclad) 的核心卡池
# 这里的顺序决定了神经网络 "看" 到的特征位置，一旦开始训练就不能乱改顺序
IRONCLAD_CARDS = [
    # --- 基础 (Starter) ---
    "Strike_R", "Defend_R", "Bash",
    
    # --- 普通 (Common) ---
    "Sword Boomerang", "Clothesline", "Headbutt", "Anger", "Warcry", "Cleave",
    "Pommel Strike", "Twin Strike", "Iron Wave", "Thunderclap", "Perfected Strike",
    "Shrug It Off", "True Grit", "Body Slam", "Clash", "Heavy Blade", "Armaments",
    "Wild Strike", 
    
    # --- 罕见 (Uncommon) ---
    "Dropkick", "Hemokinesis", "Uppercut", "Flame Barrier", "Disarm", "Inflame",
    "Pummel", "Rampage", "Ghostly Armor", "Fire Breathing", "Infernal Blade",
    "Metallicize", "Spot Weakness", "Shockwave", "Sever Soul", "Whirlwind",
    "Searing Blow", "Entrench", "Blood for Blood", "Combust", "Evolve", 
    "Dual Wield", "Power Through", "Seeing Red", "Second Wind", "Sentinel",
    "Feel No Pain", "Intimidate", "Carnage", "Battle Trance", "Rage", "Bloodletting",
    "Rupture", "Burning Pact",
    
    # --- 稀有 (Rare) ---
    "Demon Form", "Double Tap", "Exhume", "Feed", "Limit Break", "Offering",
    "Reaper", "Immolate", "Impervious", "Juggernaut", "Barricade", "Berserk",
    "Bludgeon", "Brutality", "Corruption", "Dark Embrace", "Fiend Fire",
    
    # --- 诅咒/状态 (Curse/Status) - 选几个常见的 ---
    "Dazed", "Wound", "Slimed", "Burn", "Void", "Ascender's Bane", "Clumsy", "Pain",
    "Necronomicurse", "CurseOfTheBell"
]

# 建立索引映射: "Strike_R" -> 0, "Bash" -> 2 ...
CARD_TO_INDEX = {card_id: i for i, card_id in enumerate(IRONCLAD_CARDS)}

# 未知卡牌的索引 (比如中立卡、新版本卡)
UNKNOWN_CARD_INDEX = len(IRONCLAD_CARDS)

# 词表总长度 (用于 One-Hot 向量长度)
# +1 是为了给 "Unknown" 留位置
VOCAB_SIZE = len(IRONCLAD_CARDS) + 1

def get_card_index(card_id):
    """查字典，返回卡牌的数字编号"""
    # 移除卡牌 ID 中的升级后缀 (如 "Bash+1" -> "Bash")
    # 游戏里的 ID 通常是 "Bash" 或 "Bash+1"
    clean_id = card_id.split('+')[0]
    return CARD_TO_INDEX.get(clean_id, UNKNOWN_CARD_INDEX)