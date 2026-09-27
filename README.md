# MAPS: A Multi-Platform Auction-aware Parcel Assignment System for Cooperative Urban Logistics

[English](README.en.md) | [中文](README.md)

MAPS 是基于 MPCS 多平台包裹分配仿真器构建的交互式系统演示。观众可以配置工作负载、运行仿真，并沿着**工作负载 → 包裹 → 本地决策 → 竞价 → 结算**追踪目标平台的取件包裹。本文说明系统功能、研究基础、架构和观众交互，对应 [VLDB Demonstrations Track](https://vldb.org/2026/call-for-demonstrations.html) 强调的内容。

## 研究基础

MAPS 依托 Guanglei Zhu 等人的研究手稿 *Auction-Aware Crowdsourced Parcel Assignment for Cooperative Urban Logistics*。该研究讨论跨平台城市物流（CPUL）问题：平台在配送员执行既有送件任务时分配持续到达的取件包裹，并可使用合作平台的空闲配送员。

| 研究组成 | 手稿提出的方法 |
| --- | --- |
| CAPA 与 CAMA | CAPA 按批处理到达的包裹。CAMA 根据剩余容量和路线绕行评估可行的本地配送员与包裹配对，使用动态效用阈值，并将未在本地分配的包裹送入竞价池。 |
| DLAM 与 DAPA | 双层竞价首先通过第一价格密封竞价在各合作平台内部选择配送员，再通过平台间的逆向维克里竞价确定服务平台和支付额。 |
| RL-CAPA | 两个学习策略自适应地调整分配过程：第一阶段选择批次时长，第二阶段逐包裹决定延后至下一批还是进入竞价池。论文以收益、完成率和批次处理时间研究该自适应方法及 CAPA。 |

MAPS 中的 **RL-CAPA** 选项按照 Simulation 中选择的帧间隔运行当前 MPCS 的 CAMA/DAPA 分配流程。Inspection 展示该次运行记录的本地候选、阈值、合作平台报价、获胜分配和结算结果。

## 系统演示

```mermaid
flowchart LR
    A[数据集和界面设置] --> B[MPCS 场景准备]
    B --> C[共享物理帧]
    C --> D[本地匹配与合作平台竞价]
    D --> E[结算与 JSON 回放]
    E --> F[批次检查与时间窗分析]
```

| 模块 | 观众操作与展示结果 |
| --- | --- |
| **Simulation** | 选择数据集和划分、到达时间窗、各平台同城且互不重复的订单日期、取件与送件采样数或全部有效订单、配送员数量、服务半径、期限、帧间隔、随机种子、目标平台及一个或多个算法；运行场景并查看进度和目标平台结果摘要。 |
| **Inspection** | 选择算法，播放或逐步查看批次与五个处理阶段；检查包裹状态、本地候选、合作平台报价、支付以及目标平台决策档案；在可缩放平移的完整处理后路网上查看站点、移动中的配送员及其路线、未匹配的目标包裹和匹配连线。 |
| **Analysis** | 对比目标平台的 OP、AR、BPT、本地与跨平台分配、累计与逐分钟账本收益，以及目标平台到服务平台的流向；下载回放。 |

选定的目标平台对自己的包裹执行待比较的决策。合作平台先在本地处理自己的任务，再提供剩余的可行配送员运力。对比运行使用相同的采样订单、初始配送员队伍和随机种子。平台颜色区分配送员，目标平台会突出显示。地图不绘制区域多边形。

## 安装与启动

需要 Python **3.11 或更高版本**。在仓库根目录运行：

```powershell
python -m pip install -e ".[demo]"
python -m maps_demo.app
```

打开 **http://127.0.0.1:8050**。默认 `Synthetic` 数据集不需要外部数据。也可以使用安装后的 `maps-demo` 命令启动。

### 操作示例

1. 在 **Simulation** 中保留 `Synthetic`、`Test`、目标平台 `P1` 和随机种子 `11`。将 **Pickup sample** 设为 `Count`、**Pickups per platform** 设为 `10`、**Dropoffs per platform** 设为 `0`、**Couriers per platform** 设为 `2`、到达时间窗设为 `00:00–00:01`。选择 **RL-CAPA** 并点击 **Run simulation**。该配置会产生跨平台匹配。
2. 在 **Inspection** 中使用时间线箭头或 **Play**，依次查看 **Workload**、**Parcel**、**Local decision**、**Auction** 和 **Settlement**。检查被释放包裹的本地候选、合作平台报价、获胜者、支付额和配送员路线。
3. 在 **Analysis** 中查看目标平台的分配与收益指标。逐分钟折线表示账本增量，累计折线表示其运行总额。
4. 返回 **Simulation**，选择 **Compare algorithms**，从 `RL-CAPA`、`ImpGTA`、`MRA`、`Greedy`、`RamCOM` 和 `LocalSum` 中至少选择两个算法并重新运行。在 Inspection 中切换 **Displayed algorithm**，在 Analysis 中比较结果，再使用 **Download replay JSON** 保存运行产物。

运行后修改控件不会更新当前回放；点击 **Run simulation** 才会应用新设置。

### 真实城市数据

`Chengdu`、`Shanghai` 和 `Shanghai 16` 需要位于 `dataset/` 下的本地处理后包裹文件及对应城市路网。这些文件不纳入 Git。成都处理后文件应放在 `dataset/Didichuxing/Chengdu/parcel_v2/`；[mpcs/arguments.py](mpcs/arguments.py) 定义了预期的路网路径。如果本地已有成都原始数据，可用以下命令生成 parcel-v2 文件：

```powershell
python -m mpcs.utils.DataUtils `
  --source-root dataset/Didichuxing/Chengdu/dataset `
  --output-root dataset/Didichuxing/Chengdu/parcel_v2 `
  --seed 20250308
```

运行真实城市场景时，为每个平台选择同一城市中互不重复的订单日期。有效订单表统计所选到达时间窗和运营区域内经过解析、去重的订单。取件和送件可分别选择指定采样数或 **All eligible**。`Train`、`Validation` 和 `Test` 均可选；平台日期决定所选划分使用的源文件。真实城市预设的平台数固定，Synthetic 支持 2–16 个平台。

## 指标与回放

| 指标 | MAPS 中的含义 |
| --- | --- |
| **OP** | 到达时间窗截止时目标平台的账本收益，包括本地、跨平台和既有送件业务的收益。 |
| **AR** | 截止时已分配的目标平台取件包裹数，除以目标平台采样取件包裹总数。 |
| **BPT** | 目标平台非空批次的平均决策耗时，以毫秒计；包含策略、本地匹配和竞价计算，不包含配送员移动。 |
| **Profit per minute** | 目标平台账本每分钟的收益增量；增量之和等于展示的 OP。 |

仿真会继续处理未到取件期限的任务，但 Analysis 在所选到达时间窗结束时截断。若时间窗为 `10:00–11:00`，图表和汇总指标只使用 `11:00` 之前的帧；后续帧仍可在 Inspection 中查看。一次对比只对应一个配对随机种子的场景；若要得出一般性的性能结论，应使用更多种子重复运行。

最新运行保存在 `output/maps-demo/latest.json`。**Load last replay** 可在不重新仿真的情况下打开该文件；**Download replay JSON** 可导出当前运行。对比回放共用一份路网和包裹目录，每个算法分别保存决策轨迹和摘要。

## 代码与研究命令行

| 组件 | 职责 |
| --- | --- |
| [maps_demo/app.py](maps_demo/app.py) | Dash 控件、进度、回放与分析。 |
| [maps_demo/engine.py](maps_demo/engine.py) | 场景构建，以及批次决策、快照、回执和指标的记录。 |
| [maps_demo/capa.py](maps_demo/capa.py)、[maps_demo/ramcom.py](maps_demo/ramcom.py) | 本地释放与跨平台算法适配。 |
| [maps_demo/geography.py](maps_demo/geography.py)、[maps_demo/figures.py](maps_demo/figures.py) | 处理后的路网与站点图层、地图回放和图表。 |
| [mpcs/core/Framework.py](mpcs/core/Framework.py) | 共享时钟、任务分配、移动与结算。 |

研究命令行还提供数据集与算法列表、基线运行、混合平台实验、PPO 训练、完整流程和多种子 sweep。例如：

```powershell
python -m mpcs datasets
python -m mpcs algorithms
python -m mpcs run --dataset synthetic --split test `
  --methods localsum mra --output output/synthetic-baselines
```

后端与插件接口见[架构文档](docs/architecture.md)和[扩展指南](docs/extending.md)。
