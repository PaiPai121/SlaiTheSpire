# interface.py
import sys
import json
import os
import time
import threading
import queue

class Connection:
    def __init__(self, log_filename="ai_debug_log.txt"):
        # 1. 日志路径
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_dir = os.path.join(project_root, "logs")
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
            
        self.log_path = os.path.join(log_dir, log_filename)
        
        # 2. 高效日志
        try:
            self.log_file = open(self.log_path, "w", encoding='utf-8', buffering=1)
        except:
            self.log_file = None
        
        # 3. 多线程队列 (带容量限制，防止内存泄漏)
        self.input_queue = queue.Queue(maxsize=1000)
        
        # 4. 启动后台线程
        self.reader_thread = threading.Thread(target=self._read_stdin_loop, daemon=True)
        self.reader_thread.start()
        
        self.log(">>> Connection initialized (Blocking-IO Support) <<<")

    def _read_stdin_loop(self):
        """后台线程：死循环读取，读到就塞队列"""
        while True:
            try:
                line = sys.stdin.readline()
                if line:
                    self.input_queue.put(line) # 如果队列满了会阻塞等待，形成背压
                else:
                    break 
            except:
                break

    def log(self, message):
        if not self.log_file: return
        timestamp = time.strftime('%H:%M:%S')
        try:
            self.log_file.write(f"[{timestamp}] {message}\n")
        except: pass 

    def receive_state(self, timeout=None):
        """
        [主线程调用] 
        支持 timeout 参数。
        - timeout=None: 非阻塞模式 (立即返回数据或None)
        - timeout=float: 阻塞等待模式 (直到有数据或超时)
        """
        try:
            # 如果 timeout 是数字，就会阻塞等待；如果是 None，就是非阻塞
            block = (timeout is not None)
            line = self.input_queue.get(block=block, timeout=timeout)
            return json.loads(line)
        except queue.Empty:
            return None
        except json.JSONDecodeError:
            return None
        except Exception:
            return None

    def send_command(self, cmd):
        try:
            print(cmd.strip(), flush=True)
            if cmd != "state":
                self.log(f"Send -> {cmd}")
        except:
            pass

    def close(self):
        try:
            if self.log_file: self.log_file.close()
        except:
            pass