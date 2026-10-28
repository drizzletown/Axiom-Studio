from pathlib import Path
from docx import Document
from docx.shared import Cm,Pt,RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT,WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT.parent/'Axiom_P2_第六批实施与验收报告_V0.6_20261025.docx'
doc=Document()
sec=doc.sections[0]
sec.page_height=Cm(29.7);sec.page_width=Cm(21)
sec.top_margin=Cm(2.2);sec.bottom_margin=Cm(2.0)
sec.left_margin=Cm(2.5);sec.right_margin=Cm(2.5)
sec.header_distance=Cm(1.0);sec.footer_distance=Cm(1)
styles=doc.styles
norm=styles['Normal'];norm.font.name='Noto Serif CJK SC';norm.font.size=Pt(10.2)
norm.paragraph_format.space_after=Pt(5)
norm.paragraph_format.line_spacing=1.22
for kind,size,space in [('Title',19,12),('Heading 1',14,9),('Heading 2',11.5,6)]:
    s=styles[kind];s.font.name='Noto Sans CJK SC';s.font.size=Pt(size)
    s.font.bold=True;s.font.color.rgb=RGBColor(21,30,40)
    s.paragraph_format.space_before=Pt(space);s.paragraph_format.space_after=Pt(5)

h=sec.header.paragraphs[0]
h.text='AXIOM  /  软件构造与可信演化研究原型'
h.alignment=WD_ALIGN_PARAGRAPH.RIGHT
for run in h.runs:run.font.name='Noto Sans CJK SC';run.font.size=Pt(8);run.font.color.rgb=RGBColor(110,120,130)
footer=sec.footer.paragraphs[0];footer.alignment=WD_ALIGN_PARAGRAPH.CENTER
footer.add_run('Axiom P2f · 工程版本 0.8.0   |   ')
field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');footer._p.append(field)
for run in footer.runs:run.font.size=Pt(8)

def p(t='',style=None):return doc.add_paragraph(t,style)
def hd(t,level=1):doc.add_heading(t,level)
def table(headers,rows,widths=None):
    t=doc.add_table(rows=1,cols=len(headers));t.style='Table Grid';t.alignment=WD_TABLE_ALIGNMENT.CENTER
    for i,x in enumerate(headers):t.rows[0].cells[i].text=x
    for row in rows:
        cells=t.add_row().cells
        for j,x in enumerate(row):cells[j].text=str(x);cells[j].vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
    for i,row in enumerate(t.rows):
        for cell in row.cells:
            for para in cell.paragraphs:
                para.paragraph_format.space_after=Pt(1)
                for run in para.runs:run.font.size=Pt(8.5)
        if i==0:
            for cell in row.cells:
                for run in cell.paragraphs[0].runs:run.font.bold=True
    return t

doc.add_heading('Axiom P2 第六批实施与验收报告',0)
p('原生 C++ 并发执行历史与有限线性化检查  ·  版本 V0.6  ·  2026年10月25日')
p('设计基线：Axiom 0.2（冻结）；概要设计 V1.0。工程版本：0.8.0。')

hd('一、阶段结论')
p('在 P0—P2e 连续工程基础上，完成了 C++20 真正双线程执行历史采集、基于 Axiom 抽象动作语义的有限线性化检查，以及实现级证据的版本绑定与保守失效。正确实现得到限定范围内的 Tested 结果，两个故意注入缺陷的候选被阻断。现有功能仍属于研究原型，不能解释为 C++ 并发程序的形式化精化证明或生产发布许可。')
table(['指标','验收结果'],[
 ('工程版本','0.8.0'),('新增自动化测试','12 项；已通过'),('全量自动化回归','146/146 通过'),('连续版本演示','正确候选→仅改源码→重测→缺陷候选，均按预期'),('实验执行规模','repeats=2 时每构建模式 24 段试验、80 次 API 调用'),('本地完整性审计','Consistent；非独立认证')])

