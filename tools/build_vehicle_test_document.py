"""Build the standalone field test document from its Markdown source (stdlib only)."""
import argparse
import hashlib
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs' / 'testing' / 'vehicle_test_plan.md'
TARGET = ROOT / 'docs' / 'testing' / 'One_Click_Log_Vehicle_Test_Plan.html'
source = SOURCE.read_text(encoding='utf-8-sig')

def inline(text):
    text = html.escape(text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    return re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)

parts = []
case_open = False
list_tag = None
lines = source.splitlines()
i = 0
while i < len(lines):
    line = lines[i].strip()
    if not line:
        if list_tag:
            parts.append(f'</{list_tag}>')
            list_tag = None
        i += 1
        continue
    if line.startswith('#'):
        if list_tag:
            parts.append(f'</{list_tag}>')
            list_tag = None
        level = len(line) - len(line.lstrip('#'))
        label = line[level:].strip()
        case = re.match(r'(TC-\d{2}) (.+)', label)
        if case_open:
            parts.append('</article>')
            case_open = False
        if case:
            parts.append(f'<article class="testcase" id="{case[1]}"><h3>{inline(label)}</h3>')
            case_open = True
        else:
            parts.append(f'<h{level}>{inline(label)}</h{level}>')
        i += 1
        continue
    if line.startswith('|'):
        if list_tag:
            parts.append(f'</{list_tag}>')
            list_tag = None
        rows = []
        while i < len(lines) and lines[i].strip().startswith('|'):
            cells = [x.strip() for x in lines[i].strip().strip('|').split('|')]
            if not all(re.fullmatch(r':?-+:?', x) for x in cells):
                rows.append(cells)
            i += 1
        parts.append('<div class="table-scroll"><table><thead><tr>' + ''.join('<th>'+inline(c)+'</th>' for c in rows[0]) + '</tr></thead><tbody>')
        for row in rows[1:]:
            parts.append('<tr>'+''.join('<td>'+inline(c)+'</td>' for c in row)+'</tr>')
        parts.append('</tbody></table></div>')
        continue
    ordered = re.match(r'^\d+\. (.+)', line)
    bullet = line.startswith('- ')
    if ordered or bullet:
        tag = 'ol' if ordered else 'ul'
        if list_tag != tag:
            if list_tag:
                parts.append(f'</{list_tag}>')
            parts.append(f'<{tag}>')
            list_tag = tag
        parts.append('<li>'+inline(ordered[1] if ordered else line[2:])+'</li>')
    else:
        if list_tag:
            parts.append(f'</{list_tag}>')
            list_tag = None
        parts.append('<p>'+inline(line)+'</p>')
    i += 1
if list_tag:
    parts.append(f'</{list_tag}>')
if case_open:
    parts.append('</article>')
