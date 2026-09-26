# 算法、论文与实验资产证据审计

> 历史审查（2026-09-20）。算法事实保留；统一事件平台、分叉等建议已不属于首版。2026-09-21起实施范围以[轻量需求](../02-需求与验收.md)为准。

审计日期：2026-09-20。范围：`D:\Code\auction_aware_task_assignment` 当前工作区；只读静态检查，未修改算法仓库，未运行训练或重现实验。下文“存在”表示源码或产物可见，不表示已验证复现成功。行号以本次工作区为准，用户后续修改可能改变行号。

## 1. 真实架构与版本基线

该仓库已具备算法引擎、道路仿真、实验运行器、训练和图表产物，适合构建算法可解释演示系统；目前缺少能完整重放候选筛选、两层竞价、RL策略和路径变化的事件层。

真实入口是根目录 `runner.py`、`algorithms/registry.py` 和各算法 runner；CAPA 入口实际调用 `env/chengdu.py` 的 `run_time_stepped_chengdu_batches`，不是简单调用 `capa/runner.py`。前者负责道路移动、批次末决策、历史配送任务、重复候选与完成/超时核算。后者是较简单的核心编排器，直接调用它容易得到不同的完成率语义。[CAPA入口](D:/Code/auction_aware_task_assignment/algorithms/capa_runner.py:93)、[共享仿真](D:/Code/auction_aware_task_assignment/env/chengdu.py:2006)。

模块关系为：数据/路网→`ChengduEnvironment`→共享批次运行时→CAMA→DAPA→legacy路线提交与推进→完成核算；RL环境复用CAMA及共享跨平台匹配，两个策略控制批长和包裹分流。Greedy、MRA、RamCOM、BaseGTA、ImpGTA均已有实现与runner，部分属于CPUL适配版本，不能仅按名称认定与原论文完全等价。

`AGENTS.md` 和 `docs/agent.md` 引用的下划线论文路径不存在；实际论文为[空格名版本](<D:/Code/auction_aware_task_assignment/docs/Auction-Aware Crowdsourced Parcel Assignment for Cooperative Urban Logistics.md:217>)。最新论文已使用分层策略梯度，旧实现规范的DDQN要求已过期；`docs/rl_capa_algo.md:3` 也明确废弃DDQN。演示不能沿用“两个DDQN”的旧标签。

## 2. 各阶段可展示内容与准确语义

| 阶段 | 真实输入、运算与输出 | 建议展示 |
|---|---|---|
| 到达与分批 | 任务到达时间、真实/观测截止期、backlog、批末时间；输出可处理/过期任务 | 时间线、供需热力、批窗拖动、过期原因 |
| 候选筛选 | courier可用性、载重、服务半径、可插入位置及下游截止期 | 包裹—骑手二部图、逐条件筛除、可行与不可行路径 |
| CAMA | 计算容量余量和绕路比，选局部候选；现代码用收益阈值决定本地接受 | 可行矩阵、阈值分布、候选排序、接受前后路线 |
| FPSA | 平台内可行骑手报价，最高报价骑手代表平台 | 各平台独立报价卡片，偏好项、绕路项、质量项分解 |
| RVA | 平台报价、支付上限过滤、最低有效报价获胜；通常支付次低报价 | 跨平台排序、上限线、获胜报价与实际支付分开显示 |
| 提交与配送 | 插入路线、累计载荷、逐段移动、真实截止期核算 | 轨迹回放、ETA与slack、accepted/delivered/timeout漏斗 |
| RL决策 | π1输出离散批长分布，π2输出每包裹跨平台概率 | 原始/归一化状态、概率条、采样动作、后续收益反馈 |

核心经济账应逐包裹闭合：本地完成时骑手收入为 `ζp`、本地平台收入为 `(1−ζ)p`；跨平台时令骑手支付为 `b_c`、平台支付为 `p_P`，三方分别得到 `p−p_P`、`p_P−b_c`、`b_c`，总和为票价 `p`。它是收入分配，不是扣除所有实际成本后的社会福利。[Assignment结构](D:/Code/auction_aware_task_assignment/capa/models.py:189)、[跨平台账本](D:/Code/auction_aware_task_assignment/capa/dapa.py:166)。

