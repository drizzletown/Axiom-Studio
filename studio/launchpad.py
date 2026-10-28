"""Axiom Studio V0.7: practical project onboarding, action inbox, portable handoff.

Only orchestrates existing Axiom services. No implicit execution of native code,
no creation of fake evidence, no production approval.
"""
from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
import zipfile

from orchestrator import FlowError, FlowConflict

TEMPLATES = {
    'model-toggle': {
        'label': '开关状态 · 规格验证入门',
        'description': '有限状态行为验证，无需 C++ 编译器',
        'model': 'toggle.ax',
        'manifest': None,
        'goal': '验证开关状态转换满足给定不变量，保留可追溯的模型验证证据。',
        'files': ['toggle.ax'],
    },
    'model-ledger': {
        'label': '守恒账户 · 规格与反例',
        'description': '两账户转移和余额守恒的不变量检查',
        'model': 'two_account.ax',
        'manifest': None,
        'goal': '保持两个账户的余额总量守恒并检验可达状态边界。',
        'files': ['two_account.ax'],
    },
    'cpp-ledger': {
        'label': 'C++ 多文件项目 · 实际交付流程',
        'description': '规格、两类实现、三个独立测试目标和 Gate（执行 C++ 需要另行确认）',
        'model': 'ledger.ax',
        'manifest': 'project.json',
        'goal': '构建符合 Axiom 守恒行为规格的 C++20 多文件项目，独立验证实现与格式及集成测试。',
        'files': ['ledger.ax','project.json','ledger.hpp','ledger.cpp','format.hpp','format.cpp',
                  'test_ledger.cpp','test_format.cpp','test_integration.cpp'],
    },
}

class LaunchError(FlowError):
    pass


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(data) -> bytes:
    return json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')


