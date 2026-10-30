# gf_admission 实施与验收记录：0.1.0rc2

> 2026-10-30 当前状态：rc2 最终桌面交付和[Session 2 本地复评](GF_ADMISSION_0.1.0rc2_REVIEW_20261022.md)均已完成。用户本次批准阶段性合入 main 并推送，作为[下一轮研发基线](DEVELOPMENT_BASELINE_20261030.md)。华为短验证、H/L 标定及正式性能结果仍未完成；下文保留 10 月 22 日各阶段原记录。


更新：2026-10-22；开发分支 backup/20261022-init；g5 起点3b63b00546e7a6ffb2526dafc341969cebe22359。

当前已完成本地代码修复、统一高压触发、观测与现场工具，独立解包与wheel验证已通过，准备最终桌面交付。rc1已撤回；其旧测试/交付记录是历史，不能解释为缺陷已通过。Session2对rc2复评、华为短验证及性能均未完成；不合并main。

## 已实现

- R1：受约束submission_round，实际Motor同attempt资源恢复可成功，旧事务不可复活；传输重试/丢ACK不换key；新一轮刷新payload/generation，逻辑分类/credit只一次。
- R2：过期owner清理不恢复lease；失联CLAIMED仅按同记录两账释放证据收敛；未知状态保留。
- R3：准备总deadline与并发许可覆盖metadata RPC＋线程，真实线程结束才归还许可，取消传播。
- R4：残留先筛后分页，有total/truncated。
- 统一(cost长 OR 最低候选score高)触发，共享预算；normal优先、tail低阈值L放行、年龄保护；schema2拒绝旧配置/worker。无实验专用开关。
- 分类原因、派发来源、晋升原因、LIFO越序计数及有界事件环；每P FG W/N/score/event_age可通过认证状态接口采样。锁内诊断写内存，不新增文件日志。
- 压力collect/summarize/freeze工具；独立后台watchdog，不依赖agent高频轮询，现场health/notify适配器须实接并演练。
- 六格正式计划、完整华为prompt，B16×实际66K/128K已有结果优先/必要短探测决定静态H/L；下一版才考虑TTFT预测动态指标。

## 本地证据

Python 3.13.11：项目96 passed；Motor相关309 passed、8 skipped。非两次独立性能实验，均为CPU逻辑/接口测试。7项skip因无libmindie_workload_shm.so，1项为原Motor endpoint model_validate已存在skip。未运行Python3.12/910B2/完整真实P/D/AISBench。

真正Motor DEALER/ROUTER＋msgpack、多客户端和独立Python子进程、丢ACK与typed cancellation仍覆盖；同一真IPC测试扩展到已验证身份的FG事件→高压同成本tail→新tail优先READY/claim→旧tail取消→两账归零。SHM为FakeNative，不能称原生CAS实机通过。

R1真UnifiedPD回归、R2四种清理路径、R3慢metadata并发和总deadline、R4晚出现残留均有定向拦截；原super-p95 oracle夹具未改，低压力成本分支继续对照原型；高压扩展单独测。已有安装/回退/未知hash拒绝测试通过。新脚本测试覆盖压力窗口汇总/缺P拒收/冻结校验、后台健康异常停止自有进程并通知。

新改动范围Ruff通过；原Motor runtime两钩子此次未改。全Motor pre-commit历史仍有gitleaks缺二进制和旧g5格式问题，未把它宣称全绿。25份runtime contract保护文件核对匹配，包括本地observe-only文件；不冒充远端字节一致。

原始日志/XML：artifacts/gf-admission-rc2；摘要及源码hash：evidence/manifests/gf_admission_rc2_20261022.json。包内复制到evidence/local。解包安装与测试完成后在交付记录记录最终结果；不能将待执行写成通过。

## 已知边界与下一步

- 真实Python3.12/native SHM、Conductor/tokenizer、原生P/D生命周期、故障回退仍待华为短验证。
- 0<L<H为静态实验超参数，enforce模板null主动拒绝未配置；shadow小数值为观测占位，不能声称标定。按等待窗口探测每长度选一组H/L，同长度B16/18/20保持一致。
- quota1/20、tail2、驻留5s是首轮候选；入场调节与真实LIFO分别归因，无越序不冒称LIFO效果。参数作用与性能未在NPU确认。
- 全局事件freshness仍是保守屏障；一个活跃P事件陈旧可停止新增tail/晋升。没有改为猜测闲忙。必须按实测事件间隔校准并报告陈旧占比。
- 事件环有界可能覆盖中间事件，累计计数仍保留；采样时记录sequence缺口。pump_ms不是锁时长硬上限，CPU测试不证明高压控制面开销。
- 无自动Mgmt崩溃重建/分布式共识；未知native outcome保留并停派发，需要现场对账。两账清空不等于D/E2E结束。
- watchdog代码已本地验证；现场agent唤醒接口尚未提供，必须由现场接入真实适配器并演练。没有接口则明确无法自动唤醒，不虚构无人值守恢复。

下一步为完整新包复评→华为短验证/阈值探测/通知演练→冻结六格实验→回传原始证据/吸收现场修复→评估收益及main合并条件。无需用户再收集整套环境或GB流量。


## 交付候选独立验证补充

独立解包目录随包75项通过；wheel全部gf_admission源码及runtime contract逐字节一致，pip --target隔离导入与兼容验证通过。第一次解包发现子进程测试脚本误引入本地测试helper（开发PYTHONPATH掩盖），已删除无用导入并在仅包内src的环境重验；失败原日志保留在evidence/local/extracted-initial-failure.log，未把失败隐藏。最终归档校验及桌面移动hash在交付清单。

CPU控制面微基准1000次enqueue+finish对，包含逐渐增长的墓碑：P50 426.244us、P95 993.930us、P99 1502.238us、最大2852.969us；native模拟账最终零。方法/原始JSON随包。仅进程内broker＋FakeLedger，不含IPC/NPU、不代表真实并发吞吐或锁时长上限；没有根据该结果宣称硬2ms预算。


## rc2 最终交付完成（2026-10-22）

覆盖前文“仅上下文同步/开始修复”的进度：R1–R4及统一高压让行实现已完成，代码提交75c5e519195b55ce314fc00bf81b068f382e9cb1；项目96通过、Motor309通过/8跳过，最终独立解包75通过、685文件SHA校验。新rc2包、prompt、指南、修复报告已从WSL移动到Windows桌面并核对hash；归档SHA b23cee6b81d6f4f8b87b1e6cfd6fc28e7e8ed4bab3512c4ab6a4a7cecd1b0121。交付凭据见docs/engineering/GF_ADMISSION_0.1.0rc2_DELIVERY_20261022.md。

下一步是Session2复评完整包、华为短验证/已有结果或必要短探测选择静态H/L/实际通知演练、冻结后跑六格AISBench。无需用户重建环境或增加GB流量采集。暂无NPU或性能证据，未合并main；共享未提交文档继续保留。
