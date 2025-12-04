import time
from .game_io import get_latest_state

def wait_for_card_played(conn, prev_state, card_cost=None):
    """
    [战斗锁 - NONE 修复版]
    修复了因 Screen:NONE 导致提前退出等待，进而引发连打的问题。
    """
    try:
        p_c = prev_state['game_state']['combat_state']
        base_e = p_c['player']['energy']
        base_h = len(p_c.get('hand', []))
        base_ids = sorted([c.get('id','') for c in p_c.get('hand', [])])
    except:
        conn.log("[Wait] ❌ 获取基准值失败，直接跳过")
        time.sleep(0.5); return

    conn.log(f"[Wait] 开始等待... Cost:{card_cost} | Base E:{base_e} H:{base_h}")

    # 1. 物理冷却
    time.sleep(0.2)
    
    start_t = time.time()
    loop_count = 0
    
    while time.time() - start_t < 3.0:
        loop_count += 1
        conn.send_command("state")
        state = get_latest_state(conn, retry_limit=3)
        
        if not state:
            time.sleep(0.05); continue
        
        try:
            screen = state['game_state'].get('screen_type')
            
            # [关键修复] 严格的退出条件
            # 只有明确处于非战斗结算界面，才视为战斗结束
            # 如果是 NONE，说明还在战斗转场中，必须继续检查能量变化！
            end_screens = ['VICTORY', 'GAME_OVER', 'COMBAT_REWARD', 'MAP', 'SHOP', 'REST']
            
            if screen in end_screens:
                conn.log(f"[Wait] ✅ 战斗真正结束 (Screen:{screen})，放行")
                return
            
            # 如果是 COMBAT 或 NONE，继续检查数值变化
            
            c_c = state['game_state'].get('combat_state')
            if not c_c: 
                # 可能是 NONE 状态且没有 combat_state，继续等下一帧
                time.sleep(0.05); continue

            curr_e = c_c['player']['energy']
            curr_h = len(c_c.get('hand', []))
            
            # --- 判定逻辑 ---
            
            # A. 能量变了 (最强判定)
            if curr_e != base_e:
                conn.log(f"[Wait] ✅ 能量变化 ({base_e}->{curr_e})，放行")
                time.sleep(0.1); return

            # B. 手牌变了
            check_hand = (card_cost is None) or (card_cost == 0)
            
            if check_hand:
                if curr_h != base_h:
                    conn.log(f"[Wait] ✅ 手牌数变化 ({base_h}->{curr_h})，放行")
                    time.sleep(0.1); return
                
                curr_ids = sorted([c.get('id','') for c in c_c.get('hand', [])])
                if curr_ids != base_ids:
                    conn.log(f"[Wait] ✅ 手牌内容变化，放行")
                    time.sleep(0.1); return
            else:
                # 调试日志：如果你看到这一行，说明脚本正在正确地等待能量扣除，而不是乱打
                if curr_h != base_h and loop_count % 5 == 0:
                    conn.log(f"[Wait] 手牌已变但能量未变(E:{base_e})，继续等待 (Screen:{screen})...")
                    
        except Exception as e:
            conn.log(f"[Wait] ⚠️ 逻辑报错: {e}")
            pass
        
        # 没满足条件，继续等
        time.sleep(0.05)
    
    conn.log(f"[Wait] ❌ 超时 (3.0s)，状态未发生预期变化。")

def wait_for_new_turn(conn, prev_turn):
    conn.log(f"[Wait] 等待新回合 (Curr:{prev_turn})...")
    time.sleep(0.2)
    st = time.time()
    while time.time() - st < 60.0:
        conn.send_command("state")
        s = get_latest_state(conn)
        if not s: 
            time.sleep(0.05); continue
        
        g = s.get('game_state', {})
        screen = g.get('screen_type', 'N/A')
        
        # 同样的逻辑：NONE 不算结束
        end_screens = ['VICTORY', 'GAME_OVER', 'COMBAT_REWARD', 'MAP']
        if screen in end_screens: 
            conn.log(f"[Wait] 战斗结束 ({screen})"); return
        
        ct = g.get('combat_state', {}).get('turn', 0)
        if ct > prev_turn:
            # 必须看到 play 才能确认回合开始
            if 'play' in s.get('available_commands', []): 
                conn.log(f"[Wait] 新回合开始: {ct}"); return
            else:
                # 只有回合数变了但没 play，可能是抽牌动画，稍等
                time.sleep(0.1)
                
        time.sleep(0.05)
    conn.log("[Wait] ⚠️ 等待回合超时")

def ensure_hand_drawn(conn, state):
    for i in range(30):
        c = state.get('game_state', {}).get('combat_state', {})
        if len(c.get('hand', [])) > 0: 
            return state
        
        if i == 10: 
            conn.log("[Combat] 手牌延迟，发送 ready...")
            conn.send_command("ready")

        time.sleep(0.1); conn.send_command("state")
        new_s = get_latest_state(conn)
        if new_s: state = new_s
        
    return state