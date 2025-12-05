import time
from .game_io import get_latest_state
from .combat import ensure_hand_drawn

def process_non_combat(conn, state):
    """
    [导航核心 V17 - 篝火精灵/Grid 终极修复版]
    针对 "篝火精灵" 等需要选牌后确认的事件进行了定力增强。
    1. 引入"耐心选择"机制：不再每回合切换选择目标，而是连续尝试同一张牌 3 次 (idx = counter // 3)。
       这能防止 AI 在 confirm 按钮出现前就急着换牌，导致选中状态丢失。
    2. 保持了对 confirm 的最高优先级响应。
    """
    stuck_counter = 0
    combat_wait_counter = 0
    choose_stuck_counter = 0 
    
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
            time.sleep(0.001)
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
        # 2. 战斗与交互检测 (含 GRID/HAND_SELECT)
        # ==========================================
        is_combat_interaction = (phase == 'COMBAT') and (screen in ['HAND_SELECT', 'GRID'])
        is_combat = (screen == 'COMBAT') or \
                    ('play' in cmds) or \
                    ('end' in cmds) or \
                    is_combat_interaction
                    # (screen == 'CARD_REWARD') # 有些奖励界面也需要点击
        
        if screen in ['GAME_OVER', 'VICTORY']: 
            return state
        
        if is_combat:
            # --- [Grid/Hand Select 专用逻辑] ---
            
            # 1. 最高优先级：看见 Confirm 就点，绝不犹豫
            # 1. 最高优先级：看见 Confirm 就点
            if 'confirm' in cmds:
                conn.log(f"[Combat] 交互确认 -> confirm")
                conn.send_command("confirm")
                choose_stuck_counter = 0 
                
                # [关键修复] 智能等待 confirm 消失
                # 防止因为动画延迟导致脚本以为没点上，从而疯狂连点
                start_wait = time.time()
                while time.time() - start_wait < 3.0: # 最多给 3 秒动画时间
                    time.sleep(0.01) # 每次小睡 0.2s
                    conn.send_command("state")
                    # 使用较小的 retry 防止这里卡死
                    new_s = get_latest_state(conn, retry_limit=2)
                    
                    if new_s:
                        state = new_s # 更新这一轮的状态
                        
                        # 检查 confirm 是否已经消失
                        if 'confirm' not in state.get('available_commands', []):
                            # 消失了！说明点击生效，动画结束，跳出循环进入下一步
                            break
                
                # 如果 3 秒后 confirm 还在，循环会自动结束，
                # 外层 while True 会再次进来点一次（作为兜底防丢包），这比无限连点要安全得多。
                time.sleep(0.001)
                continue
            # 2. 选择逻辑 (Choose)
            # 只有当 'choose' 存在，且不能打牌(play)时，才视为选择界面
            if 'choose' in cmds and 'play' not in cmds and 'end' not in cmds:
                if screen in ['HAND_SELECT', 'GRID']:
                    # 停止自动导航，将状态返回给 Agent，让神经网络决定选哪张牌
                    return state
                # [关键修复] 降低切换频率
                # (counter // 3) % 5 意味着：
                # counter=0,1,2 -> 选第 0 张
                # counter=3,4,5 -> 选第 1 张
                # 这样保证了每一张牌都有 3 次机会等待 confirm 出现
                idx = (choose_stuck_counter // 3) % 5 
                
                # 特殊情况：如果是篝火(Rest)的卡牌奖励界面，通常只选第0个就行，不需要轮询
                if screen == 'CARD_REWARD':
                    idx = 0

                conn.log(f"[Combat] 交互选择 (Screen:{screen}) -> choose {idx}")
                conn.send_command(f"choose {idx}")
                
                choose_stuck_counter += 1
                
                # 等待时间
                wait_time = 1.0 if screen == 'GRID' else 0.5
                time.sleep(wait_time)
                
                conn.send_command("state")
                state = get_latest_state(conn)
                time.sleep(0.001)
                continue
            
            # 如果成功脱离了 choose 循环，重置计数
            choose_stuck_counter = 0

            # --- [正常战斗逻辑] ---
            if 'play' in cmds or 'end' in cmds:
                return ensure_hand_drawn(conn, state)
            else:
                combat_wait_counter += 1
                if combat_wait_counter % 20 == 0: 
                    conn.send_command("ready")
                time.sleep(0.01)
                conn.send_command("state")
                state = get_latest_state(conn)
                time.sleep(0.001)
                continue
        else:
            combat_wait_counter = 0
            choose_stuck_counter = 0

        # 3. 转场过滤
        if screen == 'NONE':
            time.sleep(0.01); conn.send_command("state")
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
            # === [新增] 篝火 (REST) ===
            elif screen == 'REST':
                # 如果还没做选择 (有 choose 指令)
                if 'choose' in cmds:
                    # 1. 获取玩家血量信息
                    player = game.get('combat_state', {}).get('player') or \
                             game.get('player', {}) # 兼容不同层级
                    
                    current_hp = player.get('current_hp', 0)
                    max_hp = player.get('max_hp', 80)
                    hp_ratio = current_hp / max(1, max_hp)
                    
                    # 2. 分析选项
                    choice_list = game.get('choice_list', [])
                    # 典型的 choice_list 长这样: ['rest', 'smith', 'toke'...]
                    
                    # 默认行为：找 "rest" (索引通常是 0)
                    target_action = "rest"
                    
                    # 3. 决策逻辑
                    # 如果血量健康 (>50%)，且可以锻造，就优先锻造
                    if hp_ratio > 0.5:
                        if 'smith' in choice_list:
                            target_action = "smith"
                        elif 'dig' in choice_list: # 如果有铲子
                            target_action = "dig"
                        elif 'lift' in choice_list: # 如果有吉拉亚
                            target_action = "lift"
                            
                    # 4. 执行选择
                    # 找到目标动作在列表里的索引
                    try:
                        idx = choice_list.index(target_action)
                        action_cmd = f"choose {idx}"
                        decision_reason = f"篝火决策: {target_action} (HP: {int(hp_ratio*100)}%)"
                    except ValueError:
                        # 如果想做的做不了（比如满血不能rest，或者没牌升级不能smith）
                        # 就选第一个能用的
                        action_cmd = "choose 0"
                        decision_reason = "篝火默认选择"
                
                # 如果已经选完了 (有 proceed)
                elif 'proceed' in cmds:
                    action_cmd = 'proceed'
                    decision_reason = "离开篝火"
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
            # === [新增] 宝箱 (CHEST) ===
            elif screen == 'CHEST':
                # 1. 还没开箱子，先开
                if 'open' in cmds:
                    action_cmd = 'open'
                    decision_reason = "开启宝箱"
                
                # 2. 箱子开了，里面有东西 (遗物/金币/钥匙)
                # Communication Mod 通常会把箱子里的东西变成 'choose' 选项
                elif 'choose' in cmds:
                    # 这里不需要太复杂，无脑拿第一个就行
                    # 因为拿完一个，状态会刷新，下次循环拿第二个
                    # 除非你有 "诅咒钥匙(Cursed Key)" 遗物不想拿，但现阶段建议全拿
                    action_cmd = "choose 0" 
                    decision_reason = "拿取宝箱奖励"
                    
                # 3. 拿空了，继续
                elif 'proceed' in cmds:
                    action_cmd = 'proceed'
                    decision_reason = "离开宝箱房间"
            # === [新增/修改] C1. 战斗奖励专用逻辑 (修复药水卡死) ===
            elif screen == 'COMBAT_REWARD':
                # 1. 检查药水是否满了
                combat_state = game.get('combat_state', {})
                # 注意：有些情况下 potions 在 game_state 根目录下，有些在 combat_state 下，做个兼容
                potions = combat_state.get('potions', []) or game.get('potions', [])
                
                # 计算已填充的格子 (ID 不是 "Potion Slot" 的就是有药水)
                filled_slots = [p for p in potions if p.get('id') != 'Potion Slot']
                is_potion_full = (len(filled_slots) >= len(potions)) and (len(potions) > 0)
                
                # 2. 遍历奖励列表，跳过不该拿的
                choice_list = game.get('choice_list', []) # 例如 ['gold', 'potion', 'card']
                target_idx = -1
                target_name = ""

                for i, item_name in enumerate(choice_list):
                    # 核心修复：如果是药水且包满了，绝对不要选它！
                    if item_name == 'potion' and is_potion_full:
                        conn.log(f"[Nav] ⚠️ 药水已满 ({len(filled_slots)}/{len(potions)})，自动跳过药水奖励")
                        continue
                    
                    # 只要不是(满包时的药水)，就拿第一个遇到的东西
                    target_idx = i
                    target_name = item_name
                    break # 找到一个能拿的就去拿，拿完状态会刷新，下次循环再拿下一个
                
                # 3. 执行决策
                if target_idx != -1:
                    action_cmd = f"choose {target_idx}"
                    decision_reason = f"拿取奖励: {target_name}"
                else:
                    # 如果没有东西可拿了（或者只剩下拿不了的药水），点击继续/跳过
                    for kw in ['proceed', 'skip', 'leave', 'cancel']:
                        if kw in cmds: 
                            action_cmd = kw
                            decision_reason = "离开奖励结算"
                            break

            # === C. 奖励与选择 ===
            elif screen in ['BOSS_REWARD', 'REST', 'GRID', 'HAND_SELECT', 'CARD_REWARD']:
                
                if 'choose' in cmds:
                    if same_screen_counter > 100: 
                         pass 
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

            # [优化] 动态超时时间
            # MAP: 地图加载慢，给 8s
            # COMBAT_REWARD: 拿奖励很快，只要 0.5s 就够了，不要傻等
            if screen == 'MAP':
                t_out = 4.0
            elif screen == 'COMBAT_REWARD':
                t_out = 0.5 # <--- 关键修改：拿完奖励立刻走
            else:
                t_out = 2.0
            
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
                    # [关键修改] 获取选项列表的内容摘要
                    prev_choices = game.get('choice_list', [])
                    next_choices = ng.get('choice_list', [])
                    
                    # 新逻辑：增加对选项列表变化的检测
                    # 如果选项的数量变了，或者内容变了，也视为状态切换成功
                    choices_changed = (len(prev_choices) != len(next_choices)) or (prev_choices != next_choices)

                    if ns != prev_screen or nc != prev_cmds or choices_changed:
                        state = next_s; transitioned = True; same_screen_counter = 0; break
                
                time.sleep(0.05)
            
            if not transitioned:
                state = get_latest_state(conn)
                same_screen_counter += 1
        else:
            stuck_counter += 1
            time.sleep(0.01)
            conn.send_command("state")
            state = get_latest_state(conn)
            
    return state