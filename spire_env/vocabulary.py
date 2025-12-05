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

# ==============================================================================
# 2. 怪物词表 (Monster Vocabulary)
# ==============================================================================
# 包含了 1-3 层常见怪物、精英和 Boss。
# 遇到没见过的怪会被归类为 UNKNOWN，不影响程序运行。
MONSTER_IDS = [
    # --- Act 1 ---
    "Cultist", "JawWorm", "FungiBeast", "FuzzyLouseNormal", "FuzzyLouseDefensive", "AcidSlime_L", "SpikeSlime_L",
    "AcidSlime_M", "SpikeSlime_M", "AcidSlime_S", "SpikeSlime_S", "Looter", "BlueSlaver",
    "GremlinNob", "Sentry", "Lagavulin", "TheGuardian", "Hexaghost", "SlimeBoss",
    # [新增] 地精家族 (把这一组补进去)
    "GremlinNob",       # 精英 (已有)
    "GremlinFat",       # 胖地精 (虚弱)
    "GremlinTsundere",  # 愤怒地精 (Mad Gremlin) - ID叫傲娇确实挺搞笑的
    "GremlinWarrior",   # 护盾地精 (Shield Gremlin)
    "GremlinThief",     # 偷窃地精 (Sneaky Gremlin) - 为了防止以后报错，一起加上
    "GremlinWizard",    # 巫师地精 (Wizard Gremlin) - 为了防止以后报错，一起加上
    # --- Act 2 ---
    "SphericGuardian", "Chosen", "ShellParasite", "Byrd", "Centurion", "Mystic",
    "Snecko", "SnakePlant", "Mugger", "Shelled Parasite", "Taskmaster",
    "GremlinLeader", "BookOfStabbing", "SlaverBlue", "SlaverRed", 
    "Champ", "TheCollector", "BronzeAutomaton",
    
    # --- Act 3 ---
    "Darkling", "Orb Walker", "SpireGrowth", "Transient", "WrithingMass", "GiantHead",
    "Nemesis", "Reptomancer", "TimeEater", "AwakenedOne", "Donu", "Deca",
    
    # --- Others ---
    "SpireShield", "SpireSpear", "CorruptHeart"
]

MONSTER_TO_INDEX = {m_id: i for i, m_id in enumerate(MONSTER_IDS)}
VOCAB_MONSTER_SIZE = len(MONSTER_IDS) + 1  # +1 for Unknown

def get_monster_index(m_id):
    # 移除可能存在的后缀 (比如 Darkling_1 -> Darkling)
    # 但 Spire 的 ID 通常比较干净，如果有后缀需要 split('_')[0]
    return MONSTER_TO_INDEX.get(m_id, len(MONSTER_IDS))

# ==============================================================================
# 3. 意图词表 (Intent Vocabulary)
# ==============================================================================
# 怪物头顶显示的意图类型
INTENT_TYPES = [
    "ATTACK",           # 攻击
    "ATTACK_BUFF",      # 攻击+强化
    "ATTACK_DEBUFF",    # 攻击+削弱
    "ATTACK_DEFEND",    # 攻击+格挡
    "BUFF",             # 强化
    "DEBUFF",           # 削弱
    "STRONG_DEBUFF",    # 强力削弱
    "DEFEND",           # 防御
    "DEFEND_BUFF",      # 防御+强化
    "DEFEND_DEBUFF",    # 防御+削弱
    "ESCAPE",           # 逃跑
    "SLEEP",            # 睡觉
    "STUN",             # 眩晕
    "UNKNOWN"           # 未知
]

INTENT_TO_INDEX = {intent: i for i, intent in enumerate(INTENT_TYPES)}
VOCAB_INTENT_SIZE = len(INTENT_TYPES) + 1

def get_intent_index(intent_str):
    return INTENT_TO_INDEX.get(intent_str, len(INTENT_TYPES))