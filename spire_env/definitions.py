from .vocabulary import VOCAB_SIZE, VOCAB_MONSTER_SIZE, VOCAB_INTENT_SIZE # [新增引用]

class ActionConfig:
    # 常量定义
    MAX_HAND_CARDS = 10
    MAX_MONSTERS = 5
    MAX_POTIONS = 3
    
    # --- 动作空间映射 ---
    # 1. 卡牌动作: 0 - 49
    # [Card 0 (Target 0-4)], [Card 1 (Target 0-4)] ...
    CARD_ACTION_SIZE = MAX_HAND_CARDS * MAX_MONSTERS # 50
    
    # 2. 药水动作: 50 - 64
    # [Potion 0 (Target 0-4)], ...
    POTION_ACTION_START = CARD_ACTION_SIZE # 50
    POTION_ACTION_SIZE = MAX_POTIONS * MAX_MONSTERS # 15
    
    # 3. 其他动作
    # 65: End Turn / Confirm / Proceed
    # 66: Cancel / Return (新增，用于退出选牌界面)
    END_TURN_IDX = CARD_ACTION_SIZE + POTION_ACTION_SIZE # 65
    CANCEL_IDX = END_TURN_IDX + 1 # 66
    
    # 总大小 = 67
    TOTAL_ACTIONS = CANCEL_IDX + 1

# 兼容旧代码的引用 (保留但标记为过时)
class ActionIndex:
    TOTAL_ACTIONS = ActionConfig.TOTAL_ACTIONS

class ObservationConfig:
    # 1. 玩家 (Player) - 14维 (保持不变)
    PLAYER_SIZE = 1 + 1 + 6 + 1 + 5 
    
    # 2. 手牌 (Hand) - (保持不变)
    HAND_FEATURE_SIZE = 5 + VOCAB_SIZE
    HAND_SIZE = 10 * HAND_FEATURE_SIZE
    
    # 3. 怪物 (Monster) - [核心修改]
    # 3个基础值 (HP, Block, Dmg) + 意图OneHot + 身份OneHot
    MONSTER_FEATURE_SIZE = 3 + VOCAB_INTENT_SIZE + VOCAB_MONSTER_SIZE
    MONSTER_SIZE = 5 * MONSTER_FEATURE_SIZE # 5只怪
    
    # 4. 其他 (保持不变)
    RELIC_SIZE = 10
    PILE_SIZE = 12
    GLOBAL_SIZE = 2
    POTION_SIZE = 3
    SCREEN_SIZE = 8
    
    # 总维度
    SIZE = PLAYER_SIZE + HAND_SIZE + MONSTER_SIZE + RELIC_SIZE + PILE_SIZE + GLOBAL_SIZE + POTION_SIZE + SCREEN_SIZE