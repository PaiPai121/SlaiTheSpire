import time

def get_latest_state(conn, retry_limit=10):
    """
    [IO核心 - 极速读取版]
    读取最新状态。为了加快缓冲区清理速度，
    移除了读取失败后的等待，改为高频重试。
    """
    for i in range(retry_limit):
        s = conn.receive_state()
        
        # 只要 JSON 结构合法且有指令列表，就返回
        if s and isinstance(s, dict) and 'available_commands' in s:
            return s
        
        # 如果没读到，不要 sleep，立即重试，以最快速度消耗缓冲区
        # 只有在最后几次重试才加一点点延迟防止 CPU 100%
        if i > retry_limit - 3:
            time.sleep(0.02)
            
        # 偶数次失败主动请求
        if i % 2 == 1: 
            conn.send_command("state")
    
    return None