FPSA代码为 `base_price + (α·detour + β·service_score)·platform_gamma·μ1·fare`，平台内取最大值；不要因其含“成本”而把界面错误改成最低者获胜。RVA通常为 `b_c + quality_factor·μ2·fare`，总支付上限为 `(μ1+μ2)·fare`；只有一个有效平台时另有支付规则。`λ`敏感性模式会改变出价基数并直接按总上限支付，必须显示为独立实验变体，不能仍解释成“次价支付”。[FPSA](D:/Code/auction_aware_task_assignment/capa/dapa.py:108)、[竞价与支付](D:/Code/auction_aware_task_assignment/capa/dapa.py:290)。

## 3. 投稿前必须解决的语义差异

### A. CAMA已不是论文所写的效用阈值与KM

论文Eq.6/7规定基于效用 `u` 的累计阈值，最新Algorithm 2末尾明确执行KM。当前代码虽然计算效用，但用 `(1−ζ)·fare` 更新阈值并接受任务；每包裹预选一个best courier，再依次提交，重新验证失败后进入拍卖池，没有在CAMA内执行KM。[论文Eq.6/7](<D:/Code/auction_aware_task_assignment/docs/Auction-Aware Crowdsourced Parcel Assignment for Cooperative Urban Logistics.md:127>)、[论文KM](<D:/Code/auction_aware_task_assignment/docs/Auction-Aware Crowdsourced Parcel Assignment for Cooperative Urban Logistics.md:154>)、[收益阈值与提交](D:/Code/auction_aware_task_assignment/capa/cama.py:229)。

影响：匹配机制、阈值量纲和路径依赖均不同。收入阈值应标货币单位，效用阈值为无量纲。演示不能绘制虚构的KM增广步骤。应在实现修订或论文修订之间明确选择，并保存 `algorithm_semantics_version`。论文关于最小绕路比与文字“最小额外距离”、伪代码KM与复杂度 `O(nm)` 也存在内部歧义，需要作者统一，不能简单把所有偏差归为代码错误。

### B. 第二阶段动作从“延期/竞价”变为“先本地/直接竞价”

论文第227行规定 `a=0` 延期下一批，`a=1` 进入拍卖池；代码却对 `a=0` 先跑CAMA，并将本地失败者同批加入DAPA。因此 `cross_rate` 统计的是策略选择直接跨平台的比例，不等于最终跨平台成交比例。[动作实施](D:/Code/auction_aware_task_assignment/rl_capa/env.py:242)。这是不同MDP，不是按钮改名即可解决；展示必须分别记录 `policy_action`、`dispatch_path`、`assignment_mode`，并在正式投稿前冻结动作语义。

### C. 未来状态含真实未来数据

`get_stage1_state`把 `_count_future_parcels` 的结果输入策略；该函数直接遍历未到达任务流，统计未来窗口的真实到达数。论文描述通过GRU等预测供需。[特征入口](D:/Code/auction_aware_task_assignment/rl_capa/env.py:137)、[真实未来读取](D:/Code/auction_aware_task_assignment/rl_capa/env.py:610)、[论文预测](<D:/Code/auction_aware_task_assignment/docs/Auction-Aware Crowdsourced Parcel Assignment for Cooperative Urban Logistics.md:222>)。

影响：离线已知未来的oracle策略不能当作可部署在线预测策略，更不能与仅使用当前信息的基线无条件比较。需要历史可用信息预测器、无预测消融及单列oracle上界。未来骑手可用时间若来自已知计划则未必泄露，但应记录其信息可见性；不能笼统将所有future字段判为泄露。

### D. 实际训练为五网络扩展

当前trainer实例化π1、π2、Q1、V1、V2共五个网络，注释仍写四网络；第一阶段优势是 `Q1(s,a)−EπQ1(s,a)`，不是论文 `V2−V1`；V2拟合即时回报而非论文累计回报。状态实际维数为8与11/12，也高于论文6与9。[网络创建](D:/Code/auction_aware_task_assignment/rl_capa/trainer.py:168)、[训练目标](D:/Code/auction_aware_task_assignment/rl_capa/trainer.py:521)、[维数](D:/Code/auction_aware_task_assignment/rl_capa/state_builder.py:20)。这些可作为明确扩展，但须先统一方法、checkpoint元数据和解释图。π输出的是概率，不能标成Q值；Q1也不自动构成DDQN。

### E. 指标与数据名称不能直接照抄

代码BPT为每批平均决策时间，排除单独计时的routing/insertion/movement；应同时展示端到端wall time、决策时间及各排除项，统一基线计时边界。[指标实现](D:/Code/auction_aware_task_assignment/capa/metrics.py:34)。已有`exp4.../results_summary.md`将BPT误写为“cross revenue per unit time”，不应直接导入其文字说明。