assert len(re.findall(r'<article class="testcase"', ''.join(parts))) == 48
meta = {
    'schema': 'one-click-log-vehicle-test-results-v1',
    'document_revision': '2026-10-25.2',
    'reference_app_version': '0.9.22',
    'source_sha256': hashlib.sha256(source.encode('utf-8')).hexdigest(),
}
styles = '''
:root{font-family:"Malgun Gothic","맑은 고딕",Arial,sans-serif;color:#172b3b;background:#edf2f5;font-size:15px;line-height:1.75}
*{box-sizing:border-box}body{margin:0}main{max-width:1060px;margin:auto;padding:36px 42px 80px;background:white}
h1{font-size:30px;line-height:1.4;font-weight:750;color:#111;margin:0 0 20px}h2{font-size:23px;line-height:1.5;margin:45px 0 18px;color:#183e55}h3{font-size:19px;line-height:1.5;margin:0 0 12px;color:#123f55}
p{margin:12px 0}li{padding:3px 0}ul,ol{padding-left:24px}code{font-family:Consolas,monospace;font-size:.94em;overflow-wrap:anywhere;background:#f0f4f6;padding:1px 4px}
.table-scroll{overflow-x:auto;margin:20px 0}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;vertical-align:top;border:1px solid #cbd6dd;padding:10px 12px;overflow-wrap:anywhere}th{background:#eaf2f6;color:#183e55}
.testcase{border:1px solid #cbd8df;border-radius:8px;padding:22px 24px;margin:22px 0 28px;scroll-margin-top:25px}.testcase ul{margin:8px 0 16px}.testcase li{margin:6px 0}
.toolbar{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}.toolbar button,.toolbar label{border:0;background:#164b65;color:white;font:inherit;font-size:14px;border-radius:5px;padding:9px 16px;cursor:pointer}.toolbar input{display:none}.toolbar button:focus-visible,.toolbar label:focus-within{outline:3px solid #e3ae36}
.panel{padding:22px;background:#f3f7fa;border-radius:8px;margin:24px 0}.panel h2{margin:0 0 12px;font-size:21px}.panel p{font-size:14px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px 18px}.full{grid-column:1/-1}
label.field{display:flex;flex-direction:column;gap:4px;font-size:13px;color:#304e60}input,select,textarea{width:100%;min-width:0;font:inherit;font-size:14px;color:#172b3b;background:white;border:1px solid #9bafbc;border-radius:4px;padding:8px 10px}textarea{resize:vertical;min-height:76px;overflow:hidden;line-height:1.65}input:focus,select:focus,textarea:focus{outline:2px solid #29758e;outline-offset:1px}
.result-form{background:#f2f7f9;border-radius:5px;padding:16px}.result-form h4{font-size:15px;margin:0 0 10px}.muted{color:#536e7d;font-size:13px}.statusbar{font-size:14px;font-weight:650;color:#174961;margin:10px 0}.tc-nav{display:flex;flex-wrap:wrap;gap:8px}.tc-nav a{color:#164b65;background:white;border:1px solid #b1c5d0;border-radius:4px;padding:3px 9px;text-decoration:none;font-size:13px}.save-note{background:#fff6dc;padding:10px 14px;border-radius:5px}#notice{min-height:24px;color:#244c61;font-weight:600}
@media(max-width:650px){main{padding:22px 18px 50px}h1{font-size:25px}h2{font-size:21px}.grid{grid-template-columns:1fr}.testcase{padding:17px 14px}.panel{padding:16px}.full{grid-column:auto}table{min-width:560px}}
@media print{@page{size:A4;margin:16mm}body,main{background:white}main{max-width:none;padding:0}body{font-size:10pt;line-height:1.6}h1{font-size:21pt}h2{font-size:15pt;break-after:avoid}h3{font-size:12pt;break-after:avoid}.toolbar,.tc-nav,#notice,.save-note{display:none}.testcase{border:1px solid #bbb;padding:12px;margin:15px 0;break-inside:auto}.result-form{break-inside:avoid}table{font-size:9pt;min-width:0}tr{break-inside:avoid}thead{display:table-header-group}.table-scroll{overflow:visible}input,textarea,select{font-size:9pt;border-color:#bbb}li{break-inside:avoid}code{overflow-wrap:anywhere}}
'''
script = r'''
'use strict';
const meta=__META__;
const fields=[['run_id','시험 회차 ID'],['tester','시험자'],['date_timezone','시험일과 시간대'],['actual_version_build','실제 EXE 버전과 빌드 ID'],['artifact_hash','배포 ZIP 또는 EXE SHA256'],['pc_windows','PC 별칭과 Windows 빌드'],['vehicle_ecu','차량 별칭과 ECU SW 버전'],['canoe_vector','CANoe 옵션·Vector 드라이버와 장비'],['can_config','CAN cfg 별칭·BLF 블록·채널'],['diag_config','Diag cfg 별칭·BLF 블록·채널'],['comparison_reference','동일 버스 비교 근거와 DBC 버전'],['nic','NIC 이름·식별자·포트'],['capture_tools','TShark와 Npcap 버전'],['zipy_rules','실제 Zipy 규칙·시간·최소 pps'],['storage','저장 위치 별칭·prefix·최초 번호'],['capacity','초기 여유와 예상 기록량'],['scenario','환경과 승인된 시험 시나리오']];
const statuses=['Not Run','Pass','Fail','Blocked','N/A'];
const cases=[...document.querySelectorAll('article.testcase')].map(el=>({id:el.id,title:el.querySelector('h3').textContent,definition:el.innerText}));
const environment=document.getElementById('environment');
function field(parent,key,label,type='input',full=false){const wrap=document.createElement('label');wrap.className='field'+(full?' full':'');const cap=document.createElement('span');cap.textContent=label;const control=document.createElement(type);control.dataset.field=key;control.setAttribute('aria-label',label);if(type==='input')control.type='text';if(type==='textarea')control.rows=2;wrap.append(cap,control);parent.append(wrap);return control;}
fields.forEach(([key,label])=>field(environment,key,label,'input',key==='scenario'));
const resultFields=[['trial','회차'],['time_range','시작·종료·이상 시각과 시간대'],['targets_index','선택 대상·prefix·예약 번호'],['actual','실제 순서·결과·측정값과 파일별 읽기 결과'],['evidence','ZIP·원본·화면 증빙 이름과 생성 시각'],['issue','결함 ID·재현율·복구 내용 또는 Blocked/N/A 사유']];
for(const tc of cases){const el=document.getElementById(tc.id);const form=document.createElement('div');form.className='result-form';const h=document.createElement('h4');h.textContent=tc.id+' 결과 기록';form.append(h);const grid=document.createElement('div');grid.className='grid';const status=field(grid,'status','결과 상태','select');statuses.forEach(value=>{const o=document.createElement('option');o.value=value;o.textContent=value;status.append(o);});for(const [key,label]of resultFields)field(grid,key,label,['actual','evidence','issue'].includes(key)?'textarea':'input',['actual','evidence','issue'].includes(key));form.append(grid);el.append(form);const a=document.createElement('a');a.href='#'+tc.id;a.textContent=tc.id;document.getElementById('tc-nav').append(a);}
function values(parent){return Object.fromEntries([...parent.querySelectorAll('[data-field]')].map(el=>[el.dataset.field,el.value]));}
function summary(){const counts=Object.fromEntries(statuses.map(s=>[s,0]));document.querySelectorAll('.testcase select').forEach(el=>counts[el.value]++);document.getElementById('summary').textContent=cases.length+'개 TC  |  '+statuses.map(s=>s+' '+counts[s]).join('  ·  ');return counts;}
function fit(el){if(el.tagName==='TEXTAREA'){el.style.height='auto';el.style.height=Math.max(76,el.scrollHeight+2)+'px';}}
let dirty=false;
document.addEventListener('input',e=>{if(e.target.matches('[data-field],#conclusion')){dirty=true;fit(e.target);summary();document.getElementById('notice').textContent='입력 변경됨 · 종료하거나 새로고침하기 전에 결과 JSON을 저장하세요.';}});
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
function download(){const payload={...meta,exported_utc:new Date().toISOString(),environment:values(environment),summary:summary(),results:cases.map(tc=>({...tc,...values(document.getElementById(tc.id))})),conclusion:document.getElementById('conclusion').value};const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json;charset=utf-8'});const a=document.createElement('a');const u=URL.createObjectURL(blob);a.href=u;const run=(payload.environment.run_id||'run').replace(/[^a-zA-Z0-9가-힣_-]/g,'_').slice(0,60);a.download='One_Click_Log_TestResults_'+run+'_'+new Date().toISOString().replace(/[:.]/g,'-')+'.json';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(u),1000);document.getElementById('notice').textContent='저장을 요청했습니다. 다운로드된 JSON 파일을 확인하세요. 입력 수정 후에는 다시 저장해야 합니다.';dirty=false;}
document.getElementById('export').addEventListener('click',download);
document.getElementById('export-bottom').addEventListener('click',download);
document.getElementById('choose-import').addEventListener('click',()=>document.getElementById('import').click());
document.getElementById('print').addEventListener('click',()=>window.print());
document.getElementById('import').addEventListener('change',async e=>{const f=e.target.files[0];if(!f)return;try{if(dirty&&!window.confirm('현재 입력을 바꿉니다. 이전 결과 JSON을 저장했는지 확인하세요. 계속 불러올까요?'))return;if(f.size>5*1024*1024)throw Error('결과 파일은 5 MiB 이하여야 합니다.');const data=JSON.parse(await f.text());if(data.schema!==meta.schema||!['2026-10-24.1','2026-10-25.1',meta.document_revision].includes(data.document_revision)||!Array.isArray(data.results)||data.results.length!==cases.length||!data.environment||typeof data.environment!=='object')throw Error('이 시험서와 일치하는 결과 JSON이 아닙니다.');const ids=new Set();for(const row of data.results){if(!row||!cases.some(tc=>tc.id===row.id&&tc.title===row.title)||ids.has(row.id)||!statuses.includes(row.status))throw Error('TC 또는 상태가 올바르지 않습니다.');ids.add(row.id);for(const [key] of resultFields)if(typeof row[key]!=='string')throw Error('TC 입력값이 올바르지 않습니다.');}for(const [key]of fields)if(typeof data.environment[key]!=='string')throw Error('환경 입력값이 올바르지 않습니다.');if(typeof data.conclusion!=='string')throw Error('종합 판정이 올바르지 않습니다.');for(const el of environment.querySelectorAll('[data-field]'))el.value=data.environment[el.dataset.field];for(const row of data.results){for(const el of document.getElementById(row.id).querySelectorAll('[data-field]')){el.value=row[el.dataset.field];fit(el);}}document.getElementById('conclusion').value=data.conclusion;fit(document.getElementById('conclusion'));summary();dirty=false;document.getElementById('notice').textContent='불러오기 완료: '+f.name;}catch(err){document.getElementById('notice').textContent='불러오기 실패: '+err.message;}finally{e.target.value='';}});
window.addEventListener('beforeprint',()=>document.querySelectorAll('textarea').forEach(fit));summary();
'''.replace('__META__', json.dumps(meta, ensure_ascii=False))
body = '\n'.join(parts)
# Place the form and jump list immediately after the document introduction.
insert_at = body.index('<h2>시험서 사용 방법</h2>')
form = '''<section class="panel" aria-label="현장 시험 결과 입력"><h2>현장 결과 입력</h2><p class="save-note">입력은 HTML 파일에 저장되지 않습니다. 새로고침·종료 전에 JSON을 저장하세요. ZIP·캡처 파일은 별도로 보관하고 전달하세요.</p><div class="toolbar"><button id="export" type="button">결과 JSON 저장</button><button id="choose-import" type="button">결과 JSON 불러오기</button><input id="import" type="file" accept=".json,application/json" hidden><button id="print" type="button">인쇄</button></div><div id="environment" class="grid"></div><p id="notice" role="status" aria-live="polite">아직 입력한 결과가 없습니다. 모든 TC는 Not Run입니다.</p><p id="summary" class="statusbar"></p><nav id="tc-nav" class="tc-nav" aria-label="TC 바로가기"></nav></section>'''
body = body[:insert_at] + form + body[insert_at:]
body += '<section class="panel"><h2>종합 판정 기록</h2><label class="field">미해결 결함 · 데이터 무손실과 60분 및 1 GiB 개별 판정 · 다음 시험 범위 · 판단자와 판단일<textarea id="conclusion" rows="4"></textarea></label><div class="toolbar"><button id="export-bottom" type="button">결과 JSON 저장</button><a href="#top">문서 처음으로</a></div></section>'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--check', action='store_true', help='Fail when the committed HTML is stale')
args = parser.parse_args()
document = '<!doctype html>\n<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>One Click Log 실차 시험서 48 TC</title><style>'+styles+'</style></head><body><main id="top">'+body+'</main><script>'+script+'</script></body></html>\n'
if args.check:
    if not TARGET.is_file() or TARGET.read_text(encoding='utf-8-sig') != document:
        parser.exit(1, 'Vehicle test HTML is stale. Run tools/build_vehicle_test_document.py\n')
    print('Vehicle test HTML is current: 48 cases')
else:
    TARGET.write_text(document, encoding='utf-8', newline='\n')
    print(f'{TARGET.name}: 48 cases; {TARGET.stat().st_size:,} bytes')
