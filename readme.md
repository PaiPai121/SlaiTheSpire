[CommunicationMod](https://github.com/ForgottenArbiter/CommunicationMod)
配置文件目录：
```bash
https://github.com/kiooeht/ModTheSpire/wiki/SpireConfig
```
启动tensorboard
```bash
tensorboard --logdir logs/sb3
```

SlaiTheSpire/                <-- 项目根目录
│
├── venv/                    <-- 虚拟环境
├── logs/                    <-- 存放日志文件 (ai_debug_log.txt)
├── models/                  <-- 存放训练好的模型文件 (.pth, .zip)
│
├── spire_env/               <-- 【核心包】自定义环境逻辑
│   ├── __init__.py          <-- 标识这是一个Python包
│   ├── interface.py         <-- 负责 stdin/stdout 通信
│   ├── env.py               <-- 核心 Gym 环境类 (SlayTheSpireEnv)
│   └── definitions.py       <-- 存放常量 (比如卡牌ID列表、动作枚举)
│
├── utils/                   <-- 【工具包】数据处理
│   ├── __init__.py
│   ├── state_encoder.py     <-- 将 JSON 转换成 [0, 1, 0.5...] 向量
│   └── action_mapper.py     <-- 将 AI 输出的数字转换成 "play 1 0" 指令
│
├── agents/                  <-- 【大脑】存放各种 AI 算法
│   ├── __init__.py
│   ├── rule_based_bot.py    <-- 我们刚才写的那个 if-else 脚本
│   └── ppo_agent.py         <-- 未来要写的强化学习模型
│
├── main.py                  <-- 【入口】程序启动点 
└── requirements.txt         <-- 依赖库列表