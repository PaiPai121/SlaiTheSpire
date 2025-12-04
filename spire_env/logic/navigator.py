import time
from .game_io import get_latest_state
from .combat import ensure_hand_drawn

def process_non_combat(conn, state):
    """
    [导航核心 V14 - 贪婪修复版]
    移除了奖励界面的超时放弃逻辑。
    在 COMBAT_REWARD/BOSS_REWARD 界面，只要有 'choose' 就坚持拿取，
    防止因停留时间过长而误触 proceed 跳过奖励。
    """
    stuck_counter = 0
    combat_wait_counter = 0
    same_screen_counter = 0
    last_choice_idx = 0
    last_screen_type = None
    
    while True:
        # 1. 刷新状态
        if not state or 'game_state' not in state:
            time.sleep(0.05)
            conn.send_command("state")
            state = get_latest_state(conn, retry_limit=1)
            stuck_counter += 1
            if stuck_counter > 50: 
                conn.send_command("state")
                stuck_counter = 0
            continue

        game = state.get('game_state', {})
        screen = game.get('screen_type', 'N/A')
        cmds = state.get('available_commands', [])
        phase = game.get('room_phase', '')

        # 更新卡顿计数
        if screen == last_screen_type:
            same_screen_counter += 1
        else:
            same_screen_counter = 0
            last_screen_type = screen

        # ==========================================
        # 2. 战斗检测
        # ==========================================
        is_combat = (screen == 'COMBAT') or \
                    (phase == 'COMBAT') or \
                    ('play' in cmds) or \
                    ('end' in cmds) or \
                    (screen == 'HAND_SELECT') or \
                    (screen == 'GRID')
        
        if screen in ['GAME_OVER', 'VICTORY']: 
            return state
        
        if is_combat:
            # [场景 A] 战斗中的特殊交互
            if 'choose' in cmds and 'play' not in cmds and 'end' not in cmds:
                conn.log(f"[Combat] 战斗内选择 (Screen:{screen}) -> choose 0")
                conn.send_command("choose 0")
                time.sleep(0.5)
                conn.send_command("state")
                state = get_latest_state(conn)
                continue

            # [场景 B] 正常战斗
            if 'play' in cmds or 'end' in cmds:
                return ensure_hand_drawn(conn, state)
            else:
                combat_wait_counter += 1
                if combat_wait_counter % 20 == 0: 
                    conn.send_command("ready")
                time.sleep(0.1)
                conn.send_command("state")
                state = get_latest_state(conn)
                continue
        else:
            combat_wait_counter = 0

        # 3. 转场过滤
        if screen == 'NONE':
            time.sleep(0.1); conn.send_command("state")
            state = get_latest_state(conn); continue

        # ==========================================
        # 4. 决策逻辑 (非战斗)
        # ==========================================
        action_cmd = None
        decision_reason = "" 

        # [T0] 确认
        if 'confirm' in cmds: 
            action_cmd = 'confirm'
            decision_reason = "确认/继续"

        if not action_cmd:
            
            # === A. 商店 (SHOP) ===
            if screen == 'SHOP':
                for kw in ['leave', 'return', 'cancel', 'proceed']:
                    if kw in cmds: 
                        action_cmd = kw
                        decision_reason = "离开商店 (禁买)"
                        break

            # === B. 地图 (MAP) ===
            elif screen == 'MAP':
                if 'choose' in cmds:
                    if same_screen_counter > 5:
                        idx = (last_choice_idx + 1) % 3 
                        action_cmd = f"choose {idx}"
                        last_choice_idx = idx
                        decision_reason = f"切换路径 ({idx})"
                    else:
                        action_cmd = "choose 0"
                        last_choice_idx = 0
                        decision_reason = "选择路径 (默认)"
                
                elif 'return' in cmds or 'cancel' in cmds:
                    action_cmd = 'return' if 'return' in cmds else 'cancel'
                    decision_reason = "关闭地图"

            # === C. 奖励与选择 (重点修复) ===
            elif screen in ['COMBAT_REWARD', 'BOSS_REWARD', 'REST', 'GRID', 'HAND_SELECT', 'CARD_REWARD']:
                
                # 只要有 choose，就优先选择，永不放弃 (除非卡死超过非常久)
                # 之前的 same_screen_counter > 8 在这里被移除了
                if 'choose' in cmds:
                    # 为了防止真的死循环（比如选了没反应），设置一个超大的阈值
                    if same_screen_counter > 100: 
                         # 极度无奈时才尝试 proceed
                         pass 
                    else:
                        # 正常贪婪逻辑：拿!
                        # 对于奖励界面，我们通常想拿所有东西，所以一直 choose 0 就可以
                        # 因为拿了一个，它就会从列表消失，下一个变成 0
                        action_cmd = "choose 0"
                        last_choice_idx = 0
                        decision_reason = "拿取奖励/选择 (默认)"
                
                # 如果没有东西可拿了，或者被迫放弃，才尝试离开
                if not action_cmd:
                    for kw in ['proceed', 'skip', 'leave', 'start', 'next', 'cancel']:
                        if kw in cmds: 
                            action_cmd = kw
                            decision_reason = "离开奖励界面"
                            break

            # === D. 其他 ===
            else:
                for kw in ['leave', 'return', 'cancel', 'proceed', 'skip', 'start', 'next']:
                    if kw in cmds: 
                        action_cmd = kw
                        decision_reason = "离开/前进"
                        break
                
                if not action_cmd and 'choose' in cmds:
                    action_cmd = "choose 0"
                    decision_reason = "事件选择"

                if not action_cmd and 'click' in cmds:
                    action_cmd = 'click'
                    decision_reason = "点击对话"

        # ==========================================
        # 5. 执行与等待
        # ==========================================
        if action_cmd:
            # 日志
            cmds_str = str(cmds) if len(cmds) < 5 else str(cmds[:5] + ['...'])
            conn.log(f"┌─ [Nav State] Screen: {screen} | Cmds: {cmds_str}")
            conn.log(f"└─ [Auto] 执行: {action_cmd} ({decision_reason})")
            
            prev_screen = screen
            prev_cmds = cmds
            
            conn.send_command(action_cmd)
            stuck_counter = 0
            
            wait_start = time.time()
            t_out = 8.0 if screen == 'MAP' else 2.0 
            
            transitioned = False
            while time.time() - wait_start < t_out:
                conn.send_command("state")
                next_s = get_latest_state(conn, retry_limit=1)
                
                if next_s:
                    ng = next_s.get('game_state', {})
                    ns = ng.get('screen_type')
                    nc = next_s.get('available_commands')
                    np = ng.get('room_phase')
                    
                    if ns == 'NONE' or ns == 'COMBAT' or np == 'COMBAT':
                        state = next_s; transitioned = True; break
                    
                    if ns != prev_screen or nc != prev_cmds:
                        state = next_s; transitioned = True; same_screen_counter = 0; break
                
                time.sleep(0.05)
            
            if not transitioned:
                state = get_latest_state(conn)
                same_screen_counter += 1
        else:
            stuck_counter += 1
            time.sleep(0.1)
            conn.send_command("state")
            state = get_latest_state(conn)
            
    return state