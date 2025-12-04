import time
from .game_io import get_latest_state
from .combat import ensure_hand_drawn

def process_non_combat(conn, state):
    """
    [导航核心 V12 - 详细日志版]
    保持了之前的修复逻辑（Map锁定/商店禁买/Neow修复），
    并增加了详细的格式化日志，让过图决策清晰可见。
    """
    stuck_counter = 0
    combat_wait_counter = 0
    same_screen_counter = 0
    last_choice_idx = 0
    last_screen_type = None
    
    while True:
        # 1. 刷新状态
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
        decision_reason = "" # 用于日志显示的决策理由

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
                        decision_reason = f"切换路径 (防卡死 {idx})"
                    else:
                        action_cmd = "choose 0"
                        last_choice_idx = 0
                        decision_reason = "选择路径 (默认)"
                
                elif 'return' in cmds or 'cancel' in cmds:
                    action_cmd = 'return' if 'return' in cmds else 'cancel'
                    decision_reason = "关闭地图/返回"

            # === C. 贪婪组 (奖励) ===
            elif screen in ['COMBAT_REWARD', 'BOSS_REWARD', 'REST', 'GRID', 'HAND_SELECT', 'CARD_REWARD']:
                if 'choose' in cmds:
                    if same_screen_counter > 8:
                        pass # 放弃
                    else:
                        if same_screen_counter > 4:
                            idx = (last_choice_idx + 1) % 5 
                            action_cmd = f"choose {idx}"
                            last_choice_idx = idx
                            decision_reason = f"拿取奖励/选择 ({idx})"
                        else:
                            action_cmd = "choose 0"
                            last_choice_idx = 0
                            decision_reason = "拿取奖励/选择 (默认)"
                
                if not action_cmd:
                    for kw in ['proceed', 'skip', 'leave', 'start', 'next', 'cancel']:
                        if kw in cmds: 
                            action_cmd = kw
                            decision_reason = "离开奖励界面"
                            break

            # === D. 路过组 (事件) ===
            else:
                for kw in ['leave', 'return', 'cancel', 'proceed', 'skip', 'start', 'next']:
                    if kw in cmds: 
                        action_cmd = kw
                        decision_reason = "离开/前进"
                        break
                
                if not action_cmd and 'choose' in cmds:
                    if screen == 'SHOP': pass 
                    else:
                        action_cmd = "choose 0"
                        decision_reason = "事件选择"

                if not action_cmd and 'click' in cmds:
                    action_cmd = 'click'
                    decision_reason = "点击对话"

        # 5. 执行与日志
        if action_cmd:
            # --- [新增] 详细日志 ---
            # 缩略显示 cmds 防止太长
            cmds_str = str(cmds) if len(cmds) < 5 else str(cmds[:5] + ['...'])
            conn.log(f"┌─ [Nav State] Screen: {screen} | Cmds: {cmds_str}")
            conn.log(f"└─ [Auto] 执行: {action_cmd} ({decision_reason})")
            
            prev_screen = screen
            prev_cmds = cmds
            
            conn.send_command(action_cmd)
            stuck_counter = 0
            
            # 锁定等待
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
                    
                    # 退出条件
                    if ns == 'NONE': 
                        # conn.log(f"   [Nav] 转场中 (NONE)...")
                        state = next_s; transitioned = True; break
                    if ns == 'COMBAT' or np == 'COMBAT':
                        # conn.log(f"   [Nav] 进入战斗!")
                        state = next_s; transitioned = True; break
                    if ns != prev_screen or nc != prev_cmds:
                        state = next_s; transitioned = True; same_screen_counter = 0; break
                time.sleep(0.05)
            
            if not transitioned:
                # conn.log(f"   [Nav] ⚠️ 动作未生效或加载中...")
                state = get_latest_state(conn)
                same_screen_counter += 1
        else:
            stuck_counter += 1
            time.sleep(0.1); conn.send_command("state")
            state = get_latest_state(conn)
            
    return state