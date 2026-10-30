"""Rebuild the offline colleague briefing from fixed local evidence. No network."""
from pathlib import Path
from html import escape
import csv, io, re, json, hashlib, sys, unicodedata
sys.path.insert(0, str(Path(__file__).resolve().parent / 'python-deps'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/reports/LLM_SLO_SCHEDULER_TECHNICAL_BRIEF_20261028.html'
OUT.parent.mkdir(parents=True, exist_ok=True)
SOURCE = ROOT / 'evidence/huawei/2026-10-28-g5-p-token-budget/perf_summary.original.csv'
ROWS = list(csv.DictReader(SOURCE.open(encoding='utf-8-sig')))
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == '73dffb52f08de0d544866a29c29f55a51ff9147354e75adfc39da942ff619be6'
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'axes.spines.top':False,'axes.spines.right':False,'axes.edgecolor':'#b5c2cc','axes.labelcolor':'#203444','text.color':'#203444','xtick.color':'#526776','ytick.color':'#526776','svg.fonttype':'none','figure.facecolor':'none','axes.facecolor':'none'})
BLUE, ORANGE, GREEN = '#2367a2', '#c17728', '#147565'

def svgplot(fig, label):
    f=io.StringIO(); fig.savefig(f,format='svg',bbox_inches='tight',metadata={'Date':None}); plt.close(fig)
    s=f.getvalue(); s=s[s.index('<svg'):]
    s=re.sub(r'width="[^"]+" height="[^"]+"', '', s, count=1)
    # Matplotlib's ids repeat between figures; namespace every local reference.
    key='fig'+hashlib.sha256(label.encode()).hexdigest()[:8]
    ids=re.findall(r'id="([^"]+)"',s)
    for old in sorted(set(ids),key=len,reverse=True):
        s=s.replace(f'id="{old}"',f'id="{key}-{old}"').replace(f'#{old}',f'#{key}-{old}')
    s=s.replace('<svg ',f'<svg class="plot" role="img" aria-label="{escape(label)}" ',1)
    return '<figure>'+s+f'<figcaption>{label}</figcaption></figure>'

def replay_plot():
    fig,axs=plt.subplots(1,2,figsize=(11,3.25))
    for ax,title,vals in zip(axs,['Client TTFT P90','P first-queue P90'],[(16.859,15.444),(8.746,7.811)]):
        ax.barh([1,0],vals,color=[BLUE,GREEN],height=.45)
        ax.set_yticks([1,0],['N: heap','F: FGJSQ']); ax.set_xlim(0,19); ax.set_xlabel('Seconds'); ax.set_title(title,loc='left',fontweight='bold')
        for y,v in zip([1,0],vals):ax.text(v+.25,y,f'{v:.3f} s',va='center')
        ax.set_axisbelow(True); ax.grid(axis='x',alpha=.16)
    fig.tight_layout(w_pad=3)
    return svgplot(fig,'EXP_10.9 / g2：同源 trace 原速开环；数值采用最终等待报告精确口径。')

def chunk_plot():
    fig,axs=plt.subplots(1,2,figsize=(11,3.7))
    for length,col,mark in [('66k',BLUE,'o'),('128k',ORANGE,'s')]:
        rs=[r for r in ROWS if f'T{length}' in r['run']]
        for ax,field in zip(axs,['ttft_p90','qps']):
            base=float(rs[0][field]); values=[float(r[field])/base*100 for r in rs]
            ax.plot(range(4),values,marker=mark,color=col,lw=2,label=length)
            for x,y in enumerate(values):
                if x==3:ax.annotate(f'{y:.1f}',(x,y),xytext=(-7,10 if field=='ttft_p90' or length=='66k' else -17),textcoords='offset points',ha='right',color=col)
    for ax,title in zip(axs,['TTFT P90  /  8K baseline = 100','QPS  /  8K baseline = 100']):
        ax.axhline(100,lw=1,color='#92a4b1',ls='--'); ax.set_xticks(range(4),['8K','16K','32K','64K']);ax.set_xlabel('P max_num_batched_tokens');ax.set_ylabel('Index');ax.set_title(title,loc='left',fontweight='bold');ax.grid(alpha=.15);ax.legend(frameon=False)
    fig.tight_layout(w_pad=2.5)
    return svgplot(fig,'g5 / B=1：各长度分别以 8K 预算归一化；每点单次运行，连线仅帮助阅读。')

def bars(title, entries):
    return '<div class="bars">'+''.join(f'<div class="barrow"><span>{escape(name)}</span><div class="track"><i style="width:{v}%"></i></div><b>{v:.2f}%</b></div>' for name,v in entries)+f'<small>{title}</small></div>'

