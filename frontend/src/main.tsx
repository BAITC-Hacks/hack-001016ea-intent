import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Check,
  CheckCheck,
  ChevronRight,
  CircleHelp,
  FileText,
  Fingerprint,
  GitBranch,
  LayoutDashboard,
  Link2,
  ListFilter,
  LoaderCircle,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import type { Audit, Claim, Finding, FindingType, Review, Span, Candidate, AIInvestigation } from "./types";
import { AuditMatrix } from "./AuditMatrix";
import "./style.css";
import { OrganizationalDebugger } from "./OrganizationalDebugger";

const labels: Record<FindingType, string> = {
  PRESERVED: "Сохранена",
  MOVED: "Перенесена",
  POTENTIAL_GAP: "Возможный пробел",
  POTENTIAL_DUPLICATE: "Возможное дублирование",
  POTENTIAL_AUTHORITY_CONFLICT: "Риск конфликта полномочий",
  REQUIRES_HUMAN_REVIEW: "Нужна проверка",
};
const tones: Record<FindingType, string> = {
  PRESERVED: "green",
  MOVED: "blue",
  POTENTIAL_GAP: "red",
  POTENTIAL_DUPLICATE: "amber",
  POTENTIAL_AUTHORITY_CONFLICT: "red",
  REQUIRES_HUMAN_REVIEW: "amber",
};
const unitLabels: Record<string, string> = {
  RETAINED: "Сохранено",
  NEW: "Добавлено",
  REORGANIZED: "Преобразовано",
  REQUIRES_HUMAN_REVIEW: "Нужна проверка",
};
const reviewLabels: Record<string, string> = {
  ACCEPTED: "Принято",
  REJECTED: "Отклонено",
  NEEDS_INFO: "Нужны данные",
};
const nav = [
  { id: "debugger", name: "Организационные тесты", icon: CheckCheck },
  { id: "overview", name: "Обзор аудита", icon: LayoutDashboard },
  { id: "functions", name: "Функции и выводы", icon: GitBranch },
  { id: "matrix", name: "Матрица функций", icon: ListFilter },
  { id: "units", name: "Подразделения", icon: ShieldCheck },
  { id: "conclusion", name: "Заключение", icon: FileText },
];
async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const text = await response.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error(
      "Сервер не смог обработать запрос. Проверьте его состояние и свободное место на диске.",
    );
  }
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Не удалось выполнить запрос. Проверьте выбранные файлы и поля.",
    );
  return data;
}
function Badge({ type }: { type: FindingType }) {
  return (
    <span className={`badge ${tones[type]}`}>
      <i />
      {labels[type]}
    </span>
  );
}
function Modal({
  children,
  onClose,
  label,
  wide = false,
}: {
  children: React.ReactNode;
  onClose: () => void;
  label: string;
  wide?: boolean;
}) {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    el.current?.focus();
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab") {
        const all = el.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled),input,textarea,select,a[href],[tabindex="0"]',
        );
        if (!all?.length) return;
        const first = all[0],
          last = all[all.length - 1];
        if (
          e.shiftKey &&
          (document.activeElement === first ||
            document.activeElement === el.current)
        ) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", h);
    const old = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", h);
      document.body.style.overflow = old;
      previous?.focus();
    };
  }, [onClose]);
  return (
    <div className="overlay" onClick={onClose}>
      <div
        ref={el}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        className={wide ? "drawer" : "modal"}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}

