import time
from .game_io import get_latest_state
from .combat import ensure_hand_drawn

def process_non_combat(conn, state):
    """
    [导航核心 V4] 极速响应版
    优化了超时逻辑，修复了进战斗前的 8秒 卡顿。
    """
    stuck_counter = 0
    combat_wait_counter = 0
    same_screen_counter = 0
    last_choice_idx = 0
    last_screen_type = None
    
    while True:
        # 1. 刷新
        if not state or 'game_state' not in state:
            time.sleep(0.05); conn.send_command("state")
            state = get_latest_state(conn, retry_limit=1)
            stuck_counter += 1
            if stuck_counter > 50: conn.send_command("state"); stuck_counter = 0
            continue

        game = state.get('game_state', {})
        screen = game.get('screen_type', 'N/A')
        cmds = state.get('available_commands', [])
        phase = game.get('room_phase', '')

        # 更新卡顿计数
        if screen == last_screen_type: same_screen_counter += 1
        else: same_screen_counter = 0; last_screen_type = screen

        # 2. 战斗检测 (优先级最高)
        is_combat = (screen == 'COMBAT') or (phase == 'COMBAT') or \
                    ('play' in cmds) or ('end' in cmds)
        
        if screen in ['GAME_OVER', 'VICTORY']: return state
        
        if is_combat:
            if 'play' in cmds or 'end' in cmds:
                return ensure_hand_drawn(conn, state)
            else:
                combat_wait_counter += 1
                if combat_wait_counter % 20 == 0: 
                    conn.send_command("ready")
                time.sleep(0.1); conn.send_command("state")
                state = get_latest_state(conn); continue
        else:
            combat_wait_counter = 0

        # [关键修复] 转场处理
        # 如果是 NONE，说明正在加载，死循环等待直到出现具体界面
        # 这避免了在转场时重复发送 choose/return
        if screen == 'NONE':
            time.sleep(0.1); conn.send_command("state")
            state = get_latest_state(conn); continue

        # ==========================================
        # 4. 决策逻辑
        # ==========================================
        action_cmd = None

        # [T0] 全局确认
        if 'confirm' in cmds: action_cmd = 'confirm'

        if not action_cmd:
            # === A. 商店 (禁买) ===
            if screen == 'SHOP':
                for kw in ['leave', 'return', 'cancel', 'proceed']:
                    if kw in cmds: action_cmd = kw; break

            # === B. 地图 (选路) ===
            elif screen == 'MAP':
                if 'choose' in cmds:
                    if same_screen_counter > 5:
                        idx = (last_choice_idx + 1) % 3 
                        action_cmd = f"choose {idx}"
                        last_choice_idx = idx
                    else:
                        action_cmd = "choose 0"
                        last_choice_idx = 0
                
                elif 'return' in cmds or 'cancel' in cmds:
                    action_cmd = 'return' if 'return' in cmds else 'cancel'

            # === C. 事件 (逃跑优先) ===
            elif screen == 'EVENT':
                for kw in ['leave', 'return', 'skip', 'cancel']:
                    if kw in cmds: action_cmd = kw; break
                
                if not action_cmd and 'choose' in cmds:
                    if same_screen_counter > 5:
                        idx = (last_choice_idx + 1) % 5 
                        action_cmd = f"choose {idx}"
                        last_choice_idx = idx
                    else:
                        action_cmd = "choose 0"
                        last_choice_idx = 0
                
                if not action_cmd:
                    for kw in ['proceed', 'start', 'next', 'click']:
                        if kw in cmds: action_cmd = kw; break

            # === D. 其他 (拿取优先) ===
            else:
                if 'choose' in cmds:
                    if same_screen_counter > 5:
                        idx = (last_choice_idx + 1) % 5 
                        action_cmd = f"choose {idx}"
                        last_choice_idx = idx
                    else:
                        action_cmd = "choose 0"
                        last_choice_idx = 0
                
                if not action_cmd:
                    for kw in ['proceed', 'leave', 'start', 'next']:
                        if kw in cmds: action_cmd = kw; break
                
                if not action_cmd and 'click' in cmds: action_cmd = 'click'
                
                if not action_cmd:
                    for kw in ['return', 'skip', 'cancel']:
                        if kw in cmds: action_cmd = kw; break

        # 5. 执行与快速锁定
        if action_cmd:
            conn.log(f"[Auto] {action_cmd}")
            
            prev_screen = screen
            prev_cmds = cmds
            
            conn.send_command(action_cmd)
            stuck_counter = 0
            
            # [关键修复] 缩短超时时间
            # 地图 1.5s (够了，如果没反应说明丢包，重发比死等好)
            # 其他 1.0s
            t_out = 1.5 if screen == 'MAP' else 1.0
            
            wait_start = time.time()
            transitioned = False
            
            while time.time() - wait_start < t_out:
                conn.send_command("state")
                next_s = get_latest_state(conn, retry_limit=1)
                
                if next_s:
                    ng = next_s.get('game_state', {})
                    ns = ng.get('screen_type')
                    nc = next_s.get('available_commands')
                    
                    # [关键修复] 如果变成了 NONE，视为成功跳转（正在转场）
                    if ns == 'NONE':
                        state = next_s; transitioned = True; break
                        
                    # 或者状态变了
                    if ns != prev_screen or nc != prev_cmds:
                        state = next_s; transitioned = True; same_screen_counter = 0; break
                
                time.sleep(0.05)
            
            if not transitioned:
                state = get_latest_state(conn)
                same_screen_counter += 1
        else:
            stuck_counter += 1
            time.sleep(0.1); conn.send_command("state")
            state = get_latest_state(conn)
            
    return state