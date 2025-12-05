from .vocabulary import VOCAB_SIZE

# 动作空间定义
class ActionIndex:
    # 0-9: 打牌 / 选择选项
    CARD_START = 0
    CARD_END = 9
    
    # 10: 结束回合 / 确认 / 离开 / 继续
    END_TURN = 10
    
    # 11-13: 药水
    POTION_START = 11
    POTION_END = 13
    
    # 总动作数
    TOTAL_ACTIONS = 14

class ObservationConfig:
    # --- 1. 玩家 (Player) - 14维 ---
    # HP_Ratio(1) + HP_Critical(1) + Energy_OneHot(6) + Block(1) + Powers(5)
    PLAYER_SIZE = 1 + 1 + 6 + 1 + 5 
    
    # --- 2. 手牌 (Hand) ---
    # 动态引用 VOCAB_SIZE，防止未来加卡导致维度不匹配
    HAND_FEATURE_SIZE = 5 + VOCAB_SIZE
    HAND_SIZE = 10 * HAND_FEATURE_SIZE
    
    # --- 3. 其他固定维度 ---
    MONSTER_SIZE = 25
    RELIC_SIZE = 10
    PILE_SIZE = 12
    GLOBAL_SIZE = 2
    POTION_SIZE = 3
    SCREEN_SIZE = 8
    
    # --- 总维度 ---
    SIZE = PLAYER_SIZE + HAND_SIZE + MONSTER_SIZE + RELIC_SIZE + PILE_SIZE + GLOBAL_SIZE + POTION_SIZE + SCREEN_SIZE