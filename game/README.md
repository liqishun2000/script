# 中国象棋（带窗口 GUI + 三种 AI 引擎）

基于 Python 标准库 `tkinter` 的中国象棋游戏，并集成了三种可切换的 AI 引擎，
其中包含可在本地**自对弈训练**的 AlphaZero 式神经网络。

## 运行

```bash
py chinese_chess.py
```

仅运行游戏本体（内置 AI）无需任何第三方依赖。

## 功能

1. **完整基础玩法**：车马炮相仕将兵卒全部走子规则，含蹩马腿、塞象眼、炮翻山、
   过河卒、九宫、将帅照面（白脸将）、将军/将死/困毙判定。
2. **人机 / 双人对战**：可选玩家执红或执黑。
3. **AI 预测下一步**：橙色箭头高亮当前方最佳走法（仅提示不落子）。
4. **实时局面评分**：右侧显示红方视角评分与优势进度条。
5. **三种可切换 AI 引擎**：

| 引擎 | 说明 | 依赖 |
|---|---|---|
| **内置AI** | alpha-beta 搜索 + 手写评估，难度=搜索深度 1~4 | 无 |
| **Pikafish** | 外部 UCI 超强引擎（Stockfish 衍生 + NNUE），棋力远超人类 | 需下载引擎，见下 |
| **AlphaZero** | 本地自对弈训练得到的神经网络模型 | 需 `torch`，见 `az/` |

难度（简单/普通/困难/大师）对各引擎的含义：
- 内置AI：搜索深度 1 / 2 / 3 / 4
- Pikafish：每步思考时间 0.1 / 0.4 / 1.5 / 4 秒
- AlphaZero：MCTS 模拟 50 / 200 / 600 / 1200 次

## 文件结构

| 文件/目录 | 作用 |
|---|---|
| `chinese_chess.py` | tkinter 窗口主程序（交互、绘制、引擎调度） |
| `xiangqi_core.py` | 规则核心（无 GUI 依赖）：走法、判负、评估、FEN/UCI、NN 编码 |
| `pikafish_engine.py` | Pikafish 外部引擎（UCI）封装 + 自动检测 + 安装说明 |
| `az/` | AlphaZero-lite 自对弈训练管线（详见 `az/README.md`） |

## 启用 Pikafish（立即获得超人棋力）

1. 到 https://github.com/official-pikafish/Pikafish/releases 下载：
   可执行文件（如 `pikafish-windows-x86-64.exe`）+ 权重 `pikafish.nnue`。
2. 把可执行文件重命名为 `pikafish.exe`，连同 `pikafish.nnue` 放到 `game/engines/` 目录；
   或设置环境变量 `PIKAFISH_PATH` 指向它。
3. 在 GUI「AI 引擎」中选择 **Pikafish**。未安装时选中会弹出下载指引。

## 训练自己的 AlphaZero 模型

```bash
py -m pip install -r az/requirements.txt
py az/train.py            # 开始自对弈训练（可 Ctrl+C 中断续训）
```

训练得到 `az/checkpoints/best.pt` 后，在 GUI「AI 引擎」选 **AlphaZero** 即可对战。
完整说明与**算力现实**见 `az/README.md`。

## 操作

- 点击己方棋子选中（绿框），合法落点以蓝点/蓝框提示，点击落点完成走子。
- 「新游戏」「悔棋」「AI 预测下一步」位于右侧面板。