class Launchpad:
    def __init__(self, studio, template_root:Path|None=None):
        self.studio=studio
        self.workspace=studio.flow.workspace
        self.source=template_root or Path(__file__).resolve().parent/'templates'
        self.lock=threading.RLock()

    def templates(self):
        return {'templates':[{'id':key,'label':desc['label'],
                'description':desc['description'],'native':bool(desc['manifest']),
                'default_goal':desc['goal']} for key,desc in TEMPLATES.items()],
                'warning':'示例源码为教学用途；本地 C++ 执行需要独立授权，不允许自动生产发布。'}

    def create(self, template_id, slug, name, goal):
        template=TEMPLATES.get(template_id)
        if template is None:raise LaunchError('不存在该项目模板')
        if not isinstance(slug,str) or not re.fullmatch(r'[a-z][a-z0-9_-]{2,31}',slug):
            raise LaunchError('项目目录标识须为 3–32 位小写字母、数字、下划线或连字符，且以字母开头')
        if not isinstance(name,str) or not 2<=len(name.strip())<=100:
            raise LaunchError('项目名称长度必须在 2–100 字符之间')
        if not isinstance(goal,str) or not 4<=len(goal.strip())<=2000:
            raise LaunchError('请填写明确的软件目标（4–2000 字符）')
        with self.lock:
            parent=self.workspace/'projects'
            parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            if parent.is_symlink() or not parent.resolve().is_relative_to(self.workspace.resolve()):
                raise LaunchError('工作区项目目录不安全')
            dest=parent/slug
            if dest.exists() or dest.is_symlink():raise FlowConflict('项目目录已存在，不能覆盖已有工作')
            tmp=Path(tempfile.mkdtemp(prefix='.axiom-new-',dir=parent))
            promoted=False
            try:
                for rel in template['files']:
                    src=self.source/template_id/rel
                    if src.is_symlink() or not src.is_file() or not src.resolve().is_relative_to(self.source.resolve()):
                        raise LaunchError('模板包含不安全的文件路径')
                    if src.stat().st_size>1024*1024:raise LaunchError('模板文件超限')
                    shutil.copyfile(src,tmp/rel)
                os.replace(tmp,dest);promoted=True
                base=f'projects/{slug}/'
                try:
                    project=self.studio.flow.create(name.strip(),goal.strip(),base+template['model'],
                        base+template['manifest'] if template['manifest'] else None)
                except Exception:
                    # Files created by this operation only; no pre-existing directory was touched.
                    shutil.rmtree(dest)
                    raise
                return {'project':project,'template':template_id,'created_files':
                        [base+p for p in template['files']],
                        'next_action':'verify_spec',
                        'trust':'No executable was launched. No AI generation or production approval was performed.'}
            finally:
                if not promoted and tmp.exists():shutil.rmtree(tmp)

    def import_existing(self,source,slug,name,goal,spec,manifest=None):
        """Explicit CLI-only intake of an existing *reviewed* local project.

        Copies only the pinned Axiom spec, manifest, and files listed therein.
        Never follows source symlinks; never touches the original project.
        """
        source=Path(source).expanduser().resolve()
        if not source.is_dir() or source.is_symlink():raise LaunchError('输入来源不是可信的本地目录')
        if not isinstance(slug,str) or not re.fullmatch(r'[a-z][a-z0-9_-]{2,31}',slug):
            raise LaunchError('非法目录标识')
        if not isinstance(name,str) or not 2<=len(name.strip())<=100:raise LaunchError('项目名称无效')
        if not isinstance(goal,str) or not 4<=len(goal.strip())<=2000:raise LaunchError('目标陈述无效')
        def checked(rel):
            if not isinstance(rel,str) or not rel or '\\' in rel or Path(rel).is_absolute() or '..' in Path(rel).parts:
                raise LaunchError('来源清单路径不安全')
            p=source/rel
            if not p.is_file() or p.is_symlink() or not p.resolve().is_relative_to(source):
                raise LaunchError('来源文件不在指定目录内，或包含符号链接：'+rel)
            if p.stat().st_size>1024*1024 or p.suffix not in {'.ax','.json','.cpp','.hpp','.h','.cc','.c'}:
                raise LaunchError('来源文件类型或大小不允许：'+rel)
            return p
        if not isinstance(spec,str) or not spec.endswith('.ax'):raise LaunchError('必须指定 .ax 规格文件')
        rels={spec}
        if manifest:
            if not isinstance(manifest,str) or not manifest.endswith('.json'):
                raise LaunchError('必须指定 JSON 工程清单')
            mp=checked(manifest)
            data=json.loads(mp.read_text('utf-8'))
            if data.get('schema')!='ax-cpp-project/0.1':raise LaunchError('不支持的清单协议')
            linked=(mp.parent/data.get('spec','')).resolve()
            if linked!=checked(spec).resolve():raise LaunchError('清单关联的规格与所选规格不同')
            rels.add(manifest)
            for f in data.get('files',[]):
                if not isinstance(f,str) or f.startswith('/') or '..' in Path(f).parts:
                    raise LaunchError('工程源文件清单不合法')
                actual=(mp.parent/f).resolve()
                if not actual.is_relative_to(source):raise LaunchError('工程文件越界')
                rels.add(actual.relative_to(source).as_posix())
        if len(rels)>90:raise LaunchError('工程文件数量超限')
        size=0
        for rel in rels:
            size+=checked(rel).stat().st_size
            if size>5*1024*1024:raise LaunchError('导入工程超出 5 MiB 限额')
        with self.lock:
            parent=self.workspace/'projects';parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            if parent.is_symlink() or not parent.resolve().is_relative_to(self.workspace.resolve()):
                raise LaunchError('工作区目录不安全')
            dest=parent/slug
            if dest.exists() or dest.is_symlink():raise FlowConflict('项目目录已存在，不得覆盖')
            tmp=Path(tempfile.mkdtemp(prefix='.axiom-import-',dir=parent))
            promoted=False
            try:
                for rel in sorted(rels):
                    output=tmp/rel
                    output.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(checked(rel),output)
                os.replace(tmp,dest);promoted=True
                prefix=f'projects/{slug}/'
                try: project=self.studio.flow.create(name,goal,prefix+spec,
                            prefix+manifest if manifest else None)
                except Exception:
                    shutil.rmtree(dest)
                    raise
                return {'project':project,'created_files':[prefix+f for f in sorted(rels)],
                    'original_untouched':True,'next_action':'verify_spec',
                    'warning':'Explicit copy import: review local sources before any native execution.'}
            finally:
                if not promoted and tmp.exists():shutil.rmtree(tmp)

    def _next(self,p,production):
        state=p['effective_status']
        contract=production.get('contract')
        if state=='stale':return ('fork','建立演化分支','规格或工程清单变化；旧验证不可继续', 'blocked')
        if state in ('draft','spec_blocked'):return ('verify','运行规格验证','执行 Axiom 规格检查、模型验证和 Gate；不执行 C++', 'ready')
        if not contract:return ('freeze','确认需求—性质映射','人工审核并冻结生产契约，避免无验收目标的实现', 'human')
        if state=='accepted_test_only':
            if production.get('eligible_for_live_recheck'):
                return ('passport','申请测试级生产护照','仍需实时 C++ Gate 与人工确认；非发布许可','human')
            return ('inspect','查看历史证据与状态','裁决信息已记录；检查版本和证据是否仍有效','ready')
        if state=='spec_ready':
            if p['manifest']:return ('batch','提交或比较实现方案','AI、VS Code 或人工提交候选，先暂存再验证','ready')
            return ('task','导出 AI 构造任务','模型项目已具备生成受约束任务包的条件','ready')
        if state in ('candidate_review','candidate_apply','candidate_validate','decision_pending'):
            return ('candidate','处理候选审查与验证','按原工作流完成对应人工决策或验证','human')
        return ('inspect','查看阻断诊断','必须解决失败或过期证据，不能跳过准入条件','blocked')

    def queue(self):
        items=[]
        for p in self.studio.flow.list():
            try:
                prod=self.studio.production.overview(p['id'])
                action,label,why,kind=self._next(p,prod)
                blockers=prod.get('blockers',[])
            except (FlowError,ValueError,OSError) as exc:
                action,label,why,kind='inspect','查看项目异常',str(exc)[:200],'blocked'
                blockers=['PRODUCTION_OVERVIEW_UNAVAILABLE']
            items.append({'project_id':p['id'],'name':p['name'],'state':p['effective_status'],
                'next_action':action,'label':label,'reason':why,'category':kind,
                'blockers':blockers,'revision':p['revision']})
        order={'blocked':0,'human':1,'ready':2}
        items.sort(key=lambda v:(order.get(v['category'],3),v['name']))
        return {'items':items,'counts':{'attention':sum(v['category']!='ready' for v in items),
            'total':len(items)},'scope':'Workflow hints only. No automated approval.'}

    def export(self,pid):
        """Return a capped, reproducible unsigned transfer ZIP for offline review.

        Does not include secrets or runtime evidence databases. Audit/event summaries
        are labeled as summaries, not authenticated attestations.
        """
        p=self.studio.flow.get(pid)
        production=self.studio.production.overview(pid)
        audit=self.studio.flow.audit(pid)
        graph=self.studio.production.graph(pid)
        packet=None
        if production.get('contract') and not p['stale']:
            packet=self.studio.production.task_packet(pid)
        rels={p['spec']}
        if p['manifest']:
            rels.add(p['manifest'])
            manifest_path=self.studio.flow._file(p['manifest'],'.json')
            spec=json.loads(manifest_path.read_text('utf-8'))
            for rel in spec.get('files',[]):
                if not isinstance(rel,str) or not rel or '\\' in rel or Path(rel).is_absolute() or '..' in Path(rel).parts:
                    raise LaunchError('清单包含不安全文件路径')
                abs_path=(manifest_path.parent/rel).resolve()
                if not abs_path.is_relative_to(self.workspace.resolve()):
                    raise LaunchError('工程文件越出工作区')
                rels.add(abs_path.relative_to(self.workspace).as_posix())
        archive_files={}
        total=0
        for rel in sorted(rels):
            full=self.studio.flow.guard(rel)
            raw=full.read_bytes()
            total+=len(raw)
            if len(raw)>1024*1024 or total>5*1024*1024 or len(rels)>90:
                raise LaunchError('交接包超过大小/数量上限')
            archive_files['workspace/'+rel]=raw
        overview={'schema':'ax-handoff/0.7','project_id':pid,'project':p,
            'production':production,'trace_graph':graph,
            'workflow_audit':{'chain_valid':audit.get('chain_valid'),
                'events_count':audit.get('events',0) if isinstance(audit.get('events'),int) else len(audit.get('events',[])),
                'note':'Event digest chain checked in local database; this export is not a signed attestation.'},
            'construction_task':packet,
            'limitations':['Unsigned local exchange package',
                'Does not contain private model API credentials, evidence databases or authorization keys',
                'Model Bounded and C++ Tested are not production release authorizations',
                'The recipient must revalidate all evidence in its own trusted environment']}
        archive_files['handoff/project.json']=json.dumps(overview,ensure_ascii=False,indent=2).encode()
        digest_map={'schema':'ax-handoff-sha256/0.7','files':{k:_digest(v) for k,v in sorted(archive_files.items())}}
        archive_files['handoff/SHA256.json']=json.dumps(digest_map,ensure_ascii=False,indent=2).encode()
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for name,raw in sorted(archive_files.items()):
                z.writestr(name,raw)
        return out.getvalue(),f'Axiom-Handoff-{pid}.zip'
