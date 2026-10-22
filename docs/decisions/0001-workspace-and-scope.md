# 统一工作区与会话分工

日期：2026-10-19。状态：本轮采用，后续可按讨论修订。

统一目录为 /home/zhangxiyue/llm-slo-scheduler。主会话与数学会话共享文件系统工程，避免复制出两套不一致的源码和文档。主会话负责工程复现、入场分类与让行预算；数学会话目前只写数学研究文档。

upstream 保存固定提交的开源仓库；src 保存可交付代码；evidence 保存原始投递；docs 保存研究结论；experiments 保存计划、结果和分析；artifacts 保存移交产物。原始 slo_patch 与交付 slo_patch 分开放置，保留差异可追溯性。

当前不实现 waiting 重排、保留 KV 的边界让行或释放 KV 的抢占；不修改 D 基线；不假设吞吐已经接近容量。先复现 FGJSQ＋predictor，再讨论新算法。
