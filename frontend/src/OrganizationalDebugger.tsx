import {useEffect, useMemo, useRef, useState} from "react";
import {ArrowRight, Check, ChevronRight, FileText, FlaskConical, LoaderCircle, Search, ShieldCheck} from "lucide-react";
import type {Audit} from "./types";
import type {DebugTrace, Relation, Responsibility, TestData} from "./debuggerTypes";
import "./debugger.css";

const relations: Record<Relation,string> = {
  PRESERVED:"Сохранена", MOVED:"Перенесена", SPLIT:"Возможное разделение", MERGED:"Возможное объединение",
  DUPLICATED:"Конкурирующие владельцы", POTENTIAL_GAP:"Возможный пробел", POTENTIAL_AUTHORITY_CONFLICT:"Риск конфликта полномочий", UNKNOWN:"Связь не установлена",
};
const tests: Record<string,string> = {
  OWNER_CONTINUITY:"Непрерывность владельца", RESPONSIBILITY_TRANSFER:"Основание передачи",
  SCOPE_CONTINUITY:"Границы ответственности", DUPLICATE_OWNERSHIP:"Конкурирующие владельцы",
  AUTHORITY_CONFLICT:"Совместимость полномочий", SPLIT_MERGE:"Разделение / объединение", SOURCE_INTEGRITY:"Целостность источников",
};
const authorities: Record<string,string> = {duty:"обязанность",right:"право",prohibition:"запрет",unknown:"не установлено"};
const statuses: Record<string,string> = {PASS:"Проверено", REVIEW:"На проверку", FAIL:"Ошибка", NOT_APPLICABLE:"Не требуется"};
const tools: Record<string,string> = {form_hypothesis:"Рабочая гипотеза",get_responsibility:"Исходная ответственность",search_responsibility:"Поиск доказательств",compare_candidate:"Проверка кандидата",search_counter_evidence:"Попытка опровергнуть гипотезу",revise_hypothesis:"Пересмотр гипотезы",request_human_review:"Решение остаётся за аудитором"};
const priority: Record<Relation,number> = {POTENTIAL_GAP:0,POTENTIAL_AUTHORITY_CONFLICT:1,SPLIT:2,MERGED:3,DUPLICATED:4,UNKNOWN:5,MOVED:6,PRESERVED:7};

async function read<T>(url:string, init?:RequestInit):Promise<T> {
  const response=await fetch(url,init);
  if(!response.ok) throw new Error("Не удалось выполнить проверку. Повторите запрос после проверки backend.");
  return response.json();
}

