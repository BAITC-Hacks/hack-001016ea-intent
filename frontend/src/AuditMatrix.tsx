import {useMemo, useState} from "react";
import type {Audit, Finding} from "./types";

const names: Record<string,string> = {PRESERVED:"Сохранена",MOVED:"Перенесена",POTENTIAL_GAP:"Возможный пробел",POTENTIAL_DUPLICATE:"Возможное дублирование",POTENTIAL_AUTHORITY_CONFLICT:"Риск конфликта полномочий",REQUIRES_HUMAN_REVIEW:"Нужна проверка",AFTER_ONLY:"Соответствие до не установлено"};

export function AuditMatrix({record,openFinding,openSources}: {record:Audit; openFinding:(f:Finding)=>void; openSources:(ids:string[])=>void}) {
  const [query,setQuery] = useState("");
  const [status,setStatus] = useState("ALL");
  const [page,setPage] = useState(0);
  const claims = useMemo(()=>Object.fromEntries(record.ir.claims.map(c=>[c.id,c])),[record]);
  const units = useMemo(()=>Object.fromEntries(record.ir.units.map(u=>[u.id,u.name])),[record]);
  const spans = useMemo(()=>Object.fromEntries(record.ir.documents.flatMap(d=>d.spans).map(s=>[s.id,s])),[record]);
  const documents = useMemo(()=>Object.fromEntries(record.ir.documents.map(d=>[d.id,d])),[record]);
  const rows = (record.matrix||[]).filter(row => (status==="ALL" || row.status===status) && [row.before_claim_id,...row.after_claim_ids].filter(Boolean).map(id=>claims[id!]).map(c=>c.text+" "+units[c.unit_id]).join(" ").toLowerCase().includes(query.toLowerCase()));
  const pages = Math.max(1,Math.ceil(rows.length/20));
  const current = Math.min(page,pages-1);
  return <section className="panel matrix-panel">
    <div className="panel-heading"><div><div className="eyebrow">СРАВНЕНИЕ ФУНКЦИЙ</div><h2>От прежней обязанности к новому владельцу</h2></div><a className="button secondary" href={`/api/audits/${record.id}/matrix.csv`} download>Скачать CSV</a></div>
    <p className="section-copy">В строках с неопределённостью справа показаны кандидаты. Их наличие не подтверждает передачу. Повтор функции в нескольких строках сохраняет неоднозначность сопоставления.</p>
    <div className="filter-bar"><input className="matrix-query" aria-label="Поиск в матрице" placeholder="Функция или владелец…" value={query} onChange={e=>{setQuery(e.target.value);setPage(0)}}/><select aria-label="Статус строки матрицы" value={status} onChange={e=>{setStatus(e.target.value);setPage(0)}}><option value="ALL">Все статусы</option>{Object.entries(names).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></div>
    <div className="matrix-scroll"><table className="audit-matrix"><thead><tr><th>Функция и владелец до</th><th>Функции и владельцы после / кандидаты</th><th>Результат</th><th>Доказательства</th></tr></thead><tbody>{rows.slice(current*20,(current+1)*20).map(row=>{
      const before = row.before_claim_id ? claims[row.before_claim_id] : null;
      return <tr key={row.id}><td>{before ? <><strong>{units[before.unit_id]}</strong><p>{before.text}</p>{before.context_text && <details><summary>Контекст и полномочие</summary>{before.authority} · {before.context_text}</details>}</> : <p>Прежнее соответствие не установлено. Доступен поиск по комплекту «до».</p>}</td><td>{row.after_claim_ids.length ? row.after_claim_ids.map(id=><div className="matrix-claim" key={id}><strong>{units[claims[id].unit_id]}</strong><details><summary>{claims[id].text.slice(0,160)}{claims[id].text.length>160?"…":""}</summary><p>{claims[id].text}</p><small>{claims[id].authority} · {claims[id].context_text||"Отдельный контекст не указан"}</small></details></div>):<p>Явный владелец не подтверждён. Проверить журнал поиска.</p>}</td><td><span className={`badge ${row.status==="PRESERVED"?"green":row.status==="MOVED"?"blue":"amber"}`}>{names[row.status]||row.status}</span>{row.finding_ids.map(id=>{const f=record.findings.find(f=>f.id===id); return f ? <button className="text-button" key={id} onClick={()=>openFinding(f)}>{f.title}</button>:null})}</td><td><button className="text-button" onClick={()=>openSources(row.source_span_ids)}>Открыть {row.source_span_ids.length} фрагм.</button>{row.source_span_ids.slice(0,3).map(id=><small className="matrix-locator" key={id}>{spans[id].version==="before"?"До":"После"} · {documents[spans[id].document_id].name} · §{spans[id].clause||"—"}</small>)}</td></tr>
    })}</tbody></table></div>
    {!rows.length && <p className="empty-state">Строк нет. Для старого сохранённого аудита повторите анализ текущей версией.</p>}
    <div className="matrix-pagination"><span>{rows.length} строк · страница {current+1} из {pages}</span><button disabled={current===0} onClick={()=>setPage(current-1)}>Назад</button><button disabled={current+1>=pages} onClick={()=>setPage(current+1)}>Далее</button></div>
  </section>
}
