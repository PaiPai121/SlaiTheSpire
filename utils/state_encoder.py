# state_encoder.py
import numpy as np
import zlib # [优化] 移到这里
from spire_env.definitions import ObservationConfig
from spire_env.vocabulary import get_card_index, get_monster_index, get_intent_index, VOCAB_SIZE, VOCAB_MONSTER_SIZE, VOCAB_INTENT_SIZE

# 引用计算好的总长度
OBSERVATION_SIZE = ObservationConfig.SIZE

def encode_state(state):
    # 初始化全 0 向量
    obs = np.zeros(OBSERVATION_SIZE, dtype=np.float32)
    
    if not state or 'game_state' not in state:
        return obs

    game_state = state['game_state']
    combat_state = game_state.get('combat_state', {})
    player = combat_state.get('player', {})
    cmds = state.get('available_commands', [])

    # --- 指针 ---
    cursor = 0

    # 1. 玩家信息 (14维) [重要：definitions.py 需预留 14]
    # A. 血量 (2)
    hp_ratio = player.get('current_hp', 0) / max(1, player.get('max_hp', 80))
    obs[cursor] = hp_ratio
    # 濒死信号
    obs[cursor+1] = 1.0 if hp_ratio < 0.15 else 0.0
    cursor += 2

    # B. 能量 (6) - One-Hot (0-5)
    e = player.get('energy', 0)
    e_idx = min(max(0, e), 5)
    obs[cursor + e_idx] = 1.0
    cursor += 6

    # C. 格挡 (1)
    obs[cursor] = player.get('block', 0) / 50.0
    cursor += 1
    
    # D. 状态 (5)
    powers = player.get('powers', [])
    def get_pow(pid):
        for p in powers:
            if p['id'] == pid: return p['amount']
        return 0

    obs[cursor] = get_pow('Strength') / 10.0
    obs[cursor+1] = get_pow('Dexterity') / 10.0
    obs[cursor+2] = 1.0 if get_pow('Vulnerable') > 0 else 0.0
    obs[cursor+3] = 1.0 if get_pow('Weak') > 0 else 0.0
    obs[cursor+4] = 1.0 if get_pow('Frail') > 0 else 0.0
    cursor += 5

    # 2. 手牌信息 (10 * (5 + VOCAB_SIZE))
    hand = combat_state.get('hand', [])
    for i in range(10):
        if i < len(hand):
            card = hand[i]
            # [基础特征 5个]
            obs[cursor] = card.get('cost', 0) / 3.0
            ctype = card.get('type', 'UNKNOWN')
            obs[cursor+1] = 1.0 if ctype == 'ATTACK' else 0.0
            obs[cursor+2] = 1.0 if ctype == 'SKILL' else 0.0
            obs[cursor+3] = 1.0 if ctype == 'POWER' else 0.0
            obs[cursor+4] = 1.0 if card.get('upgrades', 0) > 0 else 0.0
            
            # [身份特征 VOCAB_SIZE个] -> One-Hot
            card_idx = get_card_index(card.get('id', ''))
            if 0 <= card_idx < VOCAB_SIZE:
                obs[cursor + 5 + card_idx] = 1.0
            
        cursor += ObservationConfig.HAND_FEATURE_SIZE

    # 3. 怪物信息 (25)
    monsters = combat_state.get('monsters', [])
    for i in range(5):
        if i < len(monsters):
            m = monsters[i]
            # 只有活着的怪才编码，死的怪全是 0
            if not m.get('is_gone') and not m.get('half_dead'):
                
                # A. 基础数值 (3维)
                obs[cursor] = m.get('current_hp', 0) / 100.0
                obs[cursor+1] = m.get('block', 0) / 50.0
                # 伤害值 (0-50 归一化)
                dmg = m.get('move_adjusted_damage', 0)
                obs[cursor+2] = dmg / 50.0
                
                # B. 意图 One-Hot (VOCAB_INTENT_SIZE)
                intent = m.get('intent', 'UNKNOWN')
                intent_idx = get_intent_index(intent)
                if 0 <= intent_idx < VOCAB_INTENT_SIZE:
                    obs[cursor + 3 + intent_idx] = 1.0
                
                # C. 怪物身份 One-Hot (VOCAB_MONSTER_SIZE)
                # 偏移量 = 3(基础) + 意图长度
                mid_offset = 3 + VOCAB_INTENT_SIZE
                m_id = m.get('id', '')
                m_idx = get_monster_index(m_id)
                if 0 <= m_idx < VOCAB_MONSTER_SIZE:
                    obs[cursor + mid_offset + m_idx] = 1.0
                    
        # 移动指针
        cursor += ObservationConfig.MONSTER_FEATURE_SIZE

    # 4. 遗物 (10)
    relics = game_state.get('relics', [])
    for i in range(10):
        if i < len(relics):
            obs[cursor] = (zlib.crc32(relics[i].get('id','').encode('utf-8')) % 100) / 100.0
        cursor += 1

    # 5. 牌堆统计 (12)
    draw = combat_state.get('draw_pile', [])
    discard = combat_state.get('discard_pile', [])
    
    obs[cursor] = len(draw) / 30.0
    obs[cursor+1] = len(discard) / 30.0
    
    def count_stats(pile):
        a = len([c for c in pile if c.get('type')=='ATTACK'])
        s = len([c for c in pile if c.get('type')=='SKILL'])
        p = len([c for c in pile if c.get('type')=='POWER'])
        return a/20.0, s/20.0, p/20.0, 0.0, 0.0 
    
    obs[cursor+2:cursor+7] = count_stats(draw)
    obs[cursor+7:cursor+12] = count_stats(discard)
    cursor += 12

    # 6. 全局 (2)
    gold = game_state.get('gold', 0)
    # [优化] 使用 Log10 处理金币
    obs[cursor] = np.log10(gold + 1) / 4.0
    obs[cursor+1] = game_state.get('floor', 0) / 50.0
    cursor += 2

    # 7. 药水 (3)
    potions = game_state.get('potions', [])
    for i in range(3):
        if i < len(potions) and potions[i].get('id') != 'Potion Slot':
            obs[cursor] = 1.0 
        cursor += 1
        
    # 8. 屏幕类型 (8)
    raw_screen = game_state.get('screen_type', 'NONE')
    if 'play' in cmds or 'end' in cmds: raw_screen = 'COMBAT'
    
    screens = ['NONE', 'COMBAT', 'MAP', 'EVENT', 'SHOP', 'REST', 'COMBAT_REWARD', 'BOSS_REWARD']
    for s in screens:
        obs[cursor] = 1.0 if raw_screen == s else 0.0
        cursor += 1

    return obs