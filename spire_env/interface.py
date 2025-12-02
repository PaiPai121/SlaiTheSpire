import sys
import json
import os
import time

class Connection:
    def __init__(self, log_filename="ai_debug_log.txt"):
        # 定位 logs 目录
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_dir = os.path.join(project_root, "logs")
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
            
        self.log_path = os.path.join(log_dir, log_filename)
        self._clear_log()
        
        self.log("Connection initialized.")
        
        # [新增] 用于记录上一次收到的原始字符串，做去重对比
        self.last_raw_line = None

    def _clear_log(self):
        if os.path.exists(self.log_path):
            try: os.remove(self.log_path)
            except: pass

    def log(self, message):
        """记录日志到文件"""
        timestamp = time.strftime('%H:%M:%S')
        try:
            with open(self.log_path, "a", encoding='utf-8') as f:
                f.write(f"[{timestamp}] {message}\n")
        except: pass # 防止日志写入导致程序崩溃

    def receive_state(self):
        """读取状态，带去重功能"""
        try:
            input_str = sys.stdin.readline()
            if not input_str:
                return None
            
            # --- [优化] 日志去重逻辑 ---
            # 只有当这次收到的字符串和上次不一样时，才记录到 txt 文件
            if input_str != self.last_raw_line:
                # 为了不让日志太长，这里只截取前 200 个字符记录一下
                # 如果你想看完整 JSON，可以把 [:200] 去掉
                # self.log(f"Recv -> {input_str[:200]} ... (Length: {len(input_str)})") # 去除state日志需注释这里
                self.last_raw_line = input_str
            else:
                # 如果完全一样，就默默跳过日志记录，直接解析返回
                pass
            
            return json.loads(input_str)

        except json.JSONDecodeError:
            self.log(f"JSON解析错误: {input_str}")
            return None
        except Exception as e:
            self.log(f"读取异常: {e}")
            return None

    def send_command(self, cmd):
        """发送指令"""
        print(cmd.strip(), flush=True)
        
        # --- [优化] 不记录心跳包 ---
        # "state" 指令只是为了刷新，刷屏太烦人，不记日志
        if cmd != "state":
            self.log(f"Send -> {cmd}")