export function OrganizationalDebugger({record,onSources,onFinding}:{record:Audit;onSources:(ids:string[])=>void;onFinding:(id:string)=>void}) {
  const [data,setData]=useState<TestData|null>(null), [active,setActive]=useState<string>(""),
    [filter,setFilter]=useState("REVIEW"),[query,setQuery]=useState(""), [error,setError]=useState(""),
    [trace,setTrace]=useState<DebugTrace|null>(null),[busy,setBusy]=useState(false);
  const epoch=useRef(0);
  useEffect(()=>{
    const controller=new AbortController();
    setData(null);setTrace(null);setError("");setBusy(false);epoch.current++;
    read<TestData>(`/api/audits/${encodeURIComponent(record.id)}/organizational-tests`,{signal:controller.signal})
      .then(result=>{setData(result);setActive([...result.responsibilities].sort((a,b)=>priority[a.relation]-priority[b.relation])[0]?.lineage_id||"");})
      .catch(e=>{if(e.name!=="AbortError") setError(e.message);});
    return ()=>{controller.abort();epoch.current++;};
  },[record.id]);
  const claims=useMemo(()=>Object.fromEntries(record.ir.claims.map(c=>[c.id,c])),[record]);
  const units=useMemo(()=>Object.fromEntries(record.ir.units.map(u=>[u.id,u])),[record]);
  const findings=useMemo(()=>Object.fromEntries(record.findings.map(f=>[f.id,f])),[record]);
  const grouped=useMemo(()=>{
    const groups:Record<string,TestData["tests"]>={};
    for(const t of data?.tests||[]) (groups[t.lineage_id]??=[]).push(t);
    return groups;
  },[data]);
  const title=(r:Responsibility)=>claims[r.before_claim_ids[0]]?.text||claims[r.after_claim_ids[0]]?.text||findings[r.finding_ids[0]]?.title||"Документарный риск";
  const state=(r:Responsibility)=>grouped[r.lineage_id]?.some(t=>t.status==="FAIL")?"FAIL":grouped[r.lineage_id]?.some(t=>t.status==="REVIEW")?"REVIEW":"PASS";
  const list=(data?.responsibilities||[]).filter(r=>(filter==="ALL"||state(r)===filter)&&`${r.id} ${title(r)}`.toLowerCase().includes(query.toLowerCase())).sort((a,b)=>priority[a.relation]-priority[b.relation]||a.id.localeCompare(b.id));
  const selected=list.find(r=>r.lineage_id===active)||list[0];
  const chosen=selected?.lineage_id;
  useEffect(()=>{setTrace(null);setBusy(false);epoch.current++;},[chosen]);
  async function investigate(){
    if(!selected)return;
    const requestEpoch=++epoch.current;
    setBusy(true);setError("");
    try {
      const result=await read<DebugTrace>(`/api/audits/${encodeURIComponent(record.id)}/responsibility-investigation`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({lineage_id:selected.lineage_id})});
      if(epoch.current===requestEpoch)setTrace(result);
    }catch(e){if(epoch.current===requestEpoch)setError((e as Error).message);}
    finally{if(epoch.current===requestEpoch)setBusy(false);}
  }
  return <section className="org-debugger" aria-label="Организационные тесты">
    <div className="debug-intro"><div><span className="eyebrow">ORG-X / THE ORGANIZATIONAL DEBUGGER</span><h2>Что произошло с ответственностью?</h2><p>Документы → модель ответственности → проверки → расследование → точные источники.</p></div><FlaskConical size={32}/></div>
    {error&&<p role="alert" className="error">{error}</p>}
    {!data&&!error&&<p role="status"><LoaderCircle size={16}/> Загружаем результаты проверок…</p>}
    {data&&<>
      <div className="debug-summary">
        <button onClick={()=>setFilter("ALL")} className={filter==="ALL"?"selected":""}><strong>{data.responsibilities.length}</strong><span>Проверяемых записей</span></button>
        <button onClick={()=>setFilter("PASS")} className={filter==="PASS"?"selected":""}><strong>{data.summary.responsibilities_pass||0}</strong><span>PASS · проверено</span></button>
        <button onClick={()=>setFilter("REVIEW")} className={filter==="REVIEW"?"selected":""}><strong>{data.summary.responsibilities_review||0}</strong><span>REVIEW · на проверку</span></button>
        <button onClick={()=>setFilter("FAIL")} className={filter==="FAIL"?"selected":""}><strong>{data.summary.responsibilities_fail||0}</strong><span>FAIL · ошибки проверки</span></button>
      </div>
      <p className="debug-disclosure">{data.summary.checks} проверок по 7 правилам. PASS означает выполнение документарного условия; полнота смыслового анализа и решение человека проверяются отдельно. Записи включают исходные функции, функции без установленного предшественника и отдельные риски.</p>
      <div className="debug-workbench">
        <aside className="debug-list"><label className="debug-search"><Search size={16}/><input aria-label="Найти ответственность" placeholder="Функция или R-ID…" value={query} onChange={e=>setQuery(e.target.value)}/></label>
          <div className="debug-list-meta">{list.length} записей · {filter==="ALL"?"Все":statuses[filter]}</div>
          {list.map(r=><button className={`debug-row ${selected?.lineage_id===r.lineage_id?"active":""}`} key={r.lineage_id} onClick={()=>setActive(r.lineage_id)}>
            <span className="debug-id">{r.id}</span><strong>{title(r)}</strong><span className={`debug-relation ${r.relation.toLowerCase()}`}>{relations[r.relation]}</span><ChevronRight size={16}/></button>)}
          {!list.length&&<p className="debug-empty">По выбранному фильтру записей нет.</p>}
        </aside>
        <div className="debug-detail">{selected?<>
          <div className="debug-detail-heading"><span className="debug-id">{selected.id}</span><span className="debug-pending">REQUIRES HUMAN REVIEW</span><h3>{title(selected)}</h3><p>{selected.explanation}</p></div>
          <div className="debug-versions">{(["before","after"] as const).map(v=>{
            const ids=v==="before"?selected.before_claim_ids:selected.after_claim_ids;
            return <section key={v}><span className="eyebrow">{v==="before"?"ДО ИЗМЕНЕНИЙ":"ПОСЛЕ ИЗМЕНЕНИЙ"}</span>
              {!ids.length&&<p>{v==="before"?"Предшественник не установлен":"Подтверждённый преемник не установлен"}</p>}
              {ids.map(id=><div key={id}><strong>{units[claims[id]?.unit_id]?.name}</strong><p>{claims[id]?.text}</p><small>Полномочие: {authorities[claims[id]?.authority]||claims[id]?.authority} · область: {claims[id]?.context_text||"не указан отдельно"}</small><button className="text-button" onClick={()=>onSources(claims[id]?.source_span_ids||[])}><FileText size={13}/> Точный фрагмент</button></div>)}
              {v==="after"&&selected.basis==="COMPOSITION_HYPOTHESIS"&&<small>Кандидаты на разделение/объединение. Назначение не подтверждено.</small>}
            </section>;
          })}</div>
          <div className="debug-checks" aria-label="Семь организационных проверок">{(grouped[selected.lineage_id]||[]).map(t=><details key={t.id}><summary><span className={`debug-status ${t.status.toLowerCase()}`}>{t.status==="PASS"?<Check size={13}/>:t.status==="NOT_APPLICABLE"?"—":"!"}</span><strong>{tests[t.test]}</strong><small>{statuses[t.status]}</small></summary><p>{t.detail}</p><button className="text-button" onClick={()=>onSources(t.source_span_ids)}>Проверить источники <ArrowRight size={13}/></button></details>)}</div>
          <div className="debug-actions"><button className="button primary" disabled={busy} onClick={investigate}>{busy?<LoaderCircle size={16}/>:<Search size={16}/>} {busy?"Проверяем гипотезы…":"INVESTIGATE · Расследовать"}</button><span>Локальный поиск, проверка кандидатов и контрдоказательств</span></div>
          {trace&&<section className="debug-trace" aria-label="Результат расследования"><span className="eyebrow">ВЫПОЛНЕННОЕ РАССЛЕДОВАНИЕ</span><h3>{relations[trace.initial_hypothesis]} <ArrowRight size={18}/> {relations[trace.final_hypothesis]}</h3><p>{trace.revised?"Гипотеза пересмотрена по результатам проверок.":"Новых оснований для смены гипотезы не найдено."}</p>
            <ol>{trace.steps.map(s=><li key={s.sequence}><span className="debug-step-number">{String(s.sequence).padStart(2,"0")}</span><div><strong>{tools[s.tool]||s.tool}</strong><p>{s.detail}</p>{s.source_span_ids.length>0&&<button className="text-button" onClick={()=>onSources(s.source_span_ids)}>Открыть {s.source_span_ids.length} фрагм. <ArrowRight size={13}/></button>}</div></li>)}</ol><p className="debug-disclosure">{trace.limitation}</p>
          </section>}
          <div className="debug-review"><ShieldCheck size={22}/><div><strong>Проверьте доказательства и зафиксируйте решение</strong><p>Оригинальный аудит сохраняется. Решение аудитора ведётся отдельным журналом.</p>{selected.finding_ids.map(id=><button key={id} className="text-button" onClick={()=>onFinding(id)}>Вывод и решение аудитора <ArrowRight size={14}/></button>)}</div></div>
        </>:<p className="debug-empty">Выберите другой фильтр или запрос.</p>}</div>
      </div>
    </>}
  </section>;
}
