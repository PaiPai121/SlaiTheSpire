import time
from .game_io import get_latest_state
from .combat import ensure_hand_drawn

def process_non_combat(conn, state):
    """
    [导航核心 V11 - 篝火修复版]
    1. SHOP: 禁买，强制离开。
    2. MAP: 锁定选路，长等待。
    3. REST: 优先行动(休息/锻造)，长等待(适配动画)。
    4. REWARD: 贪婪拿取。
    5. EVENT: 优先逃跑。
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
                    conn.send_command("ready")
                time.sleep(0.1); conn.send_command("state")
                state = get_latest_state(conn); continue
        else:
            combat_wait_counter = 0

        # 3. 转场过滤
        if screen == 'NONE':
            time.sleep(0.1); conn.send_command("state")
            state = get_latest_state(conn); continue

        # ==========================================
        # 4. 决策逻辑
        # ==========================================
        action_cmd = None

        # [T0] 确认 (最高级)
        if 'confirm' in cmds: action_cmd = 'confirm'

        if not action_cmd:
            
            # === A. 商店 (SHOP) - 禁买 ===
            if screen == 'SHOP':
                for kw in ['leave', 'return', 'cancel', 'proceed']:
                    if kw in cmds: action_cmd = kw; break

            # === B. 地图 (MAP) - 锁定选路 ===
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

            # === C. 篝火 (REST) - 动画适配 ===
            # 篝火需要特殊处理，因为睡觉动画很长
            elif screen == 'REST':
                # 1. 优先行动 (休息/锻造)
                if 'choose' in cmds:
                    # 如果卡住了(比如不能睡觉?)，尝试第二个选项(锻造)
                    if same_screen_counter > 5:
                        action_cmd = "choose 1"
                    else:
                        # 默认选第0个 (通常是睡觉)
                        action_cmd = "choose 0"
                
                # 2. 行动完后离开
                if not action_cmd:
                    for kw in ['proceed', 'leave', 'start', 'next']:
                        if kw in cmds: action_cmd = kw; break

            # === D. 贪婪组 (奖励) ===
            elif screen in ['COMBAT_REWARD', 'BOSS_REWARD', 'GRID', 'HAND_SELECT', 'CARD_REWARD']:
                if 'choose' in cmds:
                    if same_screen_counter > 8: # 防死锁熔断
                        pass 
                    else:
                        if same_screen_counter > 4:
                            idx = (last_choice_idx + 1) % 5 
                            action_cmd = f"choose {idx}"
                            last_choice_idx = idx
                        else:
                            action_cmd = "choose 0"
                            last_choice_idx = 0
                
                if not action_cmd:
                    for kw in ['proceed', 'skip', 'leave', 'start', 'next', 'cancel']:
                        if kw in cmds: action_cmd = kw; break

            # === E. 路过组 (事件/其他) ===
            else:
                for kw in ['leave', 'return', 'cancel', 'proceed', 'skip', 'start', 'next']:
                    if kw in cmds: action_cmd = kw; break
                
                if not action_cmd and 'choose' in cmds:
                    if same_screen_counter > 5:
                        idx = (last_choice_idx + 1) % 5 
                        action_cmd = f"choose {idx}"; last_choice_idx = idx
                    else:
                        action_cmd = "choose 0"; last_choice_idx = 0
                
                if not action_cmd and 'click' in cmds:
                    action_cmd = 'click'

        # 5. 执行与锁定
        if action_cmd:
            # conn.log(f"[Auto] {action_cmd}") 
            prev_screen = screen
            prev_cmds = cmds
            conn.send_command(action_cmd)
            stuck_counter = 0
            
            # [动态超时] 根据界面类型调整等待时间
            if screen == 'MAP': t_out = 8.0
            elif screen == 'REST': t_out = 5.0 # 篝火动画长，给5秒
            else: t_out = 2.0
            
            wait_start = time.time()
            transitioned = False
            while time.time() - wait_start < t_out:
                conn.send_command("state")
                next_s = get_latest_state(conn, retry_limit=1)
                if next_s:
                    ng = next_s.get('game_state', {})
                    ns = ng.get('screen_type')
                    nc = next_s.get('available_commands')
                    np = ng.get('room_phase')
                    
                    # 退出条件
                    if ns == 'NONE': 
                        state = next_s; transitioned = True; break
                    if ns == 'COMBAT' or np == 'COMBAT':
                        state = next_s; transitioned = True; break
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