import time
from .game_io import get_latest_state

def wait_for_card_played(conn, prev_state):
    try:
        p_c = prev_state['game_state']['combat_state']
        base_e = p_c['player']['energy']
        base_h = len(p_c.get('hand', []))
        base_ids = sorted([c.get('id','') for c in p_c.get('hand', [])])
    except:
        time.sleep(0.5); return

    time.sleep(0.05)
    start_t = time.time()
    
    while time.time() - start_t < 3.0:
        conn.send_command("state")
        state = get_latest_state(conn, retry_limit=3)
        if not state:
            time.sleep(0.05); continue
        
        try:
            if state['game_state']['screen_type'] != 'COMBAT': return
            
            c_c = state['game_state']['combat_state']
            if c_c['player']['energy'] != base_e:
                time.sleep(0.1); return
            if len(c_c.get('hand', [])) != base_h:
                time.sleep(0.1); return
            
            curr_ids = sorted([c.get('id','') for c in c_c.get('hand', [])])
            if curr_ids != base_ids:
                time.sleep(0.1); return
        except: pass
        
        time.sleep(0.05)

def wait_for_new_turn(conn, prev_turn):
    conn.log(f"Wait Turn {prev_turn}...")
    time.sleep(0.5)
    st = time.time()
    while time.time() - st < 60.0:
        conn.send_command("state")
        s = get_latest_state(conn)
        if not s: continue
        
        g = s.get('game_state', {})
        if g.get('screen_type') not in ['COMBAT', 'NONE']: return
        
        ct = g.get('combat_state', {}).get('turn', 0)
        if ct > prev_turn:
            time.sleep(0.5)
            if 'play' in s.get('available_commands', []): return
        time.sleep(0.5)

def ensure_hand_drawn(conn, state):
    # [已删除] 移除了 "检查手牌..." 的刷屏日志
    for i in range(30):
        c = state.get('game_state', {}).get('combat_state', {})
        if len(c.get('hand', [])) > 0: 
            # 只有成功了才打印
            # conn.log(f"手牌就绪: {len(c.get('hand', []))}") 
            return state
        
        if i == 10: 
            conn.log("手牌延迟，发送 ready...")
            conn.send_command("ready")

        time.sleep(0.1); conn.send_command("state")
        new_s = get_latest_state(conn)
        if new_s: state = new_s
        
    return state