import time
from .game_io import get_latest_state
from .combat import ensure_hand_drawn

def process_non_combat(conn, state):
    """
    [导航核心] 自动处理地图、事件、奖励等非战斗界面
    """
    stuck_counter = 0
    combat_wait_counter = 0
    same_screen_counter = 0
    last_choice_idx = 0
    last_screen_type = None
    
    # [已删除] 这里的刷屏日志删掉了
    
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

        if screen == last_screen_type: same_screen_counter += 1
        else: same_screen_counter = 0; last_screen_type = screen

        # 2. 战斗检测
        is_combat = (screen == 'COMBAT') or (phase == 'COMBAT') or \
                    ('play' in cmds) or ('end' in cmds)
        
        if screen in ['GAME_OVER', 'VICTORY']: return state
        
        if is_combat:
            if 'play' in cmds or 'end' in cmds:
                return ensure_hand_drawn(conn, state)
            else:
                combat_wait_counter += 1
                if combat_wait_counter % 20 == 0: 
                    # conn.log("[Combat] 唤醒...") # 这种偶尔出现的可以留着
                    conn.send_command("ready")
                
                time.sleep(0.1); conn.send_command("state")
                state = get_latest_state(conn); continue
        else:
            combat_wait_counter = 0

        # 3. 转场过滤
        if screen == 'NONE':
            time.sleep(0.1); conn.send_command("state")
            state = get_latest_state(conn); continue

        # 4. 决策逻辑
        action_cmd = None

        if screen == 'MAP':
            if 'choose' in cmds:
                if same_screen_counter > 2:
                    idx = (last_choice_idx + 1) % 3 
                    action_cmd = f"choose {idx}"
                    last_choice_idx = idx
                else:
                    action_cmd = "choose 0"
                    last_choice_idx = 0
                
                conn.log(f"[Map] 选路: {action_cmd}")
                conn.send_command(action_cmd)
                
                wait_start = time.time()
                while time.time() - wait_start < 8.0:
                    conn.send_command("state")
                    next_s = get_latest_state(conn, retry_limit=1)
                    if next_s:
                        ns = next_s.get('game_state', {}).get('screen_type')
                        np = next_s.get('game_state', {}).get('room_phase')
                        if ns and (ns != 'MAP' or np == 'COMBAT'):
                            state = next_s; action_cmd = None; break
                    time.sleep(0.1)
                
                if action_cmd: state = get_latest_state(conn); continue
                else: continue 

            elif 'return' in cmds or 'cancel' in cmds:
                action_cmd = 'return' if 'return' in cmds else 'cancel'

        else:
            for kw in ['confirm', 'proceed', 'leave', 'start', 'next', 'return', 'skip', 'cancel']:
                if kw in cmds: action_cmd = kw; break
            
            if not action_cmd and 'choose' in cmds:
                if same_screen_counter > 2:
                    idx = (last_choice_idx + 1) % 5 
                    action_cmd = f"choose {idx}"
                    last_choice_idx = idx
                else:
                    action_cmd = "choose 0"
                    last_choice_idx = 0
            
            if not action_cmd and 'click' in cmds:
                action_cmd = "click"

        # 5. 执行
        if action_cmd:
            conn.log(f"[Auto] {action_cmd}")
            conn.send_command(action_cmd)
            stuck_counter = 0
            time.sleep(0.2); conn.send_command("state")
            state = get_latest_state(conn)
        else:
            stuck_counter += 1
            time.sleep(0.1); conn.send_command("state")
            state = get_latest_state(conn)
            
    return state