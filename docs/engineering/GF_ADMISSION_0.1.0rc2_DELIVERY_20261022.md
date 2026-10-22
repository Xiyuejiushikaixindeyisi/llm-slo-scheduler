# gf_admission 0.1.0rc2 最终交付记录

2026-10-22；代码提交 `75c5e519195b55ce314fc00bf81b068f382e9cb1`，分支 `backup/20261022-init`；g5起点 `3b63b00546e7a6ffb2526dafc341969cebe22359`。本记录是归档完成后的交付凭据，不改变归档内源码。

## 交付文件

以下四个正式文件已在WSL构建/准备并移动到Windows系统桌面 `C:/Users/ALIENWARE/Desktop`，移动前后SHA256一致，WSL原交付路径已移除；项目源文档、构建与验证证据保留。仅本次rc2为待复评候选，旧dev1/rc1不能复用。

| 文件 | 字节 | SHA256 |
| --- | ---: | --- |
| gf-admission-0.1.0rc2-20261022.tar.gz | 1575686 | `b23cee6b81d6f4f8b87b1e6cfd6fc28e7e8ed4bab3512c4ab6a4a7cecd1b0121` |
| HUAWEI_AGENT_PROMPT_GF_RUNTIME_0.1.0rc2_20261022.md | 8767 | `fe6c3b72a988e859331a85e319930f957ba297183841c344fa13d851f806f06a` |
| GF_ADMISSION_RUNTIME_GUIDE_0.1.0rc2_20261022.md | 14121 | `246134aeaa849b633fd4ee6edab0d6f343ecd9b0b137a55b62dab5e6ad3ec53f` |
| GF_ADMISSION_RC2_REPAIR_REPORT_20261022.md | 5606 | `77f7700a1f593eb8875dff8c56326bdb3cb0c8e16e4b1f9d0bb94a11f013b221` |

压缩包不包含NPU原生库、镜像或权重；包含独立wheel、四文件payload/增量patch、安装/回退脚本、版本/兼容manifest、配置模板、压力探测与后台监督脚本、源码/测试/实验计划和证据。reference-motor仅用于CPU参考测试，不能整目录覆盖现场。

## 本地验证

- 项目96通过；Motor相关309通过、8跳过（7个缺native库，1个已有skip）。Python3.13.11。
- 最终归档新建独立目录解包，685个文件SHA一致；移除外部PYTHONPATH后随包75通过。此75为交付回归子集，不与项目96相加冒充独立覆盖。
- wheel与全部gf_admission源码/contract逐字节一致，隔离pip --target导入/兼容验证通过；wheel SHA `637f1f45a4d4cd200fb691a547998fb3dea010c36d707c942360f74bbfcc258f`。
- 最终解包日志 `artifacts/gf-admission-rc2/extracted-final-tests.log`，SHA `4d591295daffba5917ddabf0341d640f56afadd308270985701ca0cea0a38e94`。首次候选解包暴露测试子进程无用导入，已修复，原失败日志随包保留。
- R1–R4定向回归、真实ZMQ多worker/子进程及高压同成本tail/LIFO覆盖；原生CAS仍为替身。Ruff新范围通过；全Motor pre-commit未宣称全绿。

## 下一步与明确边界

Session2复评本SHA和修复报告 → 华为真实Python/native/P/D短验证 → 复用已有B16×实际66K/128K等待证据，必要5–10分钟短探测 → 冻结每长度H/L与freshness → 后台通知演练 → 正式六格成对实验。现场通知/健康适配器由华为agent接入并验证真实唤醒。

H/L是静态超参数，不在本机猜值；0<L<H，enforce模板null不能直接启用。按请求候选最小FG score定高压，不能把单P最大W或8192当阈值。同长度B16/18/20使用同组阈值。下一版才研究基于TTFT预测的动态指标。

统一成本长OR高压触发、共同credit/S/V、normal FIFO优先、tail低压LIFO、年龄保护已实现，无同成本专用开关。GF减少引擎实际在途与真实LIFO越序分开统计；全体请求P90 TTFT/失败/吞吐均保留。正式目标cache50%×实际66K/128K×集群B16/18/20，优先验证B16改善或SLO下增并发。

Session2对rc2尚未复评，华为真实native/P/D、AISBench均未运行，尚无性能收益声明；没有合入main或推送。其他会话的未提交文档/评审原件保留，不混入实现提交。交付记录JSON：`evidence/manifests/gf_admission_rc2_delivery_20261022.json`。
