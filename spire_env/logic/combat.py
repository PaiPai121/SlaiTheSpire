import time
from .game_io import get_latest_state

def wait_for_card_played(conn, prev_state):
    """
    [战斗锁] 等待打牌生效
    """
    try:
        p_c = prev_state['game_state']['combat_state']
        base_e = p_c['player']['energy']
        base_h = len(p_c.get('hand', []))
        base_ids = sorted([c.get('id','') for c in p_c.get('hand', [])])
    except:
        time.sleep(0.5); return

    # [关键修改] 增加强制冷却时间到 0.3s
    # 这能给游戏引擎足够的时间去处理扣费和丢牌动画
    # 防止脚本过早读取到"未变化"的旧状态
    time.sleep(0.3)
    
    start_t = time.time()
    
    # conn.log(f"[Wait] 等待出牌反馈 (Base E:{base_e} H:{base_h})...")

    while time.time() - start_t < 3.0:
        conn.send_command("state")
        state = get_latest_state(conn, retry_limit=3)
        if not state:
            time.sleep(0.05); continue
        
        try:
            # 如果怪死光了/战斗结束，直接放行
            if state['game_state']['screen_type'] != 'COMBAT': 
                # conn.log("[Wait] 战斗结束，放行")
                return
            
            c_c = state['game_state']['combat_state']
            curr_e = c_c['player']['energy']
            curr_h = len(c_c.get('hand', []))
            
            # 判定变化
            if curr_e != base_e:
                # conn.log(f"[Wait] 能量变化 ({base_e}->{curr_e})，放行")
                time.sleep(0.1); return
            
            if curr_h != base_h:
                # conn.log(f"[Wait] 手牌数变化 ({base_h}->{curr_h})，放行")
                time.sleep(0.1); return
            
            curr_ids = sorted([c.get('id','') for c in c_c.get('hand', [])])
            if curr_ids != base_ids:
                # conn.log(f"[Wait] 手牌内容变化，放行")
                time.sleep(0.1); return
                
        except: pass
        
        # 没变化，继续轮询
        time.sleep(0.05)
    
    # conn.log("[Wait] ⚠️ 等待超时，状态未变")

def wait_for_new_turn(conn, prev_turn):
    """等待回合数增加"""
    conn.log(f"Wait Turn {prev_turn}...")
    
    # 这里的等待也可以稍微给一点，防止太快读到旧回合
    time.sleep(0.2)
    
    st = time.time()
    while time.time() - st < 60.0:
        conn.send_command("state")
        s = get_latest_state(conn)
        if not s: 
            time.sleep(0.05); continue
        
        g = s.get('game_state', {})
        if g.get('screen_type') not in ['COMBAT', 'NONE']: return
        
        ct = g.get('combat_state', {}).get('turn', 0)
        if ct > prev_turn:
            # 只有看到 play 指令才算真的开始，否则可能还在抽牌动画
            if 'play' in s.get('available_commands', []): 
                # conn.log(f"Turn {ct} Start!")
                return
            else:
                time.sleep(0.1) # 还没ready，稍等
                
        time.sleep(0.05)

def ensure_hand_drawn(conn, state):
    """确保手牌加载完成，带 ready 唤醒"""
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