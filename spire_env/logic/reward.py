def calculate_reward(prev, curr):
    """计算单步奖励"""
    if not prev or not curr: return 0
    r = 0
    try:
        gp, gc = prev.get('game_state',{}), curr.get('game_state',{})
        
        # 1. 过层
        if gc.get('floor',0) > gp.get('floor',0): r += 10.0
        
        if 'combat_state' in gp and 'combat_state' in gc:
            cp, cc = gp['combat_state'], gc['combat_state']
            
            # 2. 伤害
            mon_p = sum([m['current_hp'] for m in cp.get('monsters',[]) if not m['is_gone']])
            mon_c = sum([m['current_hp'] for m in cc.get('monsters',[]) if not m['is_gone']])
            if (mon_p - mon_c) > 0: r += (mon_p - mon_c) * 0.15
            
            # 3. 击杀
            mp_cnt = len([m for m in cp.get('monsters',[]) if not m['is_gone']])
            mc_cnt = len([m for m in cc.get('monsters',[]) if not m['is_gone']])
            if mc_cnt < mp_cnt: r += 20.0
            
            # 4. 掉血惩罚
            hp_p, hp_c = cp['player']['current_hp'], cc['player']['current_hp']
            if hp_c < hp_p: r -= (hp_p - hp_c) * 1.0
            
            # 5. 有效格挡 (简化版，防止报错)
            bp, bc = cp['player'].get('block',0), cc['player'].get('block',0)
            if bc > bp: r += 0.05 # 稍微奖励一下叠甲
            
    except: pass
    return r