`ny`、`formal`首先是Chengdu实验预设名称。当前可见数据包括 `map_ChengDu`、`order_20161101_deal`、pick-up/delivery文本；加载器也明确读取成都路网。仅有ny配置不能证明已使用NYTaxi真实数据。[数据加载](D:/Code/auction_aware_task_assignment/env/chengdu.py:655)、[预设](D:/Code/auction_aware_task_assignment/experiments/paper_config.py:17)。投稿须另核对源数据、许可证、坐标与划分清单。

## 4. 插桩位置与现有日志缺口

建议加可选、只观察的 `TraceSink`，默认关闭；研究结果与无插桩执行保持一致，不让前端重写算法。

| 插桩位置 | 事件及需保存字段 |
|---|---|
| `env/chengdu.py:1577 prepare_chengdu_batch` | batch_open/close，起止时间、到达/积压/过期列表，快照ID |
| `capa/cama.py:179 run_cama` | candidate_checked、utility_evaluated、threshold_updated、local_decided；拒绝原因、各分量、选中位置、旧新路线 |
| `capa/dapa.py:222 run_dapa` | courier_bid、fpsa_winner、platform_bid、rva_rejected、rva_settled；完整报价、阈值、排名、支付分支 |
| `env/chengdu.py:1677/1841/1927` | assignment_committed、batch_finalized；本地/跨平台提交和未解决任务 |
| `env/chengdu.py:1136` | delivered、deadline_missed、route_advanced；真实完成时间和截止期 |
| `rl_capa/env.py:137/193/242`及策略forward调用处 | state_observed、policy_evaluated、action_sampled；原始状态、归一化状态、完整概率、动作、seed |

现有 `decision_trace` 仅是最终parcel_id/mode/courier_id/delivered/on_time/revenue列表，没有阶段、时间、理由、位置、报价和策略概率，不能称为全过程回放。[生成器](D:/Code/auction_aware_task_assignment/algorithms/summary_utils.py:10)。`DAPAResult.platform_bids`只保留有效平台报价，且`PlatformBid`没有parcel_id；失败报价、每个落选骑手及对应包裹关联必须在运算时新增记录。对象含可变courier引用，事件必须存不可变数值快照，不能延迟序列化最终对象冒充历史状态。

统一事件应带 `run_id/event_seq/sim_time/batch_id/parcel_id/courier_id/platform_id/config_hash/seed/algorithm_version/checkpoint_hash`。完整候选只对聚焦包裹或小样本记录；规模实验保存聚合及可追索采样，测量trace开销。反事实比较需从同一快照分叉重跑，并记录相同数据与随机状态；只移动图上阈值不能当作实验结果。

## 5. 已有成果可用程度

已确认存在500轮真实结构的训练日志数组（episode_returns、actor/critic loss、entropy、cross_rate、batch_size_sequences）、训练图、多个pi1/其他模型checkpoint文件、规模/合作平台数/收益分成/截止期干扰等实验产物。这足以启动离线结果浏览器与小场景原型；尚未验证checkpoint与当前五网络及状态维度完全兼容。

例如[100包裹对比产物](D:/Code/auction_aware_task_assignment/outputs/plots/rl_capa_compare_v2/comparison.json)记载RL-CAPA TR=402.41、CR=0.95，CAPA为334.21、0.89，而BaseGTA/ImpGTA为690.64、1.0。它支持展示策略取舍，不支持宣称RL-CAPA全面最优。该例是小规模联调配置，不能代表论文总体实验。[训练产物](D:/Code/auction_aware_task_assignment/outputs/plots/rl_capa_compare_v2/rl-capa/training_summary.json)包含service-slack变体标识。评估默认随机采样而非argmax，须保存评估seed并将单次轨迹与多seed均值区分。[评估采样](D:/Code/auction_aware_task_assignment/rl_capa/evaluate_core.py:51)。

演示建设顺序应为：冻结论文/代码/数据语义→核验一套可重复小场景→事件与快照→算法解释页→反事实与多算法比较→规模和敏感性结果页。优先把一个包裹“为什么没留本地、谁出价、为什么该平台赢、为何这样付钱、最后是否准时”完整串起，再扩大场景规模。这最能把现有成果转成可审查的研究型demo。
