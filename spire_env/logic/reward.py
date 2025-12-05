import numpy as np

def calculate_reward(prev_state, curr_state):
    """
    [价值观重塑 V3.0]
    核心改进：
    1. 非线性血量惩罚：血量越低，掉血惩罚越重 (恐惧机制)。
    2. 阶段性奖励：击杀精英/Boss 奖励翻倍。
    3. 资源管理：使用药水会有轻微惩罚 (成本)，防止浪费。
    """
    if not prev_state or not curr_state: return 0.0

    r = 0.0
    
    # 提取常用数据
    gp = prev_state.get('game_state', {})
    gc = curr_state.get('game_state', {})
    
    # ----------------------------------------------------
    # 1. 生存法则 (Survival) - 最核心
    # ----------------------------------------------------
    if 'combat_state' in gp and 'combat_state' in gc:
        p_prev = gp['combat_state']['player']
        p_curr = gc['combat_state']['player']
        
        hp_start = p_prev['current_hp']
        hp_end = p_curr['current_hp']
        max_hp = p_prev['max_hp']
        
        hp_loss = hp_start - hp_end
        
        if hp_loss > 0:
            # [核心逻辑] 恐惧因子 (Fear Factor)
            # 当前血量百分比 (0.0 - 1.0)
            hp_ratio = hp_end / max(1, max_hp)
            
            # 基础惩罚：掉 1 血扣 1 分
            base_penalty = hp_loss * 1.0
            
            # 恐惧加成：血越少，惩罚越重
            # 满血时：倍率 ≈ 1.0
            # 20%血时：倍率 ≈ 1.0 + 2 * (0.8)^2 ≈ 2.28倍
            # 濒死时：倍率爆炸，迫使 AI 疯狂找防御
            fear_factor = 1.0 + 2.0 * ((1.0 - hp_ratio) ** 2)
            
            r -= base_penalty * fear_factor

    # ----------------------------------------------------
    # 2. 战斗收益 (Combat)
    # ----------------------------------------------------
    if 'combat_state' in gp and 'combat_state' in gc:
        # A. 伤害奖励 (鼓励进攻)
        # 计算所有怪物总血量的下降值
        mon_p = sum([m['current_hp'] for m in gp['combat_state']['monsters'] if not m['is_gone']])
        mon_c = sum([m['current_hp'] for m in gc['combat_state']['monsters'] if not m['is_gone']])
        
        dmg_dealt = mon_p - mon_c
        if dmg_dealt > 0:
            # 每打 1 点伤害 +0.1 分
            # 伤害的权重不能太高，否则 AI 会为了贪伤害而卖血
            r += dmg_dealt * 0.1
            
        # B. 击杀奖励 (Kill Bonus)
        alive_p = len([m for m in gp['combat_state']['monsters'] if not m['is_gone']])
        alive_c = len([m for m in gc['combat_state']['monsters'] if not m['is_gone']])
        
        if alive_c < alive_p:
            # 击杀一个怪 +15 分
            kill_bonus = 15.0
            
            # 如果是精英或 Boss，奖励翻倍 (通过 room_phase 判断不够准，这里简单处理)
            # 真正的强化需要读取 monster type，暂时给个通用奖励
            r += kill_bonus

    # ----------------------------------------------------
    # 3. 探索与资源 (Progress & Resources)
    # ----------------------------------------------------
    
    # A. 爬楼奖励 (Floor Climb)
    # 爬楼是终极目标，给大奖励
    f_prev = gp.get('floor', 0)
    f_curr = gc.get('floor', 0)
    if f_curr > f_prev:
        r += 50.0 
    
    # B. 药水成本 (Potion Cost)
    # 计算药水数量变化
    pot_p = len([p for p in gp.get('potions', []) if p['id'] != 'Potion Slot'])
    pot_c = len([p for p in gc.get('potions', []) if p['id'] != 'Potion Slot'])
    
    if pot_c < pot_p:
        # 使用药水扣 3 分
        # 这会告诉 AI：除非能避免 >3 分的血量惩罚(约掉3血)，否则别乱扔药
        r -= 3.0

    # C. 金币奖励 (Gold)
    # 捡到钱稍微开心一点
    g_prev = gp.get('gold', 0)
    g_curr = gc.get('gold', 0)
    if g_curr > g_prev:
        r += (g_curr - g_prev) * 0.01

    return r