function App() {
  const [record, setRecord] = useState<Audit | null>(null),
    [page, setPage] = useState("debugger"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [upload, setUpload] = useState(false);
  const [filter, setFilter] = useState("ALL"),
    [query, setQuery] = useState(""),
    [finding, setFinding] = useState<Finding | null>(null),
    [sourceIds, setSourceIds] = useState<string[]>([]),
    [drawerTab, setDrawerTab] = useState("evidence");
  const [reviews, setReviews] = useState<Review[]>([]),
    [note, setNote] = useState(""),
    [actor, setActor] = useState(""),
    [status, setStatus] = useState("ACCEPTED"),
    [saving, setSaving] = useState(false),
    [reviewError, setReviewError] = useState("");
  const [health, setHealth] = useState({
      ai_enabled: false,
      demo_available: true,
    }),
    [elapsed, setElapsed] = useState<number | null>(null),
    [cached, setCached] = useState(false),
    [aiMessage, setAiMessage] = useState("");
  const [aiCandidates, setAiCandidates] = useState<Candidate[]>([]);
  const [aiInvestigation, setAiInvestigation] = useState<AIInvestigation | null>(null);
  const beforeFile = useRef<HTMLInputElement>(null),
    afterFile = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<Record<string, File[]>>({before: [], after: []});
  useEffect(() => {
    api<typeof health>("/api/health")
      .then(setHealth)
      .catch(() =>
        setError("Backend недоступен. Запустите FastAPI на порту 8000."),
      );
    const last = localStorage.getItem("orgx-last");
    if (last)
      api<Audit>(`/api/audits/${last}`)
        .then(setRecord)
        .catch(() => localStorage.removeItem("orgx-last"));
  }, []);
  useEffect(() => {
    if (record) {
      localStorage.setItem("orgx-last", record.id);
      api<Review[]>(`/api/audits/${record.id}/reviews`)
        .then(setReviews)
        .catch(() => setError("Не удалось загрузить решения аудитора."));
    }
  }, [record]);
  const spans = useMemo(
    () =>
      Object.fromEntries(
        record?.ir.documents.flatMap((d) => d.spans).map((s) => [s.id, s]) ||
          [],
      ) as Record<string, Span>,
    [record],
  );
  const claims = useMemo(
    () =>
      Object.fromEntries(
        record?.ir.claims.map((c) => [c.id, c]) || [],
      ) as Record<string, Claim>,
    [record],
  );
  const units = useMemo(
    () => Object.fromEntries(record?.ir.units.map((u) => [u.id, u.name]) || []),
    [record],
  );
  const latest = useMemo(
    () => Object.fromEntries(reviews.map((r) => [r.finding_id, r])),
    [reviews],
  );
  const sorted = useMemo(
    () =>
      [...(record?.findings || [])].sort((a, b) => {
        const score = {
          POTENTIAL_GAP: 0,
          POTENTIAL_AUTHORITY_CONFLICT: 1,
          POTENTIAL_DUPLICATE: 2,
          MOVED: 3,
          REQUIRES_HUMAN_REVIEW: 4,
          PRESERVED: 5,
        };
        return score[a.type] - score[b.type] || a.id.localeCompare(b.id);
      }),
    [record],
  );
  const filtered = sorted.filter(
    (f) =>
      (filter === "ALL" || f.type === filter) &&
      (
        f.title +
        " " +
        f.explanation +
        " " +
        (f.before_claim_id ? claims[f.before_claim_id]?.text : "") +
        " " +
        f.source_span_ids.map((id) => spans[id]?.clause).join(" ")
      )
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const closeDrawer = React.useCallback(() => {
    setFinding(null);
    setSourceIds([]);
  }, []);
  const closeUpload = React.useCallback(() => setUpload(false), []);
  const openFinding = (f: Finding) => {
    setFinding(f);
    setSourceIds(f.source_span_ids);
    setDrawerTab("evidence");
    setNote("");
    setReviewError("");
    setAiInvestigation(null);
    setAiMessage("");
  };
  const openSources = (ids: string[]) => {
    setFinding(null);
    setSourceIds(ids);
    setDrawerTab("evidence");
  };
  async function run(demo: false | "original" | "synthetic" = false) {
    setBusy(true);
    setError("");
    const t = performance.now();
    try {
      let result;
      if (demo)
        result = await api<{ record: Audit; cached: boolean }>(demo === "synthetic" ? "/api/demo/synthetic" : "/api/demo", {
          method: "POST",
        });
      else {
        if (!files.before.length || !files.after.length)
          throw new Error("Выберите файлы для обеих версий.");
        const body = new FormData();
        for (const version of ["before", "after"]) {
          if (files[version].length > 8) throw new Error("Допускается до 8 файлов на версию.");
          for (const file of files[version]) body.append(version, file);
        }
        result = await api<{ record: Audit; cached: boolean }>("/api/audits", {
          method: "POST",
          body,
        });
      }
      setRecord(result.record);
      setCached(result.cached);
      setElapsed((performance.now() - t) / 1000);
      setPage("debugger");
      setFilter("ALL");
      setQuery("");
      setUpload(false);
      setAiMessage("");
      setAiCandidates([]);
      setAiInvestigation(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function saveReview() {
    if (!record || !finding) return;
    setSaving(true);
    setReviewError("");
    try {
      const r = await api<Review[]>(
        `/api/audits/${record.id}/findings/${finding.id}/review`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status, actor, note }),
        },
      );
      setReviews(r);
      setNote("");
    } catch (e) {
      setReviewError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  async function getSuggestions() {
    if (!record) return;
    setSaving(true);
    try {
      const result = await api<{ message: string; candidates: Candidate[] }>(
        `/api/audits/${record.id}/suggestions`,
        { method: "POST" },
      );
      setAiMessage(
        `${result.message} Кандидатов: ${result.candidates.length}.`,
      );
      setAiCandidates(result.candidates);
    } catch (e) {
      setAiMessage((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  async function investigateFinding() {
    if (!record || !finding) return;
    setSaving(true);
    setAiMessage("");
    try {
      const result = await api<AIInvestigation>(`/api/audits/${record.id}/findings/${finding.id}/investigate`, {method: "POST"});
      setAiInvestigation(result);
      setAiMessage(result.message);
    } catch (e) { setAiMessage((e as Error).message); }
    finally { setSaving(false); }
  }
  const selectFilter = (type: string) => {
    setFilter(type);
    setPage("functions");
  };
  const count = (type: string) => record?.coverage[type] || 0;
  const currentSearch = finding
    ? record?.search_results.find((s) =>
        finding.search_result_ids.includes(s.id),
      )
    : null;
  const selectedSpans = sourceIds.map((id) => spans[id]).filter(Boolean);

  function findingRow(f: Finding) {
    const claim = f.before_claim_id ? claims[f.before_claim_id] : null;
    const owners = [
      ...new Set(
        f.after_claim_ids
          .map((id) => units[claims[id]?.unit_id])
          .filter(Boolean),
      ),
    ];
    return (
      <button className="finding-row" key={f.id} onClick={() => openFinding(f)}>
        <div className={`finding-mark ${tones[f.type]}`}>
          {f.type === "PRESERVED" ? (
            <Check size={18} />
          ) : f.type === "MOVED" ? (
            <ArrowRight size={18} />
          ) : (
            <CircleHelp size={18} />
          )}
        </div>
        <div className="finding-body">
          <div className="flex flex-wrap items-center gap-2">
            <Badge type={f.type} />
            {latest[f.id] && (
              <span className="reviewed">
                <CheckCheck size={12} />
                {reviewLabels[latest[f.id].status]}
              </span>
            )}
          </div>
          <h3>
            {(f.type === "PRESERVED" || f.rule_id === "uncertain-chain-v1") &&
            claim
              ? claim.text
              : f.title}
          </h3>
          <p>{claim ? `До: ${units[claim.unit_id]}` : f.explanation}</p>
          {owners.length > 0 && (
            <p className="after-owner">
              {f.type === "PRESERVED" || f.type === "MOVED"
                ? "После: "
                : "Кандидаты: "}
              {owners.join(" / ")}
            </p>
          )}
          <div className="source-meta">
            <Link2 size={12} />
            {f.source_span_ids.length} фрагм. ·{" "}
            {claim ? f.source_span_ids
              .filter((id) => spans[id]?.version === "before")
              .slice(0, 1)
              .map((id) => `До §${spans[id]?.clause}`) : "Поиск по комплекту до"}{" "}
            <span>→</span> После ·{" "}
            {f.confidence === "high"
              ? "сильная"
              : f.confidence === "medium"
                ? "частичная"
                : "неполная"}{" "}
            цепочка
          </div>
        </div>
        <ArrowUpRight className="row-arrow" size={19} />
      </button>
    );
  }

  function candidateCard(c: Candidate) {
    return <button className="candidate" key={`${c.before_claim}:${c.after_claim}`} onClick={()=>{setSourceIds([...new Set([...(finding?.source_span_ids||[]),...c.evidence])]);setDrawerTab("evidence")}}><span className="badge amber">Предложение AI · требуется проверка</span><p><strong>До:</strong> {claims[c.before_claim]?.text}</p><p><strong>После:</strong> {claims[c.after_claim]?.text}</p><small>{units[claims[c.before_claim]?.unit_id]} → {units[claims[c.after_claim]?.unit_id]}</small>{c.checks && <p className="candidate-checks">{c.checks.same_owner?"Владелец совпадает":"Владельцы различаются"} · {c.checks.same_modality?"Модальность совпадает":"Модальность различается"} · {c.checks.same_context?"Контекст совпадает":"Контекст различается"}</p>}</button>
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setPage("debugger");
          }}
        >
          <span className="brand-symbol">
            <GitBranch size={24} />
          </span>
          ORG<span className="brand-x">-X</span>
        </a>
        <div className="brand-caption">THE ORGANIZATIONAL DEBUGGER</div>
        <div className="workspace-label">РАБОЧЕЕ ПРОСТРАНСТВО</div>
        <div className="workspace">
          <span>Н</span>
          <div>
            HackAlem AI<small>Трек 11 · Казахтелеком</small>
          </div>
        </div>
        <nav>
          {nav.map((n) => (
            <button
              key={n.id}
              className={page === n.id ? "active" : ""}
              onClick={() => setPage(n.id)}
            >
              <n.icon size={18} />
              {n.name}
              {n.id === "functions" && record && (
                <em>{record.findings.length}</em>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-indicator">
            <i />
            Локальная рабочая среда
          </div>
          <p>
            AI proposes.
            <br />
            Evidence proves.
            <br />
            <strong>Human decides.</strong>
          </p>
          <div className="sidebar-footer">
            ORG-X <span>v2.1</span>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div>
            Рабочее пространство <ChevronRight size={13} />
            <strong>{nav.find((n) => n.id === page)?.name}</strong>
          </div>
          <div className="topbar-right">
            <span className="engine-label">
              <ShieldCheck size={14} />
              Evidence-first
            </span>
            <span className="avatar">HA</span>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">АУДИТ ОРГАНИЗАЦИОННЫХ ИЗМЕНЕНИЙ</div>
              <h1>
                {page === "debugger" ? "Проверка непрерывности ответственности" : page === "overview"
                  ? "От изменений — к ответственности"
                  : page === "functions"
                    ? "Каждый вывод — с доказательством"
                    : page === "matrix"
                      ? "Функции до и после — рядом"
                    : page === "units"
                      ? "Что изменилось в структуре"
                      : "Аналитическое заключение"}
              </h1>
              <p>Кто теперь владеет каждой функцией — и чем это доказано?</p>
            </div>
            <button
              className="button primary"
              onClick={() => {
                setError("");
                setUpload(true);
              }}
            >
              <Plus size={17} />
              Новый аудит
            </button>
          </div>
          {error && (
            <div role="alert" className="error">
              {error}
              <button aria-label="Закрыть ошибку" onClick={() => setError("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {!record ? (
            <section className="welcome">
              <div className="welcome-graphic">
                <FileText size={44} />
                <span>
                  <ArrowRight size={24} />
                </span>
                <ShieldCheck size={44} />
              </div>
              <div className="eyebrow">
                ДВЕ ВЕРСИИ. ОДНА ПРОВЕРЯЕМАЯ КАРТИНА.
              </div>
              <h2>
                Изменения видны.
                <br />
                Ответственность доказуема.
              </h2>
              <p>
                Сравните документы «до» и «после», найдите владельцев функций и
                откройте точный источник любого вывода.
              </p>
              <div className="flex justify-center flex-wrap gap-3">
                <button
                  className="button primary"
                  disabled={busy}
                  onClick={() => run("synthetic")}
                >
                  {busy ? (
                    <LoaderCircle className="spin" size={16} />
                  ) : (
                    <ArrowRight size={16} />
                  )}
                  Открыть контрольный комплект
                </button>
                {health.demo_available && <button className="button secondary" disabled={busy} onClick={()=>run("original")}>Оригинальная пара · ред. 8 → 9</button>}
                <button
                  className="button secondary"
                  onClick={() => setUpload(true)}
                >
                  <Upload size={16} />
                  Загрузить документы
                </button>
              </div>
              <small>Контрольный комплект — синтетические данные: 3 файла до и 3 после. Оригиналы доступны отдельно при наличии.</small>
              <div className="welcome-features">
                <div>
                  <span>01</span>Организационная модель
                </div>
                <div>
                  <span>02</span>Цепочка доказательств
                </div>
                <div>
                  <span>03</span>Решение аудитора
                </div>
              </div>
            </section>
          ) : (
            <>
              {record.ir.documents.some(d=>d.spans.some(s=>s.exact_text.includes("Синтетический контрольный пример ORG-X"))) && <div className="synthetic-notice">Синтетический контрольный пример. Эти подразделения и функции не являются фактами документов Казахтелекома.</div>}
              <section className="document-strip">
                <div className="doc-pair">
                  {record.ir.documents.map((d, i) => (
                    <React.Fragment key={d.id}>
                      {i > 0 && d.version !== record.ir.documents[i-1].version && (
                        <ArrowRight className="doc-arrow" size={17} />
                      )}
                      <button
                        onClick={() => openSources(d.spans.map((s) => s.id))}
                      >
                        <span className="doc-icon">
                          <FileText size={19} />
                        </span>
                        <div>
                          <small>
                            {d.version === "before"
                              ? "ДО ИЗМЕНЕНИЙ"
                              : "ПОСЛЕ ИЗМЕНЕНИЙ"}
                          </small>
                          <strong title={d.name}>
                            {d.name
                              .replace("Внутренний_аудит_", "")
                              .replaceAll("_", " ")}
                          </strong>
                        </div>
                      </button>
                    </React.Fragment>
                  ))}
                </div>
                <div className="run-status">
                  <Check size={14} />
                  Анализ завершён
                  <small>
                    {elapsed !== null
                      ? `${elapsed.toFixed(2)} с · ${cached ? "из кэша" : "локальный анализ"}`
                      : "Сохранённый аудит"}
                  </small>
                </div>
              </section>
              {page === "overview" && (
                <>
                  <section className="metrics">
                    <button onClick={() => setPage("units")}>
                      <div>
                        Подразделения после
                        <GitBranch size={17} />
                      </div>
                      <strong>
                        {record.ir.units
                          .filter(
                            (u) =>
                              u.version === "after" && u.kind === "department",
                          )
                          .length.toString()
                          .padStart(2, "0")}
                      </strong>
                      <small>
                        {
                          record.unit_changes.filter(
                            (c) => c.status === "RETAINED",
                          ).length
                        }{" "}
                        сохранены ·{" "}
                        {
                          record.unit_changes.filter((c) => c.status === "NEW")
                            .length
                        }{" "}
                        добавлены
                      </small>
                    </button>
                    <button onClick={() => selectFilter("PRESERVED")}>
                      <div>
                        Сохранённые функции
                        <Check size={17} />
                      </div>
                      <strong>{count("PRESERVED")}</strong>
                      <small>Текст + ответственный + контекст</small>
                    </button>
                    <button onClick={() => selectFilter("MOVED")}>
                      <div>
                        Передача функций
                        <ArrowUpRight size={17} />
                      </div>
                      <strong>
                        {count("MOVED").toString().padStart(2, "0")}
                      </strong>
                      <small>Подтверждённые текстовые переносы</small>
                    </button>
                    <button
                      className="attention-metric"
                      onClick={() => selectFilter("REQUIRES_HUMAN_REVIEW")}
                    >
                      <div>
                        Нужна проверка
                        <CircleHelp size={17} />
                      </div>
                      <strong>{count("REQUIRES_HUMAN_REVIEW")}</strong>
                      <small>Приоритет — решение человека</small>
                    </button>
                  </section>
                  <div className="overview-grid">
                    <section className="panel">
                      <div className="panel-heading">
                        <div>
                          <span className="eyebrow">ФОКУС АУДИТОРА</span>
                          <h2>С чего начать проверку</h2>
                        </div>
                        <span className="subtle">
                          Потенциальные риски и переносы
                        </span>
                      </div>
                      {sorted
                        .filter((f) => f.type !== "PRESERVED")
                        .slice(0, 5)
                        .map(findingRow)}
                      <button
                        className="panel-footer"
                        onClick={() => setPage("functions")}
                      >
                        Все функции и выводы <ArrowRight size={16} />
                      </button>
                    </section>
                    <aside className="overview-aside">
                      <section className="principle-card">
                        <ShieldCheck size={28} />
                        <h2>
                          Вывод держится
                          <br />
                          на источнике.
                        </h2>
                        <p>
                          Для каждого вывода доступен текст «до» и
                          доказательство или результат поиска «после».
                        </p>
                        <div>
                          <Check size={14} />
                          Источники привязаны к абзацам
                        </div>
                        <div>
                          <Check size={14} />
                          Неопределённость сохранена
                        </div>
                        <div>
                          <Check size={14} />
                          Решение остаётся за аудитором
                        </div>
                      </section>
                      <section className="panel compact">
                        <div className="eyebrow">ИЗМЕНЕНИЯ СТРУКТУРЫ</div>
                        {record.unit_changes
                          .filter((c) => c.status === "NEW")
                          .map((c) => (
                            <button
                              className="new-unit"
                              key={c.id}
                              onClick={() => openSources(c.source_span_ids)}
                            >
                              <span>+</span>
                              <div>
                                {c.title}
                                <small>Новое в переданном перечне</small>
                              </div>
                              <ArrowUpRight size={15} />
                            </button>
                          ))}
                        <button
                          className="text-button"
                          onClick={() => setPage("units")}
                        >
                          Открыть структуру <ArrowRight size={14} />
                        </button>
                      </section>
                    </aside>
                  </div>
                </>
              )}
              {page === "debugger" && <OrganizationalDebugger record={record} onSources={openSources} onFinding={(id) => { const f = record.findings.find(f => f.id === id); if (f) openFinding(f); }} />}
              {page === "functions" && (
                <section className="panel">
                  <div className="filter-bar">
                    <label className="search-input">
                      <Search size={17} />
                      <input
                        placeholder="Поиск по функции, выводу или пункту…"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                      />
                    </label>
                    <label className="filter-select">
                      <ListFilter size={16} />
                      <select
                        aria-label="Тип вывода"
                        value={filter}
                        onChange={(e) => setFilter(e.target.value)}
                      >
                        <option value="ALL">Все типы</option>
                        {Object.entries(labels).map(([key, label]) => (
                          <option value={key} key={key}>
                            {label} · {count(key)}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <div className="results-meta">
                    {filtered.length} из {record.findings.length} выводов{" "}
                    <span>Нажмите строку, чтобы открыть доказательства</span>
                  </div>
                  {filtered.map(findingRow)}
                  {!filtered.length && (
                    <div className="empty-state">
                      По этому запросу выводов нет.
                    </div>
                  )}
                </section>
              )}
              {page === "matrix" && <AuditMatrix record={record} openFinding={openFinding} openSources={openSources}/>}
              {page === "units" && (
                <>
                  <div className="section-note">
                    <GitBranch size={21} />
                    <p>
                      Структурные подразделения и изменения ролей показаны
                      отдельно. Появление названия в новой версии не
                      устанавливает дату фактического создания.
                    </p>
                  </div>
                  <section className="unit-grid">
                    {record.unit_changes.map((c) => (
                      <button
                        className="panel unit-card"
                        key={c.id}
                        onClick={() => openSources(c.source_span_ids)}
                      >
                        <span
                          className={`badge ${c.status === "NEW" ? "blue" : c.status === "RETAINED" ? "green" : "amber"}`}
                        >
                          <i />
                          {c.id === "role-reorganization" ? "Изменены роли" : unitLabels[c.status]}
                        </span>
                        <h2>{c.title}</h2>
                        <p>{c.detail}</p>
                        <div className="source-link">
                          <Link2 size={14} />
                          Открыть источники <ArrowUpRight size={16} />
                        </div>
                      </button>
                    ))}
                  </section>
                </>
              )}
              {page === "conclusion" && (
                <section className="panel conclusion">
                  <div className="conclusion-heading">
                    <div>
                      <div className="eyebrow">ОБЪЯСНИМОЕ ЗАКЛЮЧЕНИЕ</div>
                      <h2>Что подтверждают документы</h2>
                    </div>
                    <a
                      className="button secondary"
                      href={`/api/audits/${record.id}/export`}
                      download
                    >
                      <ArrowDownToLine size={16} />
                      Audit JSON
                    </a>
                    <a className="button secondary" href={`/api/audits/${record.id}/report.md`} download>Заключение с решениями</a>
                  </div>
                  {record.conclusion.map((c, i) => (
                    <div className="conclusion-item" key={i}>
                      <span>{String(i + 1).padStart(2, "0")}</span>
                      <div>
                        <p>{c.text}</p>
                        <button
                          className="text-button"
                          onClick={() => openSources(c.source_span_ids)}
                        >
                          <Link2 size={13} />
                          Проверить по источникам
                        </button>
                      </div>
                    </div>
                  ))}
                  <div className="review-progress"><strong>Решения аудитора: {Object.keys(latest).length} из {record.findings.length}</strong><p>Принято: {Object.values(latest).filter(r=>r.status==="ACCEPTED").length} · Отклонено: {Object.values(latest).filter(r=>r.status==="REJECTED").length} · Нужны данные: {Object.values(latest).filter(r=>r.status==="NEEDS_INFO").length}. Это отдельный журнал; системные выводы сохраняются.</p></div>
                  <h3>Что нужно сделать аудитору</h3>
                  {(record.recommendations||[]).map((r,i)=><div className="recommendation" key={i}><span className={`badge ${r.priority==="high"?"red":"amber"}`}>{r.priority==="high"?"Приоритетно":"Проверить"}</span><p>{r.action}</p><button className="text-button" onClick={()=>{const f=record.findings.find(f=>f.id===r.finding_ids[0]);if(f)openFinding(f)}}>Открыть связанный вывод · всего {r.finding_ids.length}</button></div>)}
                  <div className="limitations">
                    <h3>Границы заключения</h3>
                    {record.limitations.map((l, i) => (
                      <p key={i}>{l}</p>
                    ))}
                  </div>
                  <div className="decision-note">
                    <ShieldCheck size={20} />
                    <p>
                      AI proposes. Evidence proves. Human decides.
                      <br />
                      <span>
                        Все выводы требуют проверки ответственным сотрудником.
                        Решения хранятся отдельно от исходного аудита.
                      </span>
                    </p>
                  </div>
                </section>
              )}
              <footer className="audit-footer">
                <span>
                  <Fingerprint size={14} />
                  {record.engine_version} · {record.id.slice(6, 18)}
                </span>
                <span>
                  {record.coverage.before_spans + record.coverage.after_spans}{" "}
                  фрагментов ·{" "}
                  {record.coverage.before_claims + record.coverage.after_claims}{" "}
                  извлечённых функций
                </span>
              </footer>
            </>
          )}
        </main>
      </div>
      {upload && (
        <Modal onClose={closeUpload} label="Новый аудит">
          <div className="modal-heading">
            <div>
              <div className="eyebrow">НОВЫЙ АУДИТ</div>
              <h2>Сравнить два комплекта</h2>
            </div>
            <button
              className="icon-button"
              aria-label="Закрыть"
              onClick={closeUpload}
            >
              <X size={20} />
            </button>
          </div>
          <p className="muted">
            Загрузите документы в порядке «до» и «после» изменений. DOCX, PDF с
            текстом или XLSX. До 8 файлов на версию, 20 МБ на файл, 40 МБ суммарно.
          </p>
          {["before", "after"].map((v, i) => (
            <div className="upload-slot" key={v}>
              <div className="upload-label">
                {i === 0 ? "01 / ДО ИЗМЕНЕНИЙ" : "02 / ПОСЛЕ ИЗМЕНЕНИЙ"}
              </div>
              <label>
                <Upload size={22} />
                <strong>{files[v]?.length ? files[v].map(f=>f.name).join(", ") : "Выбрать документы"}</strong>
                <span>Можно выбрать несколько файлов</span>
                <input
                  ref={i === 0 ? beforeFile : afterFile}
                  type="file"
                  multiple
                  aria-label={i === 0 ? "Документ до" : "Документ после"}
                  accept=".docx,.pdf,.xlsx"
                  onChange={(e) =>
                    setFiles({ ...files, [v]: Array.from(e.target.files || []) })
                  }
                />
              </label>
            </div>
          ))}
          {error && (
            <div role="alert" className="error">
              {error}
            </div>
          )}
          <button
            className="button primary full"
            disabled={busy || !files.before.length || !files.after.length}
            onClick={() => run()}
          >
            {busy ? (
              <LoaderCircle className="spin" size={17} />
            ) : (
              <ArrowRight size={17} />
            )}{" "}
            {busy
              ? "Строим модель и проверяем доказательства…"
              : "Начать анализ"}
          </button>
          <div className="demo-actions"><button className="text-button" disabled={busy} onClick={()=>run("synthetic")}>Синтетический контрольный комплект</button>{health.demo_available && <button className="text-button" disabled={busy} onClick={()=>run("original")}>Оригинальная пара 8 → 9</button>}</div>
          <p className="privacy-note">
            <ShieldCheck size={13} />
            Документы обрабатываются локально. AI по умолчанию отключён.
          </p>
        </Modal>
      )}
      {(finding || sourceIds.length > 0) && (
        <Modal onClose={closeDrawer} label="Доказательства и решение" wide>
          <div className="drawer-heading">
            <div>
              <div className="eyebrow">ЦЕПОЧКА ДОКАЗАТЕЛЬСТВ</div>
              <h2>{finding?.title || "Исходный текст документа"}</h2>
            </div>
            <button
              className="icon-button"
              onClick={closeDrawer}
              aria-label="Закрыть доказательства"
            >
              <X size={21} />
            </button>
          </div>
          {finding && (
            <div className="drawer-summary">
              <Badge type={finding.type} />
              <p>{finding.explanation}</p>
            </div>
          )}
          <div className="drawer-tabs">
            <button
              className={drawerTab === "evidence" ? "active" : ""}
              onClick={() => setDrawerTab("evidence")}
            >
              Источники <span>{selectedSpans.length}</span>
            </button>
            {finding && (
              <>
                <button
                  className={drawerTab === "search" ? "active" : ""}
                  onClick={() => setDrawerTab("search")}
                >
                  Поиск и кандидаты
                </button>
                <button
                  className={drawerTab === "investigation" ? "active" : ""}
                  onClick={() => setDrawerTab("investigation")}
                >Журнал исследования</button>
                <button
                  className={drawerTab === "decision" ? "active" : ""}
                  onClick={() => setDrawerTab("decision")}
                >
                  Решение аудитора{latest[finding.id] && <Check size={13} />}
                </button>
              </>
            )}
          </div>
          <div className="drawer-content">
            {drawerTab === "evidence" && (
              <>
                {finding && (
                  <div className="reasoning">
                    <h3>Основания</h3>
                    {finding.evidence_for.map((e, i) => (
                      <p key={i}>{e.text}</p>
                    ))}
                    {finding.evidence_against.length > 0 && (
                      <>
                        <h3>Ограничения и альтернативы</h3>
                        {finding.evidence_against.map((e, i) => (
                          <p key={i}>{e.text}</p>
                        ))}
                      </>
                    )}
                  </div>
                )}
                {["before", "after"].map((version) => (
                  <section className="evidence-version" key={version}>
                    <div className="evidence-version-label">
                      <span className={version}>
                        {version === "before" ? "ДО" : "ПОСЛЕ"}
                      </span>
                      Комплект · {record?.ir.documents.filter(d=>d.version===version).length} файл(ов)
                    </div>
                    {selectedSpans
                      .filter((s) => s.version === version)
                      .map((s) => (
                        <article
                          className={`quote ${s.version}`}
                          key={s.id}
                          id={s.id}
                        >
                          <div>
                            <strong>{record?.ir.documents.find(d=>d.id===s.document_id)?.name} · § {s.clause || "Без номера"}</strong>
                            <span>
                              {s.paragraph_id} · {s.locator}
                            </span>
                          </div>
                          <p>{s.exact_text}</p>
                          <details>
                            <summary>Контекст абзаца</summary>
                            {record?.ir.documents
                              .find((d) => d.id === s.document_id)
                              ?.spans.filter(
                                (_, idx, all) =>
                                  all[idx - 1]?.id === s.id ||
                                  all[idx + 1]?.id === s.id,
                              )
                              .map((n) => (
                                <p className="context-text" key={n.id}>
                                  <b>{n.paragraph_id}</b> {n.exact_text}
                                </p>
                              ))}
                          </details>
                        </article>
                      ))}
                    {!selectedSpans.some((s) => s.version === version) && (
                      <div className="empty-state">
                        Прямой фрагмент отсутствует. Откройте журнал поиска в
                        новой версии.
                      </div>
                    )}
                  </section>
                ))}
              </>
            )}
            {drawerTab === "search" && (
              <>
                <h3>Проверяемый поиск</h3>
                {currentSearch ? (
                  <>
                    <div className="search-report">
                      <div>
                        <span>Область поиска</span>
                        <strong>
                          {currentSearch.searched_span_ids.length} фрагментов
                          «{currentSearch.searched_version === "before" ? "до" : "после"}» · {currentSearch.searched_document_ids?.length || 1} файл(ов)
                        </strong>
                      </div>
                      <div>
                        <span>Точных совпадений</span>
                        <strong>{currentSearch.exact_match_count}</strong>
                      </div>
                      <p>{currentSearch.limitation}</p>
                    </div>
                    <h3>Кандидаты сопоставления</h3>
                    {currentSearch.candidates.map((c) => (
                      <button
                        className="candidate"
                        key={c.after_claim}
                        onClick={() => {
                          setSourceIds([
                            ...new Set([
                              ...(finding?.source_span_ids || []),
                              ...c.evidence,
                            ]),
                          ]);
                          setDrawerTab("evidence");
                        }}
                      >
                        <div>
                          <span className="badge blue">
                            {c.relation === "EXACT"
                              ? "Совпадение текста"
                              : "Лексический кандидат"}
                          </span>
                          <small>
                            Сходство {Math.round(c.confidence * 100)}%
                          </small>
                        </div>
                        <p>{claims[c.after_claim]?.text}</p>
                        <small>
                          {units[claims[c.after_claim]?.unit_id]}{" "}
                          <ArrowUpRight size={13} />
                        </small>
                      </button>
                    ))}
                    {currentSearch.candidates.length === 0 && (
                      <p>Кандидатов нет. Это не доказывает потерю функции.</p>
                    )}
                    {!!currentSearch.matched_span_ids?.length && <><h3>Найденные фрагменты корпуса</h3><p className="muted">Включая текст за пределами распознанных функций. Сходство не подтверждает эквивалентность.</p>{currentSearch.matched_span_ids.map(id=><button className="candidate" key={id} onClick={()=>{setSourceIds([...(finding?.source_span_ids||[]),id]);setDrawerTab("evidence")}}><small>{record?.ir.documents.find(d=>d.id===spans[id].document_id)?.name} · §{spans[id].clause}</small><p>{spans[id].exact_text}</p></button>)}</>}
                  </>
                ) : (
                  <p className="muted">
                    Этот вывод основан на прямом сопоставлении источников обеих
                    версий. Все фрагменты доступны на вкладке «Источники».
                  </p>
                )}
                <div className="ai-block">
                  <Sparkles size={20} />
                  <h3>AI предлагает кандидатов</h3>
                  <p>
                    Предложения не изменяют проверяемый audit record.{" "}
                    {health.ai_enabled
                      ? "По нажатию фрагменты IR будут отправлены в OpenAI."
                      : "В этой конфигурации внешний AI отключён."}
                  </p>
                  <button
                    disabled={!health.ai_enabled || saving}
                    className="button secondary"
                    onClick={getSuggestions}
                  >
                    {saving ? "Обработка…" : "Предложить пары через AI"}
                  </button>
                  {aiMessage && <p role="status">{aiMessage}</p>}
                  {aiCandidates.filter(c=>finding?.before_claim_id ? c.before_claim===finding.before_claim_id : finding?.after_claim_ids.includes(c.after_claim)).map(candidateCard)}
                </div>
              </>
            )}
            {drawerTab === "investigation" && finding && <>
              <h3>Протокол локальных проверок</h3><p className="muted">Запросы, проверенные источники и применённое правило из этого аудита. Протокол воспроизводим; это не скрытое рассуждение модели.</p>
              <ol className="investigation-log">{record?.investigations?.find(i=>i.finding_id===finding.id)?.steps.map((step,i)=><li key={i}><strong>{step.action}</strong><p>{step.detail}</p>{step.source_span_ids.length>0 && <button className="text-button" onClick={()=>{setSourceIds(step.source_span_ids);setDrawerTab("evidence")}}>Проверить {step.source_span_ids.length} фрагм.</button>}</li>)}</ol>
              <div className="ai-block"><Sparkles size={20}/><h3>Исследование с AI</h3><p>AI выбирает поисковые запросы, читает найденные функции и предлагает пары после проверки обеих версий. По нажатию выбранные фрагменты и результаты поиска передаются в OpenAI. Максимум 10 действий; системные выводы сохраняются.</p><button className="button secondary" disabled={!health.ai_enabled || saving} onClick={investigateFinding}>{saving?"AI исследует источники…":"Запустить AI-исследование"}</button>{!health.ai_enabled && <p>Внешний AI отключён. Локальные проверки выше доступны полностью.</p>}{aiMessage && <p role="status">{aiMessage}</p>}</div>
              {aiInvestigation?.finding_id===finding.id && <><h3>{aiInvestigation.cached?"Сохранённое AI-исследование":"Выполненные действия AI"}</h3><ol className="investigation-log">{aiInvestigation.steps.map(step=><li key={step.number}><strong>{{search_evidence:"Поиск доказательств",inspect_claim:"Проверка функции и владельца",propose_pair:"Предложение соответствия"}[step.tool]||"Запрос инструмента"} · {step.status==="OK"?"выполнено":"отклонено проверкой"}</strong>{typeof step.arguments.query==="string" && <p>Запрос: {step.arguments.query} · {step.arguments.version==="before"?"до":"после"}</p>}{typeof step.arguments.claim_id==="string" && <p>{claims[step.arguments.claim_id]?.text}</p>}{step.source_span_ids.length>0 && <button className="text-button" onClick={()=>{setSourceIds(step.source_span_ids);setDrawerTab("evidence")}}>Открыть использованные источники</button>}</li>)}</ol>{aiInvestigation.candidates.map(candidateCard)}{!aiInvestigation.candidates.length && <p>Проверенных предложений нет. Требуется решение аудитора.</p>}</>}
            </>}
            {drawerTab === "decision" && finding && (
              <>
                <h3>Зафиксировать решение</h3>
                <p className="muted">
                  Решение и его обоснование сохраняются в журнале. Исходный
                  вывод системы остаётся неизменным.
                </p>
                <label className="form-field">
                  Решение
                  <select
                    value={status}
                    onChange={(e) => setStatus(e.target.value)}
                  >
                    {Object.entries(reviewLabels).map(([v, l]) => (
                      <option key={v} value={v}>
                        {l}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="form-field">
                  Ответственный
                  <input
                    value={actor}
                    onChange={(e) => setActor(e.target.value)}
                    placeholder="Имя аудитора"
                    maxLength={120}
                  />
                </label>
                <label className="form-field">
                  Обоснование
                  <textarea
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="На какие источники опирается решение? Что ещё нужно уточнить?"
                    rows={4}
                    maxLength={3000}
                  />
                </label>
                <button
                  className="button primary"
                  onClick={saveReview}
                  disabled={saving || !note.trim() || !actor.trim()}
                >
                  {saving ? (
                    <LoaderCircle className="spin" size={16} />
                  ) : (
                    <Check size={16} />
                  )}
                  Сохранить решение
                </button>
                {reviewError && (
                  <p role="alert" className="error">
                    {reviewError}
                  </p>
                )}
                <div className="review-history">
                  <h3>Журнал решений</h3>
                  {reviews
                    .filter((r) => r.finding_id === finding.id)
                    .reverse()
                    .map((r) => (
                      <article key={r.id}>
                        <strong>
                          {reviewLabels[r.status]} · {r.actor}
                        </strong>
                        <small>
                          {new Date(r.created_at).toLocaleString("ru-RU")}
                        </small>
                        <p>{r.note}</p>
                      </article>
                    ))}
                  {!latest[finding.id] && (
                    <p className="muted">Решений пока нет.</p>
                  )}
                </div>
              </>
            )}
          </div>
          <div className="drawer-bottom">
            <Fingerprint size={13} />
            {finding?.rule_id || "Точный извлечённый текст"}
            <span>Evidence proves.</span>
          </div>
        </Modal>
      )}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
