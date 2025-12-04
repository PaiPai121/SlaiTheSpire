import time
from .game_io import get_latest_state
from .combat import ensure_hand_drawn

def process_non_combat(conn, state):
    """
    [导航核心 V13 - 修复战斗内选择卡死]
    修复了打出"武装"、"发现"等卡牌进入 HAND_SELECT 界面后卡死的问题。
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
            # 如果卡太久，强制刷新
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
        # 2. 战斗检测 (修复核心)
        # ==========================================
        # 只要满足以下任一条件，都视为战斗逻辑尚未结束
        is_combat = (screen == 'COMBAT') or \
                    (phase == 'COMBAT') or \
                    ('play' in cmds) or \
                    ('end' in cmds) or \
                    (screen == 'HAND_SELECT') or \
                    (screen == 'GRID')
        
        # 游戏结束直接返回，交给 env.step 处理
        if screen in ['GAME_OVER', 'VICTORY']: 
            return state
        
        if is_combat:
            # [场景 A] 战斗中的特殊交互 (如: 武装/发现/药水选择)
            # 现象: 有 choose 指令，但不能打牌 (play) 也不能结束回合 (end)
            if 'choose' in cmds and 'play' not in cmds and 'end' not in cmds:
                conn.log(f"[Combat] 检测到战斗内选择 (Screen:{screen}) -> 自动选择 0")
                conn.send_command("choose 0")
                
                # 选完后稍等并刷新状态
                time.sleep(0.5)
                conn.send_command("state")
                state = get_latest_state(conn)
                continue

            # [场景 B] 正常的战斗出牌阶段
            if 'play' in cmds or 'end' in cmds:
                return ensure_hand_drawn(conn, state)
            
            # [场景 C] 动画播放或等待中
            else:
                combat_wait_counter += 1
                # 防止长时间无响应，偶尔发送 ready
                if combat_wait_counter % 20 == 0: 
                    conn.send_command("ready")
                
                time.sleep(0.1)
                conn.send_command("state")
                state = get_latest_state(conn)
                continue
        else:
            # 离开战斗状态，重置计数器
            combat_wait_counter = 0

        # 3. 转场过滤 (NONE 状态)
        if screen == 'NONE':
            time.sleep(0.1)
            conn.send_command("state")
            state = get_latest_state(conn)
            continue

        # ==========================================
        # 4. 决策逻辑 (非战斗界面的导航)
        # ==========================================
        action_cmd = None
        decision_reason = "" 

        # [T0] 确认 (最高优先级)
        if 'confirm' in cmds: 
            action_cmd = 'confirm'
            decision_reason = "确认/继续"

        if not action_cmd:
            
            # === A. 商店 (SHOP) - 强制离开，暂不购买 ===
            if screen == 'SHOP':
                for kw in ['leave', 'return', 'cancel', 'proceed']:
                    if kw in cmds: 
                        action_cmd = kw
                        decision_reason = "离开商店 (禁买)"
                        break

            # === B. 地图 (MAP) ===
            elif screen == 'MAP':
                if 'choose' in cmds:
                    # 如果在地图卡太久，尝试切换路径
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

            # === C. 奖励与选择 (REWARD / REST / EVENT) ===
            # 包括: 战斗奖励、BOSS奖励、篝火、卡牌三选一
            elif screen in ['COMBAT_REWARD', 'BOSS_REWARD', 'REST', 'GRID', 'HAND_SELECT', 'CARD_REWARD']:
                if 'choose' in cmds:
                    # 只有在非战斗状态下，才在这里处理 choose
                    if same_screen_counter > 8:
                        pass # 如果一直选不了，可能是卡死了，暂时放弃操作
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
                
                # 如果没有 choose 或者选完了，尝试离开
                if not action_cmd:
                    for kw in ['proceed', 'skip', 'leave', 'start', 'next', 'cancel']:
                        if kw in cmds: 
                            action_cmd = kw
                            decision_reason = "离开奖励界面"
                            break

            # === D. 其他通用事件与对话 ===
            else:
                for kw in ['leave', 'return', 'cancel', 'proceed', 'skip', 'start', 'next']:
                    if kw in cmds: 
                        action_cmd = kw
                        decision_reason = "离开/前进"
                        break
                
                if not action_cmd and 'choose' in cmds:
                    # 最后的保底选择
                    if screen != 'SHOP':
                        action_cmd = "choose 0"
                        decision_reason = "事件选择"

                if not action_cmd and 'click' in cmds:
                    action_cmd = 'click'
                    decision_reason = "点击对话"

        # ==========================================
        # 5. 执行指令与等待结果
        # ==========================================
        if action_cmd:
            # 记录详细日志
            cmds_str = str(cmds) if len(cmds) < 5 else str(cmds[:5] + ['...'])
            conn.log(f"┌─ [Nav State] Screen: {screen} | Cmds: {cmds_str}")
            conn.log(f"└─ [Auto] 执行: {action_cmd} ({decision_reason})")
            
            prev_screen = screen
            prev_cmds = cmds
            
            conn.send_command(action_cmd)
            stuck_counter = 0
            
            # 执行后等待状态变化
            wait_start = time.time()
            # 地图加载比较慢，给多点时间
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
                    
                    # 如果进入 NONE (转场) 或 COMBAT (战斗)，立即退出循环
                    if ns == 'NONE': 
                        state = next_s; transitioned = True; break
                    if ns == 'COMBAT' or np == 'COMBAT':
                        state = next_s; transitioned = True; break
                    
                    # 如果屏幕类型变了，或可用指令变了，说明操作成功
                    if ns != prev_screen or nc != prev_cmds:
                        state = next_s; transitioned = True; same_screen_counter = 0; break
                
                time.sleep(0.05)
            
            if not transitioned:
                # 动作似乎没生效，更新一下状态继续循环
                state = get_latest_state(conn)
                same_screen_counter += 1
        else:
            # 没有可执行的动作，等待一下
            stuck_counter += 1
            time.sleep(0.1)
            conn.send_command("state")
            state = get_latest_state(conn)
            
    return state