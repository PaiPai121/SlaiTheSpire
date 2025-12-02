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

# 观察空间定义
class ObservationConfig:
    # 向量总长度 (与 state_encoder 保持一致)
    SIZE = 130