hd('二、本批新增能力')
table(['能力','交付内容'],[
 ('真实并发采集','使用两个 C++20 std::thread 同时启动；收集每次调用的开始、完成事件与返回值'),
 ('线性化检查','搜索保留非重叠调用实时顺序的合法串行执行；后继状态直接由现有 Axiom IR Action 求出'),
 ('终态观察','全部线程结束后读取测试适配器提供的最终状态快照，验证与抽象末状态一致'),
 ('故障注入','单边更新缺陷；仅在 set 调用发生重叠时暴露的双状态不一致缺陷'),
 ('证据与准入','绑定规格摘要、源文件、工具实现、ABI、构建模式、试验范围、运行结果'),
 ('安全与诊断','沿用实验性 Linux namespace/chroot 隔离，normal 与 UBSan 两种构建，失败保守阻断')])

hd('三、线性化检查设计')
p('每个已完成调用记录 (线程、操作、参数、invocation 序号、response 序号、结果)。当调用 i 的 response 早于调用 j 的 invocation 时，线性化顺序必须满足 i ≺ j。检查器从 Axiom Action 的抽象后继生成可允许的状态与输出，通过有限回溯寻找满足所有观察结果的合法串行顺序，并检查完成后快照。')
p('此处检查的是“已实际运行并完成的并发历史能否线性化”。它既不等于穷举所有可能的线程调度，也不直接证明无数据竞争。搜索预算不足、沙箱不可用和运行超时必须给出 Unknown，不允许进入测试级准入。')

hd('四、实际测试与反例')
table(['候选','检验结果','原型 Gate'],[
 ('加互斥锁的正确实现','Tested','Approved（仅测试级）'),
 ('BrokenOneSide','Violated；状态不满足抽象转移','Blocked'),
 ('BrokenOverlap','Violated；重叠 set 调用后状态不符合线性化要求','Blocked')])
p('在连续版本实验中，已有抽象模型证据保持适用时，仅修改候选 C++ 源码注释仍导致原实现级证据不可再直接使用；重新运行完整测试后，新版本才获得限定的 Tested/Approved。改变实现为存在缺陷的候选后，Gate 再次阻断。')
p('正确候选和注释修改后的候选均通过 normal、UBSan 两种模式；故障候选产生可记录的并发历史反例。本次独立脚本显示本地审计 Consistent，审计不能对抗同权限攻击者重新伪造自洽记录。')

hd('五、源码与工件')
table(['位置','作用'],[
 ('src/axiom/cpp_history.py','线程执行试验、严格历史解析、有限线性化搜索'),
 ('src/axiom/history_store.py','证据存储、源/规格/工具版本绑定和准入'),
 ('src/axiom/audit.py','历史证据本地交叉引用与一致性审计扩展'),
 ('cpp/history/*.cpp','正确与两类错误的真实 C++20 候选'),
 ('tests/test_cpp_history_p2f.py','新增 12 项自动化测试'),
 ('scripts/run_p2f_demo.py','端到端可复现验收和连续版本实验')])

hd('六、保证边界与未解决事项')
for item in [
 'P2f 对真实执行样本作出 Tested 判断；没有系统性控制全部 C++ 指令交错，也没有形式化证明所有执行均可线性化。',
 '本版没有产生可靠的 ThreadSanitizer 结果；UBSan 不能替代数据竞争检测与 C++ 内存模型证明。',
 '最终状态读取依赖测试专用 axiom_snapshot 适配器，其行为需要审计；该接口不能作为一般程序自动观察机制。',
 '隔离环境尚缺少生产级 seccomp/cgroup 审计与系统化攻击面加固；不能安全执行任意不可信代码。',
 '当前证据存储由本地工作区控制，可检测许多误用和破坏，但无法对抗有权同时改写代码及存储的攻击者。',
 '所有 Approved 均为 cpp-native-threads-observed-linearizability-tested-prototype，release_authorized=false。',
]:
    doc.add_paragraph(item,style='List Bullet')

hd('七、阶段判断与后续目标')
p('P0 已建立受限语义内核，P1 已建立受限 C++ 测试链，P2 现已扩展至真实 C++20 线程执行历史及版本化实现证据。P2 仍未整体完成。')
p('下一批应优先实施受控调度扰动与 TSAN 独立检测（若部署环境允许），逐步扩展未完成调用、跨线程共享状态及故障恢复的可观察行为；同步开展生产级沙箱安全设计和独立验签/证据复核。随后才能进行真实项目的增量验证成本对照实验。')
# Frozen Axiom 0.2 invariants already stated in the title and scope.

OUT.parent.mkdir(parents=True,exist_ok=True)
doc.save(OUT)
print(OUT)
