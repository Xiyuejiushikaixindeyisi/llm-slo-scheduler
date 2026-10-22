# 现场材料与源码投递

原始报告、版本信息、日志和事件轨迹放 huawei/<一次交付的日期和名称>/。原 proxy 源码放 source_drops/proxy/<批次>/；原 slo_patch 放 source_drops/slo_patch/<批次>/。保留投递目录结构和内容，不在原始文件中直接修正代码。

每次接收在 manifests 中记录来源、时间、适用版本和 SHA256。分析结论及源码差异写入 docs/engineering；审核后需要维护的代码进入 src。

2026-10-19 已将此前的 SUMMARY_REPORT 和 DOC1 原样复制入 huawei/2026-10-19-import；SHA256 见 manifests/workspace_import.json。当前尚未收到原 proxy/slo_patch 源文件。

2026-10-19 新取证报告已原样归档到 huawei/2026-10-19-g4-forensics/FGJSQ_P_ONLY_REPRO_FORENSICS.txt，摘要见 manifests/g4_forensics_2026-10-19.json。代码投递目录与包结构见 [g4 投递清单](../docs/engineering/G4_SOURCE_INTAKE.md)。