def table(headers, rows):
    return '<div class="tablewrap"><table><thead><tr>'+''.join('<th>'+str(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+str(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table></div>'

def seq(key, actors, events):
    width=1040; xs=[85+i*(870/(len(actors)-1)) for i in range(len(actors))];height=90+len(events)*48
    s=f'<svg class="sequence" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(key)}"><defs><marker id="arrow-{key}" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto-start-reverse"><path d="M0,0 L8,4 L0,8 Z" fill="#2367a2"/></marker></defs>'
    for x,name in zip(xs,actors):
        s+=f'<rect x="{x-72}" y="8" width="144" height="40" rx="7" fill="#eaf0f5"/><text x="{x}" y="34" text-anchor="middle" font-size="17" font-weight="600">{escape(name)}</text><line x1="{x}" x2="{x}" y1="50" y2="{height-12}" stroke="#c1ccd4" stroke-dasharray="4 5"/>'
    def lines(label,limit=36):
        result=[]; current=''; n=0
        for ch in label:
            size=2 if unicodedata.east_asian_width(ch) in ('W','F') else 1
            if n+size>limit: result.append(current);current='';n=0
            current+=ch;n+=size
        if current:result.append(current)
        return result
    for i,(a,b,label) in enumerate(events):
        y=87+48*i; x1,x2=xs[a],xs[b]
        if a==b:
            s+=f'<rect x="{x1-128}" y="{y-21}" width="256" height="32" rx="5" fill="#f7efe4"/><text x="{x1}" y="{y}" text-anchor="middle" font-size="16">{escape(label)}</text>'
        else:
            wrapped=lines(label, max(36,int(abs(x2-x1)/8)))
            texts=''.join(f'<text x="{(x1+x2)/2}" y="{y-9-(len(wrapped)-1-j)*19}" text-anchor="middle" font-size="16">{escape(line)}</text>' for j,line in enumerate(wrapped))
            s+=f'<line x1="{x1}" x2="{x2}" y1="{y}" y2="{y}" stroke="#2367a2" stroke-width="1.7" marker-end="url(#arrow-{key})"/>'+texts
    return '<figure>'+s+'</svg></figure>'

sections=[]
def add(sid,group,title,lead,body,refs='',deep=False,notes=''):
    sections.append(dict(id=sid,group=group,title=title,lead=lead,body=body,refs=refs,deep=deep,notes=notes))

def cite(*ids):
    return '依据：'+' · '.join(f'<a href="#ref-{x}">[{x}]</a>' for x in ids)

def callout(text):return '<div class="callout">'+text+'</div>'

# CONTENT inserted below; static prose is versioned with the evidence snapshot.
add('opening','开场','在吞吐约束下，把 P90 TTFT 降下来',
    'llm-slo-scheduler · GF 路由、有限让行与 P 侧批预算的联合设计',
    '''<div class="hero"><div class="eyebrow">TECHNICAL DESIGN REVIEW · 2026.10.28</div>
    <p class="hero-line">谁进入哪个 P？<br>谁先进入 P？<br>每一批推进多少 token？</p>
    <div class="three"><div><b>FGJSQ</b><span>批事件驱动的负载均衡<br>已适配 g5</span></div><div><b>super_p90</b><span>GF FIFO + 有限 LIFO<br>rc2 本地评审通过</span></div><div><b>Chunk tuning</b><span>分规格静态基线 → 状态自适应<br>已有 B1 扫描 / 模型设计</span></div></div></div>
    <p>面向 AI infra 工程师的技术汇报。默认 45 分钟：目标 4′、生产证据 7′、FGJSQ 10′、super_p90 10′、chunk 10′、讨论 4′。30 分钟模式保留主线；60 分钟可展开附录和讲者备注。</p>
    <p class="small">材料截止：本地可读记录截至 2026-10-28。super_p90 是本项目 GF 入场策略的名称，借鉴 vllm-omni super-p95；并非已有 P90 最优性证明。</p>''',cite('entry','rc2','chunk'),notes='先给出三层决策的地图；整个汇报围绕证据、机制与下一步验证展开。界面“演示”切换逐页，“阅读”可连续浏览；左右键翻页，Esc 返回阅读。')

add('goals','目标与边界','验收的是全体请求的联合指标',
    '主目标：提高 SLO 下可承载吞吐，并降低全体请求 P90 TTFT；P90 TPOT 是独立约束。',
    table(['逻辑规格','P90 TTFT','P90 TPOT','解释'],[
        ['32K','< 12 s','< 32 ms','按上下文规格分别评价'],['64K','< 27 s','< 30 ms','不能用跨规格平均掩盖违约'],['128K','< 30 s','< 40 ms','当前 g5 B16 TTFT 仍未达到此业务线']])+'''
    <div class="two"><div><h3>同负载比较</h3><p>保持请求集合、到达或并发、输出长度、缓存流程与执行栈一致；比较全体 P90 TTFT、完成 QPS、输出 token/s、P90 TPOT、失败与取消。</p></div><div><h3>容量比较</h3><p>逐级增加负载，寻找同时满足 TTFT / TPOT SLO 的可承载边界；相同到达率下 QPS 接近，不等于最大容量相同。</p></div></div>
    <div class="callout">固定 24 卡配置时，集群吞吐的相对提升可映射为单卡效率提升；当前平均吞吐是否接近硬件容量，不能预先假设。不得删去慢请求或只汇报 normal 子集。</div>''',cite('entry','alignment'))

add('boundary','目标与边界','研究单个 GF + 3P3D 集群',
    '研究假设：GB 已完成规格分流与集群级亲和路由；本项目主要优化 GF 负载均衡、入场顺序与 P 批预算。',
    '''<div class="flow"><div>AI 网关<small>鉴权</small></div><b>→</b><div>多个 GB<small>租户限流 / 规格队列 / 集群路由</small></div><b>→</b><div class="accent">单个 GF<small>协议转换 / P 实例路由</small></div><b>→</b><div class="accent">3P → KV → 3D<small>每引擎 TP4，共 24×910B2</small></div></div>
    <div class="two"><div><h3>并发与负载</h3><p><strong>B=16 是整个集群总在途上限</strong>，包含 prefill、交接和 decode；三个 P 各自获得多少请求由路由决定。B、max_num_seqs、实际 batch 请求数是三个不同量。</p><p>AISBench 为滚动闭环：完成一条补一条，无整轮 barrier。request_rate=1 不能直接当作稳态到达率 λ。</p></div><div><h3>g5 固定执行面</h3><p>P：async predictor scheduler、SLO=0、FCFS / running-first、共享 8192 token、max_num_seqs=24。D：原生 async，主模型 FULL_DECODE_ONLY，MTP3 speculative eager。</p><p>当前研究不改变 D 引擎和 D 路由；GF 无法暂停已经派发的 P 请求。</p></div></div>
    <p class="small">生产画像批次是原生 proxy、max_num_seqs=16；它与 g5 不是同一部署身份。模型记录为 Qwen3.6-27B W8A8。</p>''',cite('entry','frozen','alignment'))

add('measurement','目标与边界','先锁定计时口径，再解释分段',
    '正式指标沿用 AISBench 客户端汇总器；GF/P 内部指标用于解释机制。',
    '''<div class="timeline"><span>HTTP POST 前<br><b>TTFT 起点</b></span><i>GF 等待与路由</i><i>P 首次等待</i><i>P 执行 / chunk 间隔</i><i>KV + D 首次执行</i><span>首记录流式时间点<br><b>TTFT 终点</b></span></div>
    <div class="two"><div><h3>逐请求可分解</h3><p>只有对齐同一请求的时间点，才能分解阶段。queue_time 通常是入队到首次调度；首次调度后的区间仍包含计算、异步等待等，不等于纯设备耗时。</p></div><div><h3>分位数不可直接相加减</h3><p>P90(A+B) ≠ P90(A)+P90(B)。TTFT − uncached / 常量速率的 waitproxy 只是残差估计；不能作为精确排队时间或有保证的等待下界。</p></div></div>
    <p>历史实验使用不同窗口或客户端墙钟补丁时，在对应图表旁单独说明。新实验不以“首个有效 content”重新定义正式 TTFT。</p>''',cite('waiting','historical','frozen'),deep=True)

add('workload','生产数据','同一逻辑规格内，工作量仍高度异质',
    '单 UUID、5,549 条生产记录：输入长度与 prefix 命中都不能被一个“64K 请求”标签概括。',
    '<div class="two"><div><h3>输入长度</h3>'+bars('这些比例存在包含关系，不能相加。',[('输入 < 8K',20.33),('输入 ≥ 32K',72.91),('输入 > 64K',2.23)])+'</div><div><h3>Prefix 命中</h3>'+bars('请求平均命中率 31.65%；token 加权命中率 40.30%。',[('零命中',45.50),('命中 ≥ 90%',12.58),('≥ 32K 且零命中',22.85)])+'</div></div>'+'''
    <div class="callout"><strong>≥32K 且零命中：1,268 条 / 22.85%，贡献约 47.7% 的 uncached token。</strong>这说明成本分类有信息基础；不能直接据此把整组请求划入让行队列，也不能证明同 P 上同时存在长短竞争。</div>
    <p class="small">数据：2026-09-24 约两小时 UTC 的 model_handle_start_time；原生 proxy 生产配置。旧原文 1,235 条只含 32–64K 子集，不能与 1,268 混用。真实输入最大约 103.6K。</p>''',cite('flow','flow-review'))

add('arrivals','生产数据','负载画像给出异质性，尚不提供排队反事实',
    '处理起点分布、后验缓存命中和逐请求等待是不同层面的信息。',
    table(['已观察','工程含义','不能推出'],[
        ['处理起点 0.7712 次/s；uncached 约 17.2K token/s','用于描述这批记录的强度','不是执行吞吐或设备利用率'],
        ['Fano：1s=1.218；10s=1.281；60s=3.122','波动随观测尺度变化','不能证明泊松到达或 ρ≈1'],
        ['前两大 appid 合计 84.59%','成本分布可能集中于少数业务','不能固定让某租户承担牺牲'],
        ['同长度成本代理差异明显','prompt 长度不足以表征工作量','cached_tokens 后验值不自动在线可知'],
        ['延迟有效样本 0；5,548 条 completion < prompt','字段单位/语义冲突已保留','不能从此表算 SLO 达标率或输出量']])+'''
    <p>9 列画像不包含完整 P 候选与逐批轨迹，因此不精确复原路由收益。既有集中流量调研已结束，这些限制作为设计边界保留。</p>''',cite('flow-review'),deep=True)

add('replay','生产数据','生产重放支持 FGJSQ 改善等待尾部',
    'EXP_10.9：同栈 g2 的 N_heap / F_fgjsq 对照；原速开环，约 0.77 req/s。',
    replay_plot()+table(['指标','N_heap','F_fgjsq','读取方式'],[
        ['TTFT P90','16.859 s','15.444 s','−8.39%'],['P 首次 queue P90','8.746 s','7.811 s','−10.69%'],
        ['完成 OPS','0.7678','0.7677','在相同 offered load 下基本一致'],['D 池引擎 TPOT P90','24 ms','24 ms','直方图口径；不是客户端逐请求 P90'],
        ['失败 / 发出','1 / 5,549','0 / 5,549','传输级失败单列，不从分母隐藏']])+'''
    <p class="small">原早期汇总 TTFT P90 为 16.857 / 15.443 s；此处采用后续最终等待报告 16.859 / 15.444 s。完成 OPS / TPOT 来自早期汇总，口径分别标注；没有完整原生 chenyao 栈的开环对照。</p>''',cite('waiting','historical'),notes='8.4% 是这个历史同栈对照的证据。F/N 均为 g2 体系，不能宣布 g5 或新 admission 已获得同样收益。相同 offered load 的完成速率接近，也不回答容量问题。')

add('waiting','生产数据','首次入场等待存在，但并非所有尾部都在入场前',
    '等待证据支持 GF 入场优化，同时限定它能影响的范围。',
    table(['场景','已有观察','对设计的约束'],[
        ['生产重放 g2 / F','P 首次 queue P90=7.811s；126/240 个池化快照有等待','52.5% 是快照比例，不是请求等待比例'],
        ['126K / B16 闭环','首次 queue P50 约 20–30s；三 P 稳态 10s 窗 waiting 均值 6.94','存在显著首次入场等待，适合检验入场顺序'],
        ['66K / B16 闭环','首次 queue P50≈0.5s，P90≈0.8s；TTFT P50≈11.17s','仅改首次入场可能覆盖较少；不能用分位相减定位剩余阶段']])+'''
    <div class="callout">running-first 下，长 prefill 在首次入场后可连续占用多轮 token 预算。GF LIFO 只能控制尚未送入 P 的请求，已经 running 的长请求不会被它暂停。</div>
    <p class="small">EXP_10.14_TRACE 是 EXP_10.9 / 10.12 的二次分析，不能当成第三组独立性能实验。历史 126K B16 waiting 均值 5.87 已由 6.94 替代。</p>''',cite('waiting','omni'))

add('fg-score','FGJSQ','用事件修正剩余工作量，再选择最低压力 P',
    'FGJSQ = Fine-grained token Join Shortest Queue；批级时间预测用于负载衰减，不直接预测请求 TTFT。',
    '''<div class="formula">score<sub>p</sub> = W<sub>p</sub> · (⌈N<sub>p</sub> / M<sub>p</sub>⌉ + 1) / 2</div>
    <div class="formula compact">w<sub>r</sub>(t) = O<sub>r</sub> · remaining<sub>r</sub>/L<sub>r</sub> + O<sub>r</sub> · scheduled<sub>r</sub>/L<sub>r</sub> · [1 − min(Δt / T̂<sub>batch</sub>, 0.95)]</div>
    <div class="two"><div><h3>W 随批事件和时间变化</h3><p>W 是请求 committed load 的和；N 是未释放的 FG 请求数；M 是实例序列上限。未开始部分保留全额，本批 scheduled 部分随预测时间衰减。首个匹配事件把初始 O 校正为真实 prompt 长度 L。</p></div><div><h3>派发是一次事务</h3><p>rank 前重算 W；按 score 从小到大选可用 P；同锁完成候选检查与 native SHM CAS，成功后写 FG 预留。不能先按旧快照选中 P 再无条件占额。</p></div></div>
    <p class="small">实现对负载取整；预测无效时本批不衰减。5% retention 是 scheduled 负载估计的保留量，不是最低服务进展保障；score 不是秒，也不是精确剩余 token。g5 初估沿用请求 body bytes / 4。</p>''',cite('fg-code','adapter','alignment'))

add('fg-example','FGJSQ','一个数值例子：路由看到的是预计剩余工作',
    '示例只解释公式，不是实验曲线或现场预测误差。',
    table(['同一请求快照','值'],[['L = O','64,000 token'],['remaining / scheduled','24,000 / 8,000 token'],['本批预测时间','400 ms'],['事件后经过','200 ms'],['估计负载','24,000 + 8,000 × (1−0.5) = 28,000']])+'''
    <div class="two"><div><h3>比静态 token 账本细</h3><p>静态账本直到释放前可能一直记 64K；事件驱动账本能感知已经推进的工作与在途 batch 的进度。</p></div><div><h3>仍是成本代理</h3><p>同样 28K 新 token 在不同上下文、KV 层级和批形状下耗时可不同；波次系数也没有把 score 变成时延预测。候选过时、主机延迟和首事件前粗估会影响排序。</p></div></div>
    <p>当 N≤M 时波次系数通常为 1；在当前集群 B16、每 P max_num_seqs=24 的常见状态下，主要区别来自 W。不能把多波次项当成该实验收益的必然来源。</p>''',cite('fg-code'),deep=True)

add('fg-sequence','FGJSQ','g5 请求生命周期与批事件反馈',
    '保留 P→D HANDOFF、双账与事件身份；已调度不是已完成。',
    seq('fg',['Client / Worker','GF Mgmt / FG','P Scheduler','D Engine'],[
        (0,1,'P allocate：recompute → rank → CAS + FG reserve'),
        (0,2,'提交 P 请求，进入原生 waiting / running'),
        (2,2,'组批：predict + 冻结事件快照'),
        (2,1,'batch event：epoch / seq / request / attempt'),
        (1,1,'更新进度，影响后续请求排序'),
        (2,0,'P 返回 KV 交接信息；P leg 清 native 账'),
        (0,3,'随后选择 D 并提交请求 / 获取 KV'),
        (3,0,'首非空 HTTP body：触发 FG P 账释放'),
        (3,0,'流结束：完成 D / E2E；异常走幂等清理')])+'''
    <p class="small">图按逻辑依赖展示，省略异步重叠与具体 KV 协议。首非空 body 不等于首个语义 content；该释放钩子也不替代 AISBench 客户端计时。P 的 native / FG 两账为零不单独证明 D 已结束。</p>''',cite('adapter','alignment','body'))

add('predictor','FGJSQ','预测器的训练标签必须按源码解释',
    '现有 LightGBM 支撑 g5 事件反馈；新的 chunk 成本模型应单独版本化。',
    '''<div class="flow"><div>调度快照<small>legacy 8 特征</small></div><b>→</b><div>Scaler + LightGBM<small>predicted_exec_ms</small></div><b>→</b><div>批事件<small>FG 负载衰减</small></div></div>
    <div class="flow"><div>patch_core 计时<small>主机观察标签</small></div><b>→</b><div>后台分桶滑窗<small>有效样本过滤</small></div><b>→</b><div>周期重训 / 快照替换<small>不在本轮改写 v1</small></div></div>
    <div class="two"><div><h3>标签不是纯设备时间</h3><p>异步队列空时，标签是提交到主机观察完成的区间；非空时可能是相邻主机观察结果的间隔。它既不是请求剩余 TTFT，也不等于孤立 kernel 耗时。</p></div><div><h3>特征名字不等于物理含义</h3><p>legacy cache_hit_rate 来自 prompt / computed 关系；computed 可在提交后提前推进。不能把它读成真实 APC 命中率，也不能从旧八维直接恢复新模型的 Σu² 与 Σuh。</p></div></div>
    <p class="small">300 棵树、depth=5、learning rate=0.05；达到最小样本后周期训练。predict 有计数/日志副作用。现场 warm model 未外传，当前材料不构成预测数值复现或留出集精度证明。</p>''',cite('alignment','cost-audit'),deep=True)

add('fg-benchmark','FGJSQ','压测中 TTFT 有改善，TPOT 与吞吐尚未全面对齐',
    '历史 g4 与 9.10 同事基线：高并发 B16 摘要；属于跨轮栈比较，不能归因成 FG 单变量收益。',
    table(['B16 / 指标','66K 同事 9.10','66K g4','128K 同事 9.10','128K g4'],[
        ['TTFT P90（s）','13.555','13.152','47.860','47.208'],
        ['TPOT mean（ms）','11.60','12.63','11.20','12.20'],
        ['TPOT P90（ms）','12.40','13.29','—','—'],
        ['QPS','0.6693','0.6499','0.2991','0.2823']])+'''
    <div class="two"><div><h3>相同栈的配对证据</h3><p>EXP_10.13 的 66K H/F 紧邻配对，两臂 TPOT 差较小，用于定位 TPOT 回归；g5 后续 Phase 2 开/关四轮各项差异 &lt;1%，该组条件下未显示明显路由收益。不能推广为 FG 普遍无效。</p></div><div><h3>跨栈对照的局限</h3><p>9.10 / 10.12 使用 AISBench 原生全窗；10.13 / 10.14 有墙钟补丁和主集截窗。输入实长也不完全一致。表中差异用于回归定位，不构成严格同条件因果实验。</p></div></div>
    <p class="small">历史 g4 已将 D 侧恢复为原生引擎与 heap 路由。10.13 四 run 均值，10.14 两 run 均值；缺少的 P90 不用 mean 替代。</p>''',cite('historical','frozen','alignment'))

add('g5-results','FGJSQ','g5 恢复了工程基线，128K 业务 TTFT 仍未达标',
    '冻结报告 E2：128K、集群 B16、PT900、prefix 目标 50%、输出 1024。',
    table(['指标','g5 E2 r01','g5 E2 r02','结论'],[
        ['成功 / 总请求','284 / 284','283 / 283','两轮零失败'],
        ['TTFT mean / P90（s）','38.18 / 43.84','38.49 / 43.76','P90 仍高于 30s 业务线'],
        ['TPOT mean / P90（ms）','13.2 / 14.2','13.1 / 14.2','业务 40ms 内；相对 g4 仍有残差'],
        ['QPS','0.2980','0.2973','与 g4 历史约 0.2812 / 0.2834 比较有提高']])+'''
    <div class="callout">±10% 工程恢复阈值通过，不能等同业务 SLO 达标或“完全无回归”。g5 相对 g4 的 TPOT 约 +7.5% 尚未做单变量分解。</div>
    <p>两轮复用同一服务生命周期，predictor 与缓存状态可延续，不能称为独立重启随机重复。冻结报告截止时十档验收未完成，B1 的两项 TPOT 工程阈值未过；本地未见后续完整验收结果。</p>
    <p class="small">g5 较早的大幅退化同时涉及 HCCL 环境和引擎栈版本，修复收益不能记为 FGJSQ 算法增益。</p>''',cite('frozen','alignment'))

add('fg-fit','FGJSQ','FGJSQ 的价值取决于跨 P 工作差异是否可被利用',
    '适用性是可验证的场景假设；不要求入口一定泊松。',
    table(['场景','预期与理由','需要观察'],[
        ['长短输入 / 命中混合，P 之间进度差明显','事件衰减可减少静态账本滞后','跨 P score 差、实际路由变化、等待尾部'],
        ['稀疏请求，多个 P 同时空闲','路由选择空间有，但性能差可能很小','额外调度/上报开销与低负载延迟'],
        ['同质长输入、闭环同步、各 P 近似一致','负载差异小，路由策略未必有明显增益','不据此宣称容量耗尽'],
        ['大量未入场请求 / 批事件陈旧','长期全额预留可能使账本偏保守','事件新鲜度、初估误差、清账时序'],
        ['KV 分层与加载代价显著','仅 token 账本不足以完整描述成本','区分 NPU 驻留与 CPU/Disk 命中']])+'''
    <p>生产重放的 −8.4% TTFT P90 是支持证据；同质压测的弱收益也是证据。后续应保留两类负载，而不是只选择更容易展示收益的一类。</p>''',cite('historical','alignment'),deep=True)

add('tpot','FGJSQ','下一步：分别关闭两层 TPOT 回归',
    '本轮同时跟踪：g4→同事基线、g5→g4 两层回归，分别设计对照。',
    table(['回归层','已有证据','尚未解决'],[
        ['g4 相对 9.10','66K 各 B mean TPOT 约 +0.73～1.18ms；128K 约 +0.93～1.22ms','口径、跨日环境与执行栈残差未完全闭合'],
        ['g5 相对 g4','E2 mean TPOT 约 +7.5%；工程容忍通过','没有单变量归因，不能以旧 rc1→final diff 解释'],
        ['已做的历史修复','g2 D 侧 predictor / 日志 / wrapper 被移除，66K mean TPOT 降约 0.41～0.50ms','这是已回收部分，不能把残差宣布归零']])+'''
    <ol><li><strong>双锚点配对：</strong>对齐各自比较栈的采样、MTP、graph/eager、KV、通信、客户端汇总和时间窗；一组针对 g4/同事基线，一组针对 g5/g4。</li>
    <li><strong>按证据分层定位：</strong>D step 的采样 / 主机调度 / 日志路径，P→D 交接与编排，以及测量口径；一次只改变一个因素，保持 D 算法基线。</li>
    <li><strong>低并发定位 + 目标负载复核：</strong>B1/B2 看固定开销，B16 检查排队与闭环反馈；确认延迟、吞吐和失败联合回归，而非只修 mean TPOT。</li></ol>
    <div class="callout">上述是下一轮建议，不是已执行实验。sampler / I/O / 编排仅为候选原因；g5 和 g4 已同为正式版底座，旧 435 文件差异不能直接解释当前 +7.5%。</div>''',cite('historical','alignment','frozen'),notes='先定位原有路径的性能差异，并保持策略归因分离。闭环中 TPOT 变慢会拉长 E2E，降低补发强度，因此吞吐退化可能随之出现。')

add('omni','super_p90','借鉴 super-p95 的“有限让行”，拆开各项机制',
    'vllm-omni 固定源码 dd9c0895：普通 FIFO、让行 LIFO，并能在 diffusion step 边界暂停让行请求。',
    table(['原型机制','作用','LLM GF 方案'],[
        ['成本分类 + 每 20 次到达补 1 credit','有限选择较长请求承担等待','保留可解释分类，并加入统一高压触发'],
        ['normal FIFO 优先，tail LIFO','让较新 tail 先完成，将额外等待集中于少数较老请求','在尚未 P 预留的 GF pending 中实现'],
        ['step 边界暂停 active tail','普通请求到来时收回下一步执行机会','GF 不具备；已派发 P 请求不可暂停'],
        ['路由折扣 N + 0.1S','让 tail 对原型路由负载贡献较低','不照搬；g5 FG 账本与公式保持'],
        ['可选小图 batch2','另一项吞吐优化','不并入 LLM 双队列收益归因']])+'''
    <div class="two"><div><h3>历史 Qwen 图像实验</h3><p>P95 407.83→321.00s（−21.3%）；QPS 0.4525→0.4139（−8.5%）。来自历史重写笔记，不能宣称纯 LIFO 已独立证明吞吐不降。</p></div><div><h3>历史 Wan 实验</h3><p>P95 2750.93→2191.56s；QPS 0.0135→0.0157，同时从 1×USP8 改为 2×USP4，存在拓扑混杂。</p></div></div>
    <p class="small">原型衡量图片/视频完成延迟 P95，不能直接转换成 LLM P90 TTFT。让行 credit 的 5% 频率也不能机械改为 10% 来“匹配 P90”。</p>''',cite('omni','omni-code'))

add('admission-idea','super_p90','把一部分等待留在 GF，保留对派发顺序的控制',
    '目标是在吞吐不下降的条件下改善多数请求的 TTFT；收益尚需现场验证。',
    '''<div class="queue-diagram"><div class="queue"><b>normal pending / FIFO</b><div><span>N1</span><span>N2</span><span>N3</span><em>先到先出 →</em></div><small>优先派发；沿用 g5 FGJSQ</small></div><div class="queue tail"><b>sacrificial pending / LIFO</b><div><span>T-old</span><span>T-new</span><em>← 新请求先出</em></div><small>normal 空 + 实际候选 P 压力低才放行</small></div><div class="queue-result"><b>FG rank → CAS → P</b><p>排在 GF 时不占 P 的 native / FG 预留</p><p>放行后 P 保持 FCFS / running-first</p></div></div>
    <div class="two"><div><h3>为什么放在预留前</h3><p>若全部请求已进入 P waiting，GF LIFO 无法改变真实入场顺序。未预留 tail 不进入 FG 工作账本；放行时重新选择真实候选，逐条 reserve 后重算压力。</p></div><div><h3>低负载行为</h3><p>普通请求通常直接派发；低压时 tail 可及时放行。希望低负载下机制近似休眠，但长成本分类仍可能触发，必须测量实际驻留与额外开销。</p></div></div>
    <p class="small">normal 为空不代表 P 中普通工作已排空。GF 不能取消已经提交的设备计算，也不改 running/KV 抢占。</p>''',cite('revision','design'))

add('admission-rules','super_p90','rc2：长成本或统一高压力触发，共用有限预算',
    '同成本 AISBench 也可在高压时让行，不引入 benchmark 专用分类开关。',
    '''<pre><code>tail_eligible = known_positive_cost AND fresh_pressure
  AND (long_cost OR min(score[p] for p in eligible_P) &gt;= H)
  AND credit_available AND S_available AND V_available
  AND NOT protected AND NOT draining

normal FIFO 优先
当 normal 为空：尝试 tail LIFO
  实际候选 P 必须满足 score[p] &lt;= L；0 &lt; L &lt; H
  每次 CAS、每次 fallback 候选均重新检查
  reserve 成功后更新账本，再判断下一条</code></pre>
    <div class="two"><div><h3>分类与压力不是同一量</h3><p>长成本条件沿用原型：cost ≥0.8×历史 max，且 ≥1.5×历史 min。压力用请求可用候选 P 的最低 FG score，不是全池最大压力。</p></div><div><h3>成本与 KV 层级</h3><p>成本代理包括 uncached + β<sub>CPU</sub>·CPU 命中 + β<sub>Disk</sub>·Disk 命中，按可用候选取值。Conductor 的连续前缀层级覆盖互斥；unknown 不当作零命中。</p></div></div>
    <p class="small">score=0 不是物理空闲证明。H/L、β 与各预算是待标定超参数；此处不填伪造生产最优值。</p>''',cite('revision','rc2','admission-code'))

add('admission-budgets','super_p90','四种预算分别约束不同风险',
    '队列深度可以动态变化，但其上限与保护规则仍需明确。',
    table(['约束','rc2 候选起点','含义'],[
        ['分类 credit','每 20 到达补 1；cap=2','累计分类额度；不是滑窗比例或队列长度'],
        ['存量数量 S','tail ≤2','限制当前延后请求数'],
        ['存量成本 V','2,097,152 成本代理单位','限制当前延后工作量，非实测时延'],
        ['年龄保护','5s','晋升为 protected normal；不保证 5s 内完成'],
        ['压力与状态保护','stale / drain 晋升','事件陈旧不继续制造 tail；关闭时可排空']])+'''
    <p>分类按 logical 请求计一次，业务重试不重复赚取/消耗 credit。取消或晋升释放 S/V 存量，不退分类 credit。遇到压力拒绝时停止 tail 放行；资源不可用时仅做有界候选扫描。</p>
    <div class="callout">应把“降低实际入场并发”与“真实 LIFO 越序”分开归因。tail 入过队不等于 LIFO 已发挥作用；age / stale / drain 晋升可能使它最终走普通路径。</div>''',cite('rc2','runtime'),deep=True)

add('admission-sequence','super_p90','异步排队必须同时解决预留、claim 与取消',
    'Mgmt 维护队列，worker 保留 HTTP；短 enqueue + 有界 long-poll 避免挂住原 Motor 5s dispatch RPC。',
    seq('admission',['HTTP Worker','Admission Broker','FG / Native CAS','P → D'],[
        (0,1,'enqueue：logical key / round'),
        (1,1,'QUEUED：尚无 P 资源'),
        (0,1,'long-poll / query（WaitHub）'),
        (1,2,'normal 优先；tail 候选检查 score ≤ L'),
        (2,1,'CAS + FG reserve 成功'),
        (1,1,'READY_RESERVED：短交付租约'),
        (0,1,'claim：确认同一预留，进入 CLAIMED'),
        (0,3,'随后按 g5 提交 P，再 HANDOFF 到 D'),
        (0,1,'finish / cancel：按原 owner 幂等清理')])+'''
    <p>normal fast path 可在一次 RPC 内直接 reserve / CLAIMED。结果未知时查同 key，不盲目 fallback 重复预留；worker 租约过期不自动释放执行中的 CLAIMED。</p>''',cite('design','rc2'))

add('admission-status','super_p90','本地交付已通过，下一步是现场机制与收益验证',
    'rc2 实现 75c5e519；交付记录 8171c2d；尚未合入 main，未见现场 NPU 性能结果。',
    '''<div class="three"><div><b>正确性</b><span>R1–R4 已关闭<br>独立解包 75 项 + 评审 2 项通过</span></div><div><b>集成边界</b><span>真实 ZMQ / 子进程<br>native SHM 与计算仍用替身</span></div><div><b>性能结论</b><span>尚未获得<br>本地测试不等于 NPU / SLO 通过</span></div></div>
    <ol><li><strong>off / shadow：</strong>真实镜像与 P/D 兼容、取消、清账、关闭回退。</li><li><strong>H/L 标定：</strong>优先复用已有结果，必要时短探测每 P 的 FG score / committed_tokens / 未释放数 / 有效事件时间；选静态阈值并冻结。</li><li><strong>enforce 短验证与通知演练：</strong>真实 SHM、故障与恢复；保留版本、错误与重启记录。</li><li><strong>正式六格：</strong>实际约 66K / 128K × 集群 B16 / B18 / B20；cache 目标 50%；off/enforce 配对，B16 重复。</li></ol>
    <p class="small">长度标签、真实 token、配置、cache 实测与失败均留档；same-length 的 H/L 冻结后跨 B 使用。正常监控不调用模型，故障通知需验证实际可达。以上是已批准的执行计划，不是已完成实验。</p>''',cite('rc2','experiment','delivery'))

add('chunk-control','Chunk size','先区分四种“token 上限”',
    '当前寻优对象是 P 每批共享预算 C；它不等于单请求 chunk，也不等于 API 输出上限。',
    table(['量','作用域','当前研究中的角色'],[
        ['C = max_num_batched_tokens','每次 P 组批共享','现有 8K；扫描 8/16/32/64K'],
        ['U = long_prefill_token_threshold','单请求本轮分配上限（启用时）','可作为第二步静态对照；当前 g5 未启用'],
        ['max_num_seqs','实例并行序列名额','g5 为 24；不随集群 B 自动变化'],
        ['输入 / 输出长度限制','请求 API 与模型上下文','不把 C=8192 解释成输出最多 8192']])+'''
    <div class="callout">P 按 running-first、waiting FCFS 依序消费 C。没有单请求 U 时，一个长 partial prefill 可以吃完本轮预算；“有 chunk 边界”不自动意味着短请求获得机会。</div>
    <p>当前优先级：按规格 / 负载建立静态 C 基线 → 评估静态 C+U → 必要时少量状态分档 → 最后评估在线预测寻优的净收益。</p>''',cite('chunk','model','ascend-code'))

add('chunk-data','Chunk size','已有扫描：128K 温和改善，66K 的 64K 预算明显变差',
    '仅调整 P 侧 max_num_batched_tokens；集群 B=1、输出 1024、cache 目标 50%。',
    chunk_plot()+'''
    <div class="two"><div><h3>128K</h3><p>32K 相对 8K：TTFT P90 <strong>−4.72%</strong>，QPS <strong>+2.03%</strong>。64K：TTFT P90 −4.32%，QPS +2.53%。32K 的 P90 更低，64K 的 mean / QPS 略好。</p></div><div><h3>66K</h3><p>16K / 32K 与 8K 的差异较小；64K：TTFT P90 <strong>+52.44%</strong>，QPS <strong>−16.08%</strong>。不能把更大的预算作为所有规格的默认值。</p></div></div>
    <p class="small">8 个单次 run，共 285 个有效样本，每格 30–43 条。仅有单次扫描，无误差棒或显著性结论。比例变化不依赖延迟单位；原 CSV 延迟单位暂按推定 ms、span 推定 s。</p>''',cite('chunk','chunk-csv'))

chunkrows=[]
for length in ['66k','128k']:
    rs=[r for r in ROWS if f'T{length}' in r['run']]
    for budget,r in zip(['8K','16K','32K','64K'],rs):
        chunkrows.append([length,budget,r['n'],r['ttft_mean'],r['ttft_p90'],r['tpot_p90'],r['qps']])
add('chunk-table','Chunk size','八格原始读数与解释边界',
    'TTFT / TPOT 列保持 CSV 原数值，单位推定为 ms；QPS 为 req/s。',
    table(['输入标签','P 预算','n','TTFT mean','TTFT P90','TPOT P90','QPS'],chunkrows)+'''
    <p>实际输入均值约 67,892 / 129,241 token。所有行 status=valid，但本摘要没有单独失败计数；不据此补写“零失败”。实际 cache hit、预热/重启和种子细节也未在这份 CSV 中闭合。</p>
    <p>B1 只能评价低负载串行服务表现：P 之后还有约 12s decode，故 TTFT 的百分比改善被 E2E 稀释。不能据此推断三个 P 的容量、高并发尾部或 kernel 效率。</p>
    <p class="small">数值核验：qps × [ttft_mean + 1023×tpot_mean]/1000 ≈ 1，支持 ms 解释但不替代导出 schema。in_tps 包含命中输入 token，不能当作新增计算吞吐。</p>''',cite('chunk','chunk-csv'),deep=True)

add('chunk-research','Chunk size','业界的共同做法：按负载选择预算，先建立强静态基线',
    '可迁移的是控制量、成本结构和实验方法；硬件数值与混部策略不能直接照搬。',
    table(['来源','可借鉴机制','对本项目的适用边界'],[
        ['NVIDIA TensorRT-LLM','联合扫描 max batch size / max num tokens，比较时延、吞吐和内存','NVIDIA 的默认值与最优点不是 910B2 的结论'],
        ['Hugging Face TGI','分开请求长度、batch prefill 与 batch total token 约束','不能把这些不同预算统一理解为 chunk size'],
        ['Sarathi-Serve / vLLM','chunked prefill 权衡执行效率、迭代耗时与 decode 干扰','主要讨论混部；当前 P-only 没有同批 D token'],
        ['QoServe','用批成本预测与 deadline / slack 约束选择 chunk','借鉴显式时间预算；不能直接把 D TPOT SLO 当 P 批时限'],
        ['Ascend Dynamic Batch / CPP','profile 表或历史上下文预测服务成本','P-only、async、PP 条件须核对；不能直接打开替换 g5 scheduler']])+'''
    <p class="small">文献支持研究方向，不证明本实现有效；本项目未复现这些系统的硬件收益。此处摘要以官方文档、论文和固定源码为依据。</p>''',cite('nvidia','tgi','sarathi','qoserve','survey','vllm-doc'))

add('model','Chunk size','把“新增 token”与“读取的历史”分开建模',
    '在同一冻结状态上模拟原生组批，比较完整候选 batch，而非只按 prompt 总长预测。',
    '''<div class="formula compact">Q = Σu<sub>i</sub> ≤ C　　S₂ = Σu<sub>i</sub>²　　H = Σu<sub>i</sub>h<sub>i</sub>　　A = H + (S₂ + Q)/2</div>
    <div class="two"><div><h3>结构约束模型 S</h3><div class="formula compact">T̂<sub>S</sub> = α₀ + α<sub>B</sub>n + α<sub>U</sub>Q + α<sub>A</sub>A</div><p>固定批开销 + 每请求开销 + 新 token 线性成本 + 因果注意力配对成本代理。</p></div><div><h3>自由拟合模型 F</h3><div class="formula compact">T̂<sub>F</sub> = β₀ + β₁n + β₂Q + β₃S₂ + β₄H</div><p>解除 S₂ 与 H 的系数耦合，用同样本、同标签、同候选集做独立对照；多参数不天然更优。</p></div></div>
    <p>u<sub>i</sub> 是本批实际计划新算 token，h<sub>i</sub> 是执行前可用历史，n 是实际 batch 请求数。前缀命中减少新增计算量，但命中的上下文仍被注意力读取。对目标混合注意力模型，A 是经验成本代理，不是全部层精确 FLOPs。</p>
    <p class="small">结构模型是自由模型的子空间：β₃=α<sub>A</sub>/2，β₄=α<sub>A</sub>，β₂=α<sub>U</sub>+α<sub>A</sub>/2。参数尚无现场标定；不把公式当作性能结果。</p>''',cite('model','cost-audit'))

add('model-decision','Chunk size','单批效率优化有解析直觉，也有全局盲点',
    '候选目标至少应区分“最高 Q/T”与“满足时间预算下推进最多 Q”。',
    '''<div class="two"><div><h3>吞吐代理</h3><div class="formula compact">C* ∈ argmax Q(C) / T̂(C)</div><p>满预算 Q=C、固定成员与相对分配形状时，若 T(C)=a+bC+dC²，a,d&gt;0，则内点效率最优 C*=√(a/d)。上下文影响线性项时，不直接改变该理想式的最优点，却影响时限可行域。</p></div><div><h3>时限约束</h3><div class="formula compact">max Q(C)　s.t. T̂(C) ≤ τ</div><p>τ 必须定义为 P 的批服务预算；不是直接取 30ms TPOT 或 30s TTFT。有限候选枚举还要满足 KV、序列、运行时硬预算与异步依赖。</p></div></div>
    <div class="callout">逐批 Q/T 最优不等于整请求完成时间最优，更不保证总体 P90。把长 prefill 切开不会消除因果注意力总配对量；还可能增加固定批开销与历史 KV 重读。</div>
    <p>正常因果计算下，完整长度 L、初始历史 h₀ 的总配对量为 h₀L+L(L+1)/2，与切块方式无关。真正影响性能的是硬件效率、重复成本、请求间执行机会与资源限制的组合。</p>''',cite('model','survey'),deep=True)

add('chunk-sequence','Chunk size','拟议的在线路径：纯候选计划 → 成本评分 → 一次真实提交',
    '这是设计方案，尚未实现为动态 controller；现有静态扫描不依赖此流程。',
    seq('chunk',['P Scheduler','纯候选模拟','成本模型','执行 / 反馈'],[
        (0,1,'冻结状态：running / waiting / KV / inflight'),
        (1,1,'枚举 C，保持原生顺序与约束'),
        (1,2,'候选聚合：n、Q、Σu²、Σuh'),
        (2,0,'预测成本 + 可行性；选择预算'),
        (0,0,'异常 / 不可表达状态：回原生预算'),
        (0,3,'只对选中预算进行一次真实 schedule / submit'),
        (3,2,'带 batch 身份与 label_kind 的离线验证样本')])+'''
    <p>候选模拟不能调用会推进 computed、占 KV 或修改队列的真实 schedule。已提交 batch 的依赖必须保留；在线控制也不能热扩张超过实际初始化的运行时上限。</p>''',cite('model'),deep=True)

add('chunk-next','Chunk size','下一步先回答：动态策略能否胜过按规格固定 C？',
    '先用便宜、稳定、可解释的配置建立基线，再判断预测和控制复杂度是否值得。',
    '''<ol><li><strong>复核静态候选：</strong>66K 重点 8K / 16K / 32K；128K 重点 8K / 32K / 64K。核对实际配置与缓存流程，重复配对，不把单次小差异当最优。</li>
    <li><strong>进入目标负载：</strong>从 B1 扩展到目标 B，保持输入 / 输出和测量窗口可比；观察全体 TTFT、TPOT、完成 QPS 与失败。</li>
    <li><strong>独立评估 C+U：</strong>静态总预算配合单请求上限，测量吞吐和执行机会的取舍；不同时混入 GF 分类变更。</li>
    <li><strong>必要时再自适应：</strong>先少量状态档位和明确切换条件；只有在负载变化下稳定超过强静态基线，才开发完整成本模型控制器。</li></ol>
    <div class="callout">模型线的验证项：同标签留出误差、候选排序、模型调用/模拟开销，以及最终业务指标。旧 g5 LightGBM 和新 S/F 模型各自版本化；离线拟合优度不替代现场收益。</div>''',cite('chunk','model'),notes='分规格和随时间变化是两个尺度。先看静态规格是否已经覆盖大部分收益，再评估同一集群随时间切换的必要性。此页是计划与建议，未启动新压测。')

add('joint','联合验证','先分开归因，再寻找吞吐—P90 的 Pareto 方案',
    'GF 决定入场，P 决定每批推进量；二者会改变彼此看到的负载分布。',
    table(['比较阶段','固定什么','要回答的问题'],[
        ['FG / TPOT 基线','P/D 配置与测量窗口','两层 TPOT 回归是否已关闭？'],
        ['GF admission off ↔ enforce','固定 P 预算、冻结 H/L / S / V','尾部变化来自并发门控还是 LIFO 顺序？'],
        ['P 预算 / C+U 对照','固定 GF 策略与流量','吞吐净收益是否伴随 TTFT / TPOT 回归？'],
        ['组合对照（后续建议）','同一可复现部署与请求集','两者是否互补，还是门控抵消批效率？']])+'''
    <p>联合验收至少呈现：全体 P50/P90/P95/P99 TTFT、P90 TPOT、QPS / 输出 token/s、错误与取消、分组尾部，以及 tail 分类/派发/晋升/越序次数。固定硬件下画可行配置的 Pareto 前沿，不预设唯一权重。</p>
    <div class="callout">短期最有价值的三件事：关闭双层 TPOT 残差；让 rc2 在真实 P/D 上完成配对验证；用目标负载复核静态 C。动态 chunk 与 GF 联合控制是后续增量。</div>''',cite('entry','experiment','chunk'))

add('discussion','联合验证','讨论：下一轮先验证哪些假设？',
    '把分歧变成可复现的对照，避免继续叠加无法归因的复杂度。',
    '''<div class="three"><div><b>路由与 TPOT</b><span>两层回归分别缺哪一个<br>同条件对照？</span></div><div><b>入场策略</b><span>收益来自减少实际入场并发，<br>还是 tail 的真实越序？</span></div><div><b>批预算</b><span>静态 C+U 是否足够？<br>什么证据才值得上动态模型？</span></div></div>
    <p class="closing">当前已有“异质负载 + 首次等待”的证据，也有 g5 与 rc2 的工程落地。下一阶段应把这些机制变成可复现的 SLO 收益，并保留吞吐、公平性和 TPOT 的完整代价。</p>
    <p>建议团队共同确认：对照栈身份、失败/取消口径、重复规则、可接受的吞吐差异，以及由谁完成现场验证和结果回传。</p>''',cite('entry'))

add('appendix-math','附录','原始效用与 KV 宏观模型：保留推导，也保留假设',
    '研究方向尚未联合求解或现场验证；不能用它替代当前 P-only 的成本模型。',
    '''<div class="formula compact">F(C) = [C + P<sub>b</sub> + W<sub>q</sub> + λT<sub>k</sub>ℓ] / [NT<sub>k</sub> + λT₂² / 2]</div>
    <p>T<sub>k</sub>=T<sub>mix</sub>(d₁,…,d<sub>k</sub>; C,p₁,…)，T₂=T<sub>mix</sub>(d₁,…,d₂; C,p₁,…)；两组 decode 参数是用户有意保留的差异，不合并成同一个 T。</p>
    <p>分子包括等待工作量与未来到达工作，本轮没有全部完成，所以 F 是研究效用，不能直接命名为已完成 token/s。λT₂²/2 需要相应等待核；若所有到达都等到 T<sub>k</sub>，不能无解释地使用 T₂。</p>
    <p>KV 宏观演化还需明确写入、命中、活跃引用与淘汰闭合；共享前缀、异步在途和闭环反馈使常 λ / TTL 近似有适用条件。普通 LightGBM 常值叶不可直接求连续导数。</p>
    <div class="callout">d<sub>k</sub> 与 d₂、批成本预测、KV 演化、总体 P90 是四个需要分别定义的对象。当前交付是数学审查和设计，不是已验证最优控制器。</div>''',cite('kv-model','model'),deep=True)

add('appendix-compat','附录','Ascend 动态机制与 g5 的兼容性不是一个开关',
    '固定源码 5cb98caa 的能力边界，优先于泛化宣传描述。',
    table(['机制','固定源码语义','为何不能即插即用'],[
        ['Dynamic Batch','按 decode 负载查预算表，无 decode 时回基准预算；调度路径还有顺序处理','当前为 P-only，且要保留 g5 async predictor 链'],
        ['Dynamic CPP','基于历史长度 profile 反求 chunk / 时间预算；要求 PP>1','当前 TP4 不代表 PP4；替换 scheduler 会涉及新兼容性工作'],
        ['差分曲线 g(h+u)−g(h)','g(l)=al²+bl+d 时，差分消去 d','不自然保留每个 batch 再付出的固定开销'],
        ['设备同步 profile 标签','固定校准执行区间','与 g5 主机提交/取结果间隔不同，不能混合拟合']])+'''
    <p>可迁移：上下文特征、低维成本回归、明确时间标签与预算。暂不迁移：PP 专用流水线控制、decode 优先重排、动态抢占与未经验证的 profile 数值。</p>''',cite('survey','model','ascend-code'),deep=True)

REFS = {
'entry':('项目总工程师入口','docs/architecture/CHIEF_ENGINEER_SESSION_ENTRY.md','统一边界、协作与证据地图；B=16 为集群总并发。'),
'flow':('生产画像原件','docs/traffic/CLUSTER_FLOW_PROFILE_REPORT_20260924.original.md','5,549 条，单 UUID，2026-09-24。'),
'flow-review':('生产画像核对','docs/traffic/CLUSTER_FLOW_PROFILE_ANALYSIS_20260924.md','修正 ≥32K 零命中 1,268 条；保留延迟单位与 completion 语义限制。'),
'waiting':('最终等待证据核对','docs/traffic/FINAL_WAITING_AND_ADMISSION_REVIEW_20261021.md','g2 开/闭环等待、精确 TTFT 与首次 queue 数值。'),
'historical':('10.9–10.14 原始全景报告','evidence/huawei/2026-10-19-import/SUMMARY_REPORT.txt','历史 replay / AISBench 原表；历史推断以新核对稿纠正。'),
'frozen':('g5 冻结交接原件','docs/engineering/G5_FROZEN_BASELINE_HANDOVER.md','§8 实验与计时；截止 2026-10-21 13:09 UTC。原件有勘误。'),
'alignment':('g5 源码核查与勘误','docs/engineering/G5_LOCAL_BASELINE_ALIGNMENT_REVIEW.md','computed / 标签 / predict / 双账 / 正式版底座以核查为准。'),
'fg-code':('FGJSQ 公式实现','src/fgjsq/policy.py','actual、score、rank、reserve、event、release。'),
'adapter':('Motor 适配服务','src/motor_adapter/service.py','FG 与 native 预留、事件身份及原子候选检查。'),
'body':('D 流体观察与 FG 释放','src/motor_adapter/body_observer.py','首非空 body 释放钩子；不是客户端 content TTFT 定义。'),
'cost-audit':('旧成本特征源码审查','docs/modeling/COST_FUNCTION_SOURCE_AUDIT.md','旧八维特征实际含义，以及复用限制。'),
'omni':('super-p95 源码研究与 LLM 对比','docs/references/SUPER_P95_RESEARCH_AND_LLM_COMPARISON.md','原型机制与历史结果；后续 GF 设计已更新旧待讨论项。'),
'omni-code':('vllm-omni 固定 step scheduler','https://github.com/Lijunzhang0829/vllm-omni/blob/dd9c0895d98a73c760e9ca930d87e03198713ff7/vllm_omni/diffusion/sched/super_p95_step_scheduler.py','FIFO/LIFO、active 与 step 暂停；固定 commit。'),
'revision':('统一高压让行修订','docs/admission/GF_PRESSURE_ADMISSION_REVISION_20261022.md','rc2 已批准 OR 分类、H/L 与共同预算。'),
'design':('GF 双队列工程设计','docs/admission/G5_GF_DUAL_QUEUE_IMPLEMENTATION_DESIGN.md','Mgmt / worker、状态机、窄 hook 与回退。'),
'admission-code':('rc2 broker 实现','src/gf_admission/broker.py','统一分类、FIFO/LIFO、预留/claim/取消和保护。'),
'rc2':('rc2 复评与现场放行','docs/engineering/GF_ADMISSION_0.1.0rc2_REVIEW_20261022.md','本地通过、R1–R4 关闭、现场流程与验证边界。'),
'runtime':('gf_admission 运行指南','docs/engineering/GF_ADMISSION_RUNTIME_GUIDE.md','off/shadow/enforce 与安装、诊断、关闭回退。'),
'experiment':('rc2 六格实验计划','experiments/plans/GF_ADMISSION_RC2_AISBENCH_20261022.json','66K/128K × B16/18/20 配对矩阵，冻结条件。'),
'delivery':('rc2 交付凭据','docs/engineering/GF_ADMISSION_0.1.0rc2_DELIVERY_20261022.md','实现与归档 SHA；旧待复评状态已被复评通过覆盖。'),
'chunk':('MaaS token 预算实践与 g5 B1 扫描','docs/modeling/MAAS_TOKEN_LIMIT_PRACTICES_AND_G5_EXPERIMENT.md','2026-10-28 最新优先级：静态 C / C+U 后再自适应。'),
'chunk-csv':('P 侧 token 预算原始 CSV','evidence/huawei/2026-10-28-g5-p-token-budget/perf_summary.original.csv','SHA256 73dffb52f08de0d544866a29c29f55a51ff9147354e75adfc39da942ff619be6；用户本轮保留单位推定。'),
'model':('动态批 token 预算设计 v0.1','docs/modeling/DYNAMIC_BATCH_TOKEN_BUDGET_DESIGN_V0_1.md','S/F 模型、标签、候选模拟、可行域和验证；未实现动态控制器。'),
'kv-model':('Chunk / KV 数学建模','docs/modeling/CHUNK_SIZE_KV_CACHE_MATHEMATICAL_MODEL.md','保留 d_k 与 d_2 区别；KV 宏观演化为研究方向。'),
'survey':('Chunk 行业研究','docs/modeling/CHUNK_SIZE_INDUSTRY_RESEARCH_SURVEY.md','固定源码与论文的适用性比较。'),
'ascend-code':('Ascend 固定 RecomputeScheduler','https://github.com/vllm-project/vllm-ascend/blob/5cb98caaadeff42b5b62b996e34bb2aaa29d20fd/vllm_ascend/core/recompute_scheduler.py','running-first、共享预算与单请求 threshold。'),
'nvidia':('NVIDIA max batch / max token 调优','https://nvidia.github.io/TensorRT-LLM/1.3.0rc23.post1/legacy/performance/performance-tuning-guide/tuning-max-batch-size-and-max-num-tokens.html','官方文档：按 workload 扫描并考虑内存；本轮在线核验。'),
'tgi':('Hugging Face TGI launcher','https://huggingface.co/docs/text-generation-inference/en/reference/launcher','官方预算参数定义；本轮在线核验。'),
'sarathi':('Sarathi-Serve · OSDI 2024','https://www.usenix.org/conference/osdi24/presentation/agrawal','原论文：chunked prefill 与吞吐/时延权衡；本轮核验。'),
'qoserve':('QoServe · ASPLOS 2026','https://www.microsoft.com/en-us/research/wp-content/uploads/2025/10/QoServe_CC_final_v2.pdf','Microsoft Research 原论文；批成本、QoS 与动态 chunk。'),
'vllm-doc':('vLLM v0.23.0 optimization','https://docs.vllm.ai/en/v0.23.0/configuration/optimization/','混部调优解释；不替代 P-only 固定源码。')
}
source_html='<p>正文、图表、样本读数与机制说明均已内嵌，可单文件离线分享。下列“项目文件”链接需要保留项目目录；外部链接用于原论文和固定源码核验。</p>'
source_html+=table(['版本简称','本文身份'],[['g2','早期 proxy FGJSQ 与 P/D 插件栈，承载 EXP_10.9–10.13 历史结果'],['g4','P 保留 predictor / FG；D 恢复原生引擎 + heap 路由'],['g5','基于正式版 g4 底座接入 Motor；冻结版本见交接与核查稿'],['rc2','g5 上增量 gf_admission 0.1.0rc2；本地评审通过，性能待现场验证']])
source_html+='<div class="sources">'
for key,(title,path,desc) in REFS.items():
    external=path.startswith('https:')
    if not external:assert (ROOT/path).exists(),path
    href=path if external else '../../'+path
    source_html+=f'<article id="ref-{key}"><b>[{key}] {escape(title)}</b><p>{escape(desc)}</p><a href="{escape(href)}" target="_blank" rel="noopener">{"外部来源" if external else "项目文件"} ↗</a><code>{escape(path)}</code></article>'
source_html+='</div>'
add('sources','来源','可追溯来源与版本说明','原始结果、源码核查、批准设计与研究模型分开引用。',source_html,deep=True)

CSS=r'''
:root{--ink:#173244;--muted:#5b6f7f;--blue:#2367a2;--green:#147565;--gold:#b6762e;--line:#dbe4eb;--paper:#fff;--bg:#eef2f5;--nav:#122b3c}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:86px}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"Segoe UI","Microsoft YaHei","PingFang SC",sans-serif;font-size:16px;line-height:1.65}
a{color:var(--blue);text-underline-offset:3px}button,select{font:inherit}button{cursor:pointer}
button:focus-visible,a:focus-visible,select:focus-visible{outline:3px solid #dfac5a;outline-offset:3px}
#sidebar{position:fixed;inset:0 auto 0 0;width:238px;background:var(--nav);color:#e0eaf0;z-index:12;display:flex;flex-direction:column;padding:25px 18px}
.brand{font-size:17px;line-height:1.4;letter-spacing:.3px;color:#fff;font-weight:700}.brand small{display:block;font-size:11px;color:#91b2c7;letter-spacing:2px;margin-top:9px}
#toc{overflow:auto;flex:1;margin:28px -5px 15px;padding-right:5px}.nav-group{font-size:11px;color:#91b2c7;letter-spacing:1.5px;margin:20px 9px 6px}
#toc a{display:flex;gap:9px;font-size:12px;line-height:1.5;color:#c4d5df;text-decoration:none;padding:7px 9px;border-radius:5px;margin:2px 0}#toc a:hover,#toc a.current{background:#24485f;color:#fff}#toc .num{color:#8babc0;min-width:20px}
.sidefoot{font-size:11px;color:#a8bfcd;border-top:1px solid #365061;padding-top:14px}
header.topbar{position:sticky;top:0;z-index:10;margin-left:238px;min-height:64px;background:#fffffff5;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 32px;backdrop-filter:blur(12px)}
.toolbar{display:flex;gap:7px;align-items:center;flex-wrap:wrap}.toolbar button,.toolbar select{border:1px solid var(--line);border-radius:5px;background:white;padding:6px 10px;font-size:12px;color:var(--ink)}.toolbar button.active{background:var(--ink);color:white;border-color:var(--ink)}
#progressLabel{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}
main{margin-left:238px;padding:28px 32px 80px;max-width:1600px}
.slide{background:var(--paper);padding:36px 42px 26px;margin:0 0 28px;border:1px solid var(--line);border-radius:9px;box-shadow:0 4px 18px #18374c05;scroll-margin-top:86px}
.kicker{display:flex;justify-content:space-between;color:var(--blue);font-size:11px;letter-spacing:1.5px;font-weight:700;margin-bottom:9px}
h1,h2,h3,p{margin-top:0}h2{font-size:29px;line-height:1.4;letter-spacing:-.5px;margin-bottom:12px;font-weight:700}h3{font-size:17px;line-height:1.4;margin-bottom:12px}p{margin-bottom:15px}p.lead{font-size:17px;color:var(--muted);margin-bottom:25px}
.small,small{font-size:12px;line-height:1.7;color:var(--muted)}.two,.three{display:grid;gap:25px;margin:22px 0}.two{grid-template-columns:1fr 1fr}.three{grid-template-columns:repeat(3,1fr)}
.three>div{border-top:3px solid var(--blue);padding:18px 0}.three b{font-size:21px;display:block;margin-bottom:10px}.three span{font-size:14px;color:var(--muted);display:block}
.callout{background:#edf5f7;border-left:3px solid var(--green);padding:16px 20px;margin:22px 0;font-size:15px}
.hero{background:var(--nav);color:#f5f9fc;padding:28px 32px;border-radius:6px;margin:20px 0 24px}.eyebrow{font-size:11px;letter-spacing:2px;color:#98becf}.hero-line{font-size:35px;line-height:1.5;font-weight:600;margin:20px 0}.hero .three{margin-bottom:0;gap:24px}.hero .three>div{border-color:#5f9ac1;padding:12px 0 0}.hero .three span{color:#bed1df}.hero .three b{font-size:19px}
.tablewrap{overflow-x:auto;margin:20px 0}table{width:100%;border-collapse:collapse;font-size:13.5px;line-height:1.6}th{text-align:left;color:var(--blue);background:#f2f6f9;font-weight:600;padding:11px 12px;border-bottom:2px solid #c8d8e3}td{padding:12px;border-bottom:1px solid var(--line);vertical-align:top}tr:last-child td{border-bottom:0}td:first-child{font-weight:600}table td{font-variant-numeric:tabular-nums}
figure{margin:24px 0 16px}figure svg{display:block;max-width:100%;height:auto;width:100%}figcaption{font-size:12px;color:var(--muted);line-height:1.5;margin-top:12px}.sequence{font-family:"Segoe UI","Microsoft YaHei",sans-serif}.sequence text{fill:var(--ink)}
.formula{background:#f5f7fa;border:1px solid var(--line);font-family:"Cambria Math","Cambria","Microsoft YaHei",serif;font-size:25px;text-align:center;padding:21px 15px;margin:21px 0;overflow-x:auto}.formula.compact{font-size:20px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#142e3f;color:#edf6fc;padding:22px 25px;border-radius:6px;line-height:1.75;font-size:13px}code{font-family:"Cascadia Code",Consolas,monospace}
.flow{display:flex;align-items:center;gap:14px;margin:25px 0;flex-wrap:wrap}.flow>div{flex:1;min-width:130px;padding:17px;background:#f0f4f7;font-weight:600}.flow small{display:block;font-weight:400;margin-top:8px}.flow .accent{background:#e5f2f1}
.timeline{display:flex;gap:8px;align-items:stretch;margin:25px 0;font-size:12px}.timeline>*{flex:1;padding:14px 9px;background:#eef4f7;text-align:center;font-style:normal}.timeline span{background:#e2eff0}
.barrow{display:grid;grid-template-columns:150px 1fr 64px;gap:12px;align-items:center;margin:18px 0;font-size:14px}.track{height:13px;background:#e9eff3;border-radius:2px}.track i{display:block;height:100%;background:var(--blue);border-radius:2px}.barrow b{text-align:right;font-size:14px;font-variant-numeric:tabular-nums}
.queue-diagram{display:grid;grid-template-columns:1.2fr 1fr;gap:16px;margin:24px 0}.queue{padding:18px;background:#eaf2f8;border-left:3px solid var(--blue)}.queue.tail{grid-column:1;background:#f6efe6;border-color:var(--gold)}.queue-result{grid-column:2;grid-row:1/3;align-content:center;padding:25px;background:#edf5f2}.queue>div{display:flex;gap:9px;margin:15px 0;align-items:center;flex-wrap:wrap}.queue span{background:white;padding:7px 11px;font-family:monospace}.queue em{font-size:12px;font-style:normal}.queue-result p{font-size:14px;margin-top:14px}
ol{padding-left:25px}li{padding:5px 0;margin-bottom:8px}.sources{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin:25px 0}.sources article{background:#f4f7f9;padding:18px;font-size:13px;scroll-margin-top:95px}.sources p{margin:9px 0}.sources code{display:block;font-size:10px;overflow-wrap:anywhere;color:var(--muted);margin-top:8px}.sources a{font-size:12px}
.foot{display:flex;justify-content:space-between;gap:18px;font-size:11px;color:var(--muted);padding-top:17px;border-top:1px solid var(--line);margin-top:25px}.foot a{text-decoration:none}
details.notes{border-top:1px dashed var(--line);padding-top:12px;margin-top:15px;font-size:13px;color:var(--muted)}summary{cursor:pointer}details.notes p{margin-top:12px}
.closing{font-size:22px;line-height:1.75;border-left:4px solid var(--blue);padding-left:25px;margin:25px 0}
.progress{position:fixed;top:0;left:238px;right:0;height:3px;z-index:30;background:#dbe5eb}.progress div{background:var(--green);height:100%;width:0;transition:width .15s}
body.present main{max-width:none}body.present .slide{display:none;min-height:calc(100vh - 120px);margin-bottom:0}body.present .slide.current-slide{display:block}.short-hidden{display:none!important}
#mobileMenu{display:none}
@media(min-width:1700px){body{font-size:18px}h2{font-size:34px}table{font-size:15px}}
@media(max-width:1150px){#sidebar{width:204px}main{margin-left:204px;padding:22px 20px}header.topbar{margin-left:204px;padding:10px 20px}.progress{left:204px}.slide{padding:28px}h2{font-size:25px}.barrow{grid-template-columns:130px 1fr 57px;font-size:12px}.two,.three{gap:18px}}
@media(max-width:850px){#sidebar{transform:translateX(-100%);width:245px;transition:.15s}body.nav-open #sidebar{transform:translateX(0)}main{margin-left:0;padding:16px}header.topbar{margin-left:0;padding:10px 16px}.progress{left:0}#mobileMenu{display:inline-block}.slide{padding:24px}.two{grid-template-columns:1fr}.three{gap:14px}.timeline{flex-wrap:wrap}.timeline>*{min-width:90px}.sources{grid-template-columns:1fr}.barrow{grid-template-columns:150px 1fr 65px}#progressLabel{display:none}}
@media(max-width:540px){body{font-size:15px}.slide{padding:21px 18px}h2{font-size:23px}.lead{font-size:15px!important}.hero{padding:22px}.hero-line{font-size:27px}.three{grid-template-columns:1fr}.three>div{padding:11px 0}.three b{font-size:19px}.queue-diagram{grid-template-columns:1fr}.queue-result{grid-column:1;grid-row:auto}.formula.compact{font-size:17px}.sequence{min-width:700px}figure:has(.sequence){overflow-x:auto}.foot{display:block}.foot span{display:block;margin-top:8px}.toolbar{gap:5px}.toolbar button,.toolbar select{padding:6px 7px}.barrow{grid-template-columns:130px 1fr 60px;gap:7px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*{transition:none!important}}
@media print{@page{size:A4 landscape;margin:12mm}body{background:white;font-size:11px}#sidebar,header.topbar,.progress,details.notes{display:none!important}main{margin:0;padding:0;max-width:none!important}.slide,body.present .slide{display:block!important;border:0;box-shadow:none;border-radius:0;break-before:page;min-height:0!important;padding:0;margin:0}.slide.short-hidden{display:block!important}.slide:first-child{break-before:auto}h2{font-size:22px}.lead{font-size:13px!important}.two,.three{gap:18px;margin:15px 0}table{font-size:10px}td,th{padding:7px}.callout{font-size:11px;padding:10px;margin:14px 0}.formula{font-size:18px;padding:12px;margin:12px 0}.formula.compact{font-size:15px}.hero{padding:15px 25px;print-color-adjust:exact}.hero-line{font-size:27px}figure{margin:12px 0}figure svg{max-height:100mm;width:100%}.sources{grid-template-columns:1fr 1fr}.sources article{break-inside:avoid;font-size:10px}.foot{margin-top:14px;padding-top:10px;font-size:9px}.sequence{min-width:0}pre{font-size:10px;padding:14px;print-color-adjust:exact}}
'''
JS=r'''
const sections = [...document.querySelectorAll('.slide')];
const links = [...document.querySelectorAll('#toc a')];
let index = 0, presenting = false, duration = '45';
const shortIds = new Set(['opening','goals','boundary','workload','replay','waiting','fg-score','fg-sequence','fg-benchmark','g5-results','tpot','omni','admission-idea','admission-rules','admission-sequence','admission-status','chunk-control','chunk-data','chunk-research','model','chunk-next','joint','discussion']);
function activeSections(){
  return sections.filter(s => !s.classList.contains('short-hidden') && (duration==='60' || !s.classList.contains('deep')));
}
function refresh(){
  sections.forEach((s,i)=>s.classList.toggle('current-slide',i===index));
  links.forEach(a=>a.classList.toggle('current',a.hash==='#'+sections[index].id));
  const active=activeSections(), n=active.indexOf(sections[index]);
  document.getElementById('progressLabel').textContent = (n>=0 ? (n+1)+' / '+active.length : '附录') + ' · '+duration+' min';
  document.getElementById('progress').style.width=((index+1)/sections.length*100)+'%';
  document.getElementById('prev').disabled=!active.some(s=>sections.indexOf(s)<index);
  document.getElementById('next').disabled=!active.some(s=>sections.indexOf(s)>index);
}
function go(i, hash=true){
  index=Math.max(0,Math.min(sections.length-1,i));
  sections[index].classList.remove('short-hidden');
  refresh();
  if(hash)history.replaceState(null,'','#'+sections[index].id);
  sections[index].scrollIntoView({behavior:'instant',block:'start'});
  document.body.classList.remove('nav-open');
}
function advance(dir){
  const active=activeSections(), current=sections[index];let pos=active.indexOf(current);
  if(pos<0){const choices=sections.map((s,i)=>({s,i})).filter(x=>active.includes(x.s)&&(dir>0?x.i>index:x.i<index));const target=dir>0?choices[0]:choices.at(-1);if(target)go(target.i);return;}
  const target=active[pos+dir];if(target)go(sections.indexOf(target));
}
document.getElementById('mode').addEventListener('click',()=>{
  presenting=!presenting;document.body.classList.toggle('present',presenting);
  const button=document.getElementById('mode');button.textContent=presenting?'返回阅读':'进入演示';button.classList.toggle('active',presenting);button.setAttribute('aria-pressed',String(presenting));go(index,false);
});
document.getElementById('duration').addEventListener('change',e=>{
  duration=e.target.value;
  sections.forEach(s=>s.classList.toggle('short-hidden',duration==='30'&&!shortIds.has(s.id)));
  links.forEach(a=>a.classList.toggle('short-hidden',duration==='30'&&!shortIds.has(a.hash.slice(1))&&a.hash!=='#sources'));
  if(sections[index].classList.contains('short-hidden'))index=0;
  document.getElementById('routeNote').textContent=duration==='30'?'主线 23 页 · 重点结论':duration==='45'?'主线 + 按需详解 · 45 分钟':'全部页面 + 附录 · 60 分钟';
  refresh();if(presenting)go(index,false);
});
document.getElementById('prev').addEventListener('click',()=>advance(-1));
document.getElementById('next').addEventListener('click',()=>advance(1));
document.getElementById('print').addEventListener('click',()=>window.print());
document.getElementById('mobileMenu').addEventListener('click',()=>document.body.classList.toggle('nav-open'));
document.addEventListener('click',e=>{
  const a=e.target.closest('a[href^="#"]');if(!a)return;
  const el=document.getElementById(a.hash.slice(1));if(!el)return;
  const section=el.closest('.slide');if(!section)return;e.preventDefault();go(sections.indexOf(section));
  if(el!==section)setTimeout(()=>el.scrollIntoView({block:'start'}),50);
});
document.addEventListener('keydown',e=>{
  if(['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName))return;
  if(e.key==='Escape'&&presenting){document.getElementById('mode').click();return;}
  if(!presenting)return;
  if(['ArrowRight','PageDown'].includes(e.key)){e.preventDefault();advance(1)}
  if(['ArrowLeft','PageUp'].includes(e.key)){e.preventDefault();advance(-1)}
});
const observer=new IntersectionObserver(entries=>{
  if(presenting)return;
  const visible=entries.filter(e=>e.isIntersecting).sort((a,b)=>b.intersectionRatio-a.intersectionRatio);
  if(visible.length){index=sections.indexOf(visible[0].target);refresh()}
},{rootMargin:'-70px 0px -45% 0px',threshold:[0,.2,.5]});
sections.forEach(s=>observer.observe(s));
const initial=sections.findIndex(s=>'#'+s.id===location.hash);
if(initial>=0)go(initial,false);else refresh();
'''
toc=''; prev=''; html_sections=''
for i,s in enumerate(sections):
    if s['group']!=prev:toc+=f'<div class="nav-group">{s["group"]}</div>';prev=s['group']
    toc+=f'<a href="#{s["id"]}"><span class="num">{i+1:02d}</span><span>{escape(s["title"])}</span></a>'
    notes=s['notes'] or ('详解页，可在 60 分钟报告或问答时展开。' if s['deep'] else '先讲本页结论，再用表格或图示解释机制；证据边界与来源在本页保留。')
    html_sections+=f'''<section class="slide {'deep' if s['deep'] else ''}" id="{s['id']}" aria-labelledby="title-{s['id']}">
    <div class="kicker"><span>{s['group']}</span><span>{i+1:02d} / {len(sections):02d}{' · 详解 / 附录' if s['deep'] else ''}</span></div>
    <h2 id="title-{s['id']}">{s['title']}</h2><p class="lead">{s['lead']}</p>
    {s['body']}<details class="notes"><summary>讲者备注</summary><p>{notes}</p></details>
    <div class="foot"><span>{s['refs']}</span><span>llm-slo-scheduler · 2026-10-28</span></div></section>'''
html=f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="面向 AI infra 工程师的技术汇报：生产证据、FGJSQ、GF super_p90 和 P 批 token 预算。">
<title>llm-slo-scheduler · 吞吐与 P90 TTFT 技术设计汇报</title><style>{CSS}</style></head>
<body><aside id="sidebar"><div class="brand">llm-slo-scheduler<small>ENGINEERING BRIEFING</small></div><nav id="toc" aria-label="汇报目录">{toc}</nav><div class="sidefoot"><span id="routeNote">主线 + 按需详解 · 45 分钟</span><br>本地证据快照 · 2026.10.28<br>全体 P90 TTFT / 吞吐 / P90 TPOT</div></aside>
<div class="progress" aria-hidden="true"><div id="progress"></div></div>
<header class="topbar"><div class="toolbar"><button id="mobileMenu" type="button" aria-label="打开目录">目录</button><button id="mode" type="button" aria-pressed="false">进入演示</button><select id="duration" aria-label="汇报时长"><option value="30">30 min · 主线</option><option value="45" selected>45 min · 标准</option><option value="60">60 min · 深入</option></select><button id="prev" type="button" aria-label="上一页">←</button><button id="next" type="button" aria-label="下一页">→</button><button id="print" type="button">打印 / PDF</button></div><div id="progressLabel" aria-live="polite"></div></header>
<main>{html_sections}<noscript><p>JavaScript 已关闭：正文、数据与图表仍可阅读；演示模式需要启用 JavaScript。</p></noscript></main><script>{JS}</script></body></html>'''
OUT.write_text(html,encoding='utf-8')
print(json.dumps({'file':str(OUT),'sections':len(sections),'bytes':OUT.stat().st_size,'references':len(REFS)},ensure_ascii=False))
