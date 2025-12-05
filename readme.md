# 🗡️ 杀戮尖塔强化学习（RL）智能体
基于 **Gymnasium** 和 **Stable-Baselines3 (Maskable PPO)** 构建的《杀戮尖塔》强化学习训练环境，通过与游戏 **[CommunicationMod](https://github.com/ForgottenArbiter/CommunicationMod)** 交互，实现AI智能体的训练与优化。

## 🛠️ 项目目录结构
```text
Project Root/
├── main.py                 # 训练入口，配置模型与回调函数
├── spire_env/              # Gym 环境核心包
│   ├── env.py              # 主环境类 (SlayTheSpireEnv)，整合各功能模块
│   ├── definitions.py      # 动作空间与观察空间定义
│   ├── interface.py        # 底层 Stdout/Stdin 游戏通讯接口
│   └── logic/              # 核心逻辑处理模块
│       ├── game_io.py      # 游戏状态读取与缓冲区清洗
│       ├── combat.py       # 战斗同步与防抖逻辑
│       ├── navigator.py    # 非战斗场景自动导航（地图/事件/商店）
│       └── reward.py       # 奖励函数计算逻辑
└── utils/
    ├── action_mapper.py    # 动作编解码与 Mask 掩码生成
    └── state_encoder.py    # 状态特征提取（状态→向量转换）
```

## 🚀 环境搭建与运行指南
### 1. 游戏端准备
1. 安装 Steam 版《杀戮尖塔》；
2. 订阅并启用创意工坊 Mod：
   - **ModTheSpire**（Mod加载器）
   - **BaseMod**（基础依赖库）
   - **CommunicationMod**（核心通讯接口）
   - *(可选) SuperFastMode（极速模式，推荐开启以提升训练效率）*

### 2. 配置 CommunicationMod
修改配置文件，让游戏能正确启动Python训练脚本：
1. 找到配置文件 `communication_mod.config.properties`（不同系统路径）：
   - Windows: `%LOCALAPPDATA%\ModTheSpire\`
   - Linux: `~/.config/ModTheSpire/`
   - Mac: `~/Library/Preferences/ModTheSpire/`
   - 若找不到，参考 [ModTheSpire Wiki - SpireConfig](https://github.com/kiooeht/ModTheSpire/wiki/SpireConfig)
2. 编辑 `command` 字段，指向Python解释器和项目入口文件：
```properties
# Windows 示例（注意路径分隔符）
command=D:/Anaconda/envs/spire_ai/python.exe D:/Projects/SlayTheSpireAI/main.py
```

3. Python 环境准备
建议使用虚拟环境隔离依赖，通过requirements.txt安装：

```bash
# 1. 创建虚拟环境
python -m venv venv

# 2. 激活虚拟环境
# Windows:
.\venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 3. 安装依赖（可选清华源加速）
pip install -r requirements.txt
# 或使用清华源
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

### 4. 启动训练
1. 启动《杀戮尖塔》，在Mod加载器中勾选上述Mod并点击 **Play**；
2. 游戏启动后，CommunicationMod 会自动拉起Python训练脚本；
3. 观察Python控制台或 `logs/ai_debug_log.txt`，出现 `>>> 环境重置 >>>` 即代表训练开始。

> 💡 性能优化：训练时将游戏窗口最小化，可停止图形渲染，大幅降低CPU占用、提升训练FPS。

## 📊 训练监控（Visualization）
项目集成TensorBoard记录训练曲线（奖励变化、Loss等），训练中执行以下命令启动监控面板：
```bash
tensorboard --logdir logs/sb3
```

启动后在浏览器访问 `http://localhost:6006`，即可查看实时训练图表。

## 📈 奖励设计（Reward Shaping）
当前奖励函数（`logic/reward.py`）包含以下维度：
- **伤害奖励**：对敌人造成伤害（+）；
- **格挡奖励**：获得有效格挡（不超过敌人攻击力）（+）；
- **击杀奖励**：消灭敌人（++）；
- **过层奖励**：爬至下一层（+）；
- **受伤惩罚**：自身掉血（-）。

## 🧠 一些改动（Core Architecture）

### 1. 感知：从哈希到独热编码（State Encoder）
- ❌ 原有问题：使用`zlib.crc32`哈希编码卡牌，导致神经网络无法识别卡牌关联（如“打击”和“完美打击”哈希值无关联），AI对卡牌“脸盲”；
- ✅ 解决方案：实现固定词表的**独热编码（One-Hot Encoding）**：
  - 每张卡牌对应独立的输入维度（神经元）；
  - 能量（Energy）编码为独热向量（0-5+），而非标量，让网络学习非线性阈值（如“仅当能量≥4时使用高费卡牌”）；
  - 金币（Gold）使用`Log10`缩放，让AI对前期经济差异（50 vs 150金币）敏感，同时忽略后期通胀。

### 2. 决策：动作空间扁平化（Action Mapper）
- ❌ 原有问题：原始动作空间为`Discrete(14)`（卡牌1-10、药水1-3），AI仅能选择卡牌，无法指定目标，默认攻击第一个敌人，无法优先处理高威胁目标；
- ✅ 解决方案：将动作空间扁平化为`Discrete(67)`：
  - 公式：`ActionID = (卡牌索引 × 5个目标) + 目标索引`；
  - 效果：AI可精准输出“对第二个敌人使用猛击”等指令；
  - 智能掩码：ActionMapper 动态屏蔽无效目标（如已死亡敌人），精简搜索空间。

### 3. 价值：“恐惧因子”非线性奖励（Reward Shaping）
- ❌ 原有问题：线性奖励函数对血量损失一视同仁（80/80掉5血 vs 6/80掉5血惩罚相同），导致AI贪伤害、易暴毙；
- ✅ 解决方案：引入**非线性生存惩罚**：
  - 公式：$R_{loss} = \text{BaseLoss} \times (1 + 2 \times (1 - \text{HPRatio})^2)$
  - 行为逻辑：
    - 满血（100% HP）：惩罚系数≈1.0x（激进）；
    - 残血（10% HP）：惩罚系数飙升至≈2.6x（保守）；
  - 资源管理：使用药水新增小额负奖励（-3.0），让AI理解“成本”，避免在小怪战浪费药水。

## 🔄 更新日志（Changelog）
### v1.0.4 - 动作空间升级
- 目标精准化：AI不再局限于攻击第一个敌人，可指定卡牌/药水的目标；
  - 机制：动作空间扁平化为`Discrete(67)`；
  - 逻辑：`ActionID = (卡牌索引 × 5) + 目标索引`；
- 智能掩码：ActionMapper 自动屏蔽无效目标（如死亡敌人），AOE/能力卡默认“目标0”以精简搜索空间。

### v1.0.3 - 感知层重构
- 状态编码重构：
  - 哈希编码 → 独热编码，AI可精准区分卡牌类型；
- 特征工程优化：
  - 金币：线性归一化 → Log10缩放，提升低金币阶段敏感度；
  - 能量：标量 → 独热向量，学习能量非线性阈值；
  - 血量：新增“濒死状态（HP < 15%）”布尔特征，强化生存本能。

## 📝 未来计划（TODO）
- [ ] 完善商店购买逻辑（当前为强制跳过）；
- [ ] 增强事件决策逻辑（当前多为随机/固定选择）；
- [ ] 接入LSTM/Transformer，处理长短期记忆；
- [ ] 适配更多角色（当前主要适配铁甲战士）。

---

**许可证（License）**：MIT