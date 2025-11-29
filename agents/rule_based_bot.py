import sys
import json
import os
import time

# --- 日志功能 ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(SCRIPT_DIR, "ai_debug_log.txt")
# 每次启动先清空旧日志
if os.path.exists(LOG_FILE):
    try:
        os.remove(LOG_FILE)
    except PermissionError:
        pass # 如果文件被占用就不删了，直接追加
def log(message):
    """把调试信息写到本地文件，而不是打印到屏幕"""
    with open(LOG_FILE, "a", encoding='utf-8') as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {message}\n")

# --- 核心逻辑 ---

def read_state():
    try:
        input_str = sys.stdin.readline()
        if not input_str:
            return None
        return json.loads(input_str)
    except Exception as e:
        log(f"读取错误: {e}")
        return None

def send_command(cmd):
    # 打印到标准输出，这是给游戏看的
    print(cmd, flush=True)
    # 同时也记录到日志，这是给你看的
    log(f"发送指令 -> {cmd}")

def main():
    log("Python 脚本启动成功！正在等待游戏数据...")
    send_command("ready")

    while True:
        time.sleep(0.2)
        state = read_state()
        if state is None:
            continue

        # 记录一下当前是什么状态（为了防止日志爆炸，只记命令列表）
        avail_cmds = state.get('available_commands', [])
        # log(f"收到状态，可用指令: {avail_cmds}") 

        if 'start' in avail_cmds:
            pass
            # send_command("start ironclad")
        
        elif 'choose' in avail_cmds:
            send_command("choose 0")

        elif 'play' in avail_cmds:
            # --- 智能战斗逻辑 v2.0 ---
            
            # 1. 获取必要的战斗信息
            game_state = state.get('game_state', {})
            combat_state = game_state.get('combat_state', {})
            
            hand = combat_state.get('hand', [])
            monsters = combat_state.get('monsters', [])
            player_energy = combat_state.get('player', {}).get('energy', 0)
            
            # 2. 寻找一个合法的攻击目标（找第一个活着的怪物）
            target_index = -1
            for i, monster in enumerate(monsters):
                # 判定条件：没有逃跑(is_gone为False) 且 血量大于0 且 没死(half_dead为False)
                if not monster.get('is_gone') and monster.get('current_hp', 0) > 0 and not monster.get('half_dead'):
                    target_index = i
                    break
            
            # 3. 遍历手牌尝试出牌
            card_played = False
            for index, card in enumerate(hand):
                card_idx = index + 1 # 转换成游戏用的 1-based 索引
                cost = card.get('cost', 0)
                
                # 检查: 是否可打出 + 能量是否足够
                if card.get('is_playable') and player_energy >= cost:
                    
                    # 情况 A: 需要指定目标的卡 (攻击牌)
                    if card.get('has_target'):
                        if target_index != -1: # 只有场上有活怪才打
                            send_command(f"play {card_idx} {target_index}")
                            log(f"打击 -> {card['name']} (目标序号: {target_index})")
                            card_played = True
                            break
                        else:
                            log(f"想打 {card['name']} 但是找不到活着的怪")
                    
                    # 情况 B: 不需要目标的卡 (防御牌/AOE/能力牌)
                    else:
                        send_command(f"play {card_idx}")
                        log(f"打出 -> {card['name']} (无目标)")
                        card_played = True
                        break
            
            # 4. 如果没牌打，结束回合
            if not card_played:
                # 双重保险：如果没有目标了，或者没能量了，或者手里全是废牌
                log("无法出牌，结束回合")
                send_command("end")
                
        elif 'end' in avail_cmds:
            send_command("end")

        elif 'proceed' in avail_cmds:
            send_command("proceed")
        
        elif 'confirm' in avail_cmds:
            send_command("confirm")
        
        elif 'leave' in avail_cmds:
            send_command("leave")

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log(f"致命错误导致崩溃: {e}")