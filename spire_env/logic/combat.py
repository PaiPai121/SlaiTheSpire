import time
from .game_io import get_latest_state

def wait_for_card_played(conn, prev_state, card_cost=None):
    """
    [战斗锁 - 极速响应版]
    修复了逻辑死锁：只要检测到【手牌减少】或【能量变化】任一发生，
    就立即视为动作完成，不再死等能量数值刷新。
    """
    try:
        p_c = prev_state['game_state']['combat_state']
        base_e = p_c['player']['energy']
        base_h = len(p_c.get('hand', []))
        # 记录手牌ID列表，用于精确比对
        base_ids = sorted([c.get('id','') for c in p_c.get('hand', [])])
    except:
        # 如果获取不到基准值，为了不卡死，直接等待一下就放行
        conn.log("[Wait] ❌ 获取基准值失败，默认等待0.5s")
        time.sleep(0.5)
        return

    # 1. 物理冷却 (给游戏一点反应时间)
    time.sleep(0.15)
    
    start_t = time.time()
    
    # 将超时时间从 3.0 延长到 4.0，防止慢动作导致的误报
    while time.time() - start_t < 4.0:
        conn.send_command("state")
        state = get_latest_state(conn, retry_limit=3)
        
        if not state:
            time.sleep(0.05); continue
        
        try:
            g = state.get('game_state', {})
            screen = g.get('screen_type')
            
            # --- 场景 A: 战斗结束 ---
            # 如果屏幕变成了非战斗、非NONE状态 (如 Victory, Map)，直接放行
            end_screens = ['VICTORY', 'GAME_OVER', 'COMBAT_REWARD', 'MAP', 'SHOP', 'REST']
            if screen in end_screens:
                return # 战斗结束，无需等待
            
            c_c = g.get('combat_state')
            if not c_c: 
                time.sleep(0.05); continue

            curr_e = c_c['player']['energy']
            curr_h = len(c_c.get('hand', []))
            
            # --- 场景 B: 判定成功 (任意满足其一即可) ---
            
            # 1. 能量变了 (强证据)
            # 注意：有些牌可能回复能量，所以只要不相等就算变了
            if curr_e != base_e:
                # conn.log(f"[Wait] ✅ 能量变化 ({base_e}->{curr_e})") # 减少刷屏
                return

            # 2. 手牌数变少了 (核心修复)
            # 只要手牌变少，说明牌肯定打出去了 (排除了能力牌/消耗牌的影响)
            # 即使是抽牌流(剑柄打击)，打出的一瞬间手牌也会先-1
            if curr_h < base_h:
                # conn.log(f"[Wait] ✅ 手牌减少 ({base_h}->{curr_h})")
                return

            # 3. 手牌数没变，但内容变了 (例如：打出一张牌抽了一张牌)
            if curr_h == base_h:
                curr_ids = sorted([c.get('id','') for c in c_c.get('hand', [])])
                if curr_ids != base_ids:
                    # conn.log(f"[Wait] ✅ 手牌内容更新")
                    return
            
            # 如果到了这里，说明没变化，继续等
            # 只有在非 NONE 状态下才认为是真的没变化
            # NONE 状态通常意味着动画正在播放，我们耐心等待
            
        except Exception as e:
            pass
        
        time.sleep(0.05)
    
    # 如果超时了，通常是因为动画太长或者状态未同步
    # 但我们不能抛出异常，只能打印日志并继续，防止训练中断
    conn.log(f"[Wait] ⚠️ 等待超时 (4s) - 强制继续")

def wait_for_new_turn(conn, prev_turn):
    conn.log(f"[Wait] 等待新回合 (Curr:{prev_turn})...")
    time.sleep(0.5) # 给一点初始等待，防止还没按下结束回合就检测
    
    st = time.time()
    while time.time() - st < 60.0:
        conn.send_command("state")
        s = get_latest_state(conn)
        if not s: 
            time.sleep(0.05); continue
        
        g = s.get('game_state', {})
        screen = g.get('screen_type', 'N/A')
        
        end_screens = ['VICTORY', 'GAME_OVER', 'COMBAT_REWARD', 'MAP']
        if screen in end_screens: 
            return
        
        # 检查回合数
        ct = g.get('combat_state', {}).get('turn', 0)
        cmds = s.get('available_commands', [])
        
        # 判定新回合开始的标准：
        # 1. 回合数增加
        # 2. 必须能打牌 (play) —— 这很重要，防止在敌人回合判定开始
        if ct > prev_turn and 'play' in cmds:
            conn.log(f"[Wait] 新回合开始: {ct}")
            return
                
        time.sleep(0.1)
    
    conn.log("[Wait] ⚠️ 等待回合超时")

def ensure_hand_drawn(conn, state):
    """确保手牌已经发到手里"""
    for i in range(30): # 最多等 3 秒
        c = state.get('game_state', {}).get('combat_state', {})
        hand = c.get('hand', [])
        
        if len(hand) > 0: 
            return state
        
        # 如果等了 1 秒还没牌，可能是卡动画了，发个 ready
        if i == 10: 
            conn.send_command("ready")

        time.sleep(0.1)
        conn.send_command("state")
        new_s = get_latest_state(conn)
        if new_s: state = new_s
        
    return state