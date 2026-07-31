/** Main UI: settings, pipeline controls, live log, and reports — the whole DeclaratorLM window. */
import { useState, useRef, useEffect, useLayoutEffect, useCallback, useMemo } from "react";
import { createPortal } from "react-dom";
import UsageDashboard from "./UsageDashboard";
import VisualLogPanel from "./VisualLogPanel";
import DossierPanel, { DossierProgressStrip, dossierProgressMeta } from "./DossierPanel";
import { useI18n } from "./i18n";
import {
  AboutProgramBodyEn,
  CloudHelpBodyEn,
  CloudWarningBodyEn,
  CompactModeHelpBodyEn,
  DeepResearchDownloadHintEn,
  DeepResearchExistingHintEn,
} from "./i18n/modalsEn";
import "./index.css";

/** Version shown in the header and in "About the program". */
const APP_UI_VERSION = "v0.90";

/** Header taglines (random pick on startup, if enabled in "About the program"). */
const HEADER_TAGLINES = [
  "Читай менше. Розумій більше.",
  "Менше довіри. Більше аналізу.",
  "Все правильно. Майже.",
  "Нічого підозрілого. Якщо не думати.",
  "Знову все сходиться. Дивно.",
  "Тут все правильно. І це неправильно.",
  "Структура. Аналіз. Висновки.",
  "Кожна декларація має історію.",
  "Ми не довіряємо. Ми перевіряємо.",
  "Читати це вручну? Нє, дякую.",
  "Дані відкриті. Сенс — захований.",
  "Не кожна декларація бреше. Але кожну варто перевірити.",
  "Сховатися можна. Сховати — ні.",
  "Нічого особистого. Просто аналіз.",
  "Не підкопаєшся. Якщо не копати.",
  "Виглядає чисто. Звучить дивно.",
  "Збігів не існує. Є закономірності.",
  "Все сходиться. Але не складається.",
  "Сліди залишають всі. Не всі їх бачать.",
  "Чим чистіше виглядає, тим цікавіше.",
  "Дані → висновки → питання.",
  "Автоматизуємо те, що раніше ігнорували.",
  "Кожна цифра має автора.",
  "Все сходиться… кудись не туди.",
  "Якщо стало некомфортно — значить, працює.",
  "Якщо з’явились питання — ми на правильному шляху.",
  "Хтось розраховував, що це не перевірять.",
  "Деталі мають значення.",
  "Контекст вирішує більше, ніж цифри.",
  "Все виглядає просто. Не все таким є.",
  "Дані формують контекст.",
  "Контекст формує висновки.",
  "Питання з’являються поступово.",
  "Частина відповідей лежить між рядками.",
  "Іноді важливе виглядає звичайним.",
  "Іноді достатньо поставити питання.",
  "Те, що повторюється, заслуговує уваги.",
  "Перевіряємо.",
  "Не випадково.",
  "Значення з’являється у контексті.",
  "Структура допомагає побачити більше.",
  "Те, що повторюється, формує контекст.",
  "Контекст з’єднує окремі факти.",
  "Іноді питання важливіші за відповіді.",
  "Пошук закономірностей — у промислових масштабах.",
  "Автоматизована уважність до деталей.",
  "Уважність, масштабована технологіями.",
  "Attention Is All You Need",
  "Більше контексту. Менше шуму.",
  "Більше декларацій. Менше сліпих зон.",
  "Декларації містять більше, ніж здається.",
  "Уважність — питання масштабу.",
  "Аналіз — це робота зі зв’язками.",
  "Увага до деталей масштабується.",
  "Від декларації до інтерпретації.",
  "Декларації → аналіз → контекст.",
  "Від JSON до повнішої картини.",
  "JSON на вході. Питання на виході.",
  "JSON для моделі. Контекст для людини.",
  "Декларації цифрові з 2016. Аналіз цифровим став тільки зараз.",
  "Структура даних має працювати на аналіз.",
  "JSON існував не для архіву.",
  "Дані вже структуровані. Час аналізувати структуру.",
  "Декларації стали цифровими раніше за аналіз.",
  "Дані вже структуровані. Час працювати зі зв’язками.",
  "Дані накопичувались роками. Аналіз — починається зараз.",
  "Увага більше не обмежена людиною.",
  "Деякі закономірності потребують машинної уважності.",
  "Люди сплять. Пайплайн — ні.",
  "Люди втомлюються. Декларатор - ні.",
  "Люди бачать випадки. Система бачить масиви.",
  "Масштаб більше не проблема.",
  "Декларатор не відволікається.",
  "Великі дані люблять автоматизацію.",
  "Декларатор не ставить питань. Він створює їх.",
  "Декларації читаються. Закономірності — збираються.",
  "Люди бачать документи. Система бачить поведінку.",
  "Система підтримки аналітичних рішень.",
  "Аналіз декларацій у промислових обсягах.",
  "Системний підхід до перевірки декларацій.",
  "Дані синхронізовано з реальністю.",
  "Структурований підхід до складних даних.",
  "Інструмент для системного зіставлення даних.",
  "Структуровані дані відкривають нові можливості аналізу.",
  "Інтелектуальний аналіз декларацій.",
  "Підхід, побудований навколо даних.",
  "Контекстно-орієнтований аналіз декларацій.",
  "Рішення для аналізу у промислових обсягах.",
  "Структуровані дані. Масштабований аналіз.",
  "Декларацій забагато. Людей — замало.",
];

function pickRandomHeaderTagline() {
  return HEADER_TAGLINES[Math.floor(Math.random() * HEADER_TAGLINES.length)];
}

/** Sanitizes a numeric field's raw input: empty/NaN falls back, everything else is floored and clamped to [min, max]. */
function sanitizeInt(raw, { fallback, min = -Infinity, max = Infinity }) {
  if (String(raw).trim() === "") return fallback;
  const v = Math.floor(Number(raw));
  if (!Number.isFinite(v)) return fallback;
  return Math.min(max, Math.max(min, v));
}

/** Short model name for the header (no provider, no vendor prefix before "/"). */
function formatCloudHeaderModelShort(model) {
  const m = String(model || "").trim();
  if (!m) return "(не вказано)";
  const slash = m.lastIndexOf("/");
  if (slash >= 0 && slash < m.length - 1) return m.slice(slash + 1);
  return m;
}

/** Full name for the tooltip (provider + model id). */
function formatCloudHeaderModelFull(provider, model) {
  const m = String(model || "").trim();
  const tag = provider === "openrouter" ? "openrouter" : "ollama";
  if (!m) return `${tag}: (не вказано)`;
  return `${tag}: ${m}`;
}

const PROGRESS_RE = /\[(\d+)\/(\d+)\]\s+(OK|ERR|LIMIT_EXCEEDED)\s+(.+)/;
const PIPELINE_TOTAL_RE = /^PIPELINE_TOTAL\|(\d+)\s*$/;
const PIPELINE_FOUND_RE = /found (\d+) declaration files/;
const THINK_EVENT_RE = /^THINK_EVENT\|(.*)\s*$/;
const VISUAL_LOG_RE = /^VISUAL_LOG\|(.+)$/;
const VISUAL_RUN_TOTALS_RE = /^VISUAL_RUN_TOTALS\|(.+)$/;
const PIPELINE_ERR_REVIEW_RE = /^PIPELINE_ERR_REVIEW\|(.+)$/;
const DEEP_DOWNLOAD_PROGRESS_RE = /^DEEP_DOWNLOAD_PROGRESS\|(.+)$/;
const NAZK_DOWNLOAD_PROGRESS_RE = /^NAZK_DOWNLOAD_PROGRESS\|(.+)$/;
const LOG_VIEW_MODE_KEY = "dlmLogViewMode";

function formatNazkDownloadProgress(p) {
  if (!p) return "Запит до API НАЗК…";
  const phase = String(p.phase || "");
  const target = Number(p.target) || 0;
  const saved = Number(p.saved) || 0;
  const skipped = Number(p.skipped) || 0;
  const page = Number(p.page) || 0;
  if (phase === "start") return "Підключення до API НАЗК…";
  if (phase === "list") {
    return page > 0 ? `Отримання списку (стор. ${page})…` : "Запит до API НАЗК…";
  }
  if (phase === "done") {
    let s = `Готово: збережено ${saved}`;
    if (target > 0) s += ` з ${target}`;
    if (skipped > 0) s += `, пропущено ${skipped}`;
    return s;
  }
  if (target > 0) {
    let s = `Збережено ${saved} з ${target}`;
    if (skipped > 0) s += ` · пропущено ${skipped}`;
    if (page > 0) s += ` · стор. ${page}`;
    return s;
  }
  return "Завантаження декларацій…";
}

function formatDeepDownloadProgress(p) {
  if (!p) return "Завантаження з API НАЗК…";
  const phase = String(p.phase || "");
  if (phase === "start") return "Підключення до API НАЗК…";
  const found = Number(p.found) || 0;
  const downloaded = Number(p.downloaded) || 0;
  const skipped = Number(p.skipped) || 0;
  if (phase === "done") {
    let s = `Готово: знайдено ${found}, завантажено ${downloaded}`;
    if (skipped > 0) s += `, вже на диску ${skipped}`;
    return s;
  }
  let hint = `Знайдено: ${found} · Завантажено: ${downloaded}`;
  if (skipped > 0) hint += ` · вже на диску: ${skipped}`;
  const page = Number(p.page) || 0;
  if (page > 0) hint += ` · стор. ${page}`;
  return hint;
}

function upsertVisualEntry(prev, entry) {
  const file = String(entry?.source_file || "").trim();
  const withMeta =
    entry.completedAt != null ? entry : { ...entry, completedAt: Date.now() };
  if (!file) return [...prev, withMeta].slice(-500);
  const without = prev.filter((e) => e.source_file !== file);
  return [...without, withMeta].slice(-500);
}

function upsertActiveProcessing(prev, entry) {
  const file = String(entry?.source_file || "").trim();
  if (!file) return [...prev, { ...entry, startedAt: Date.now() }];
  const kept = prev.find((e) => e.source_file === file);
  const startedAt = kept?.startedAt ?? Date.now();
  return [...prev.filter((e) => e.source_file !== file), { ...entry, startedAt }];
}

function removeActiveProcessing(prev, entry) {
  const file = String(entry?.source_file || "").trim();
  return file ? prev.filter((e) => e.source_file !== file) : prev;
}

function readLogViewMode() {
  try {
    const v = localStorage.getItem(LOG_VIEW_MODE_KEY);
    if (v === "visual" || v === "text") return v;
  } catch (_) {
    /* ignore */
  }
  return "visual";
}

/** Keeps only names that exist in the current directory listing (after move-processed, etc.). */
function pruneFileNamesToAvailable(selection, availableFiles) {
  const names = new Set(
    (availableFiles || []).map((f) => String(f?.name || "").trim()).filter(Boolean)
  );
  if (selection instanceof Set) {
    return new Set([...selection].filter((n) => names.has(n)));
  }
  return (selection || []).filter((n) => names.has(n));
}

function formatVisualLogCopy(entries) {
  return entries
    .map((e) => {
      if (e.status === "OK") {
        return `[OK] ${e.name || e.source_file} score=${e.score ?? "—"} ${e.source_file}`;
      }
      if (e.status === "ERR") {
        return `[ERR] ${e.source_file}: ${e.error || "помилка"}`;
      }
      if (e.status === "LIMIT_EXCEEDED") {
        return `[LIMIT] ${e.source_file}`;
      }
      return `[${e.status || "?"}] ${e.source_file}`;
    })
    .join("\n");
}
const SIDEBAR_TOOLTIPS = {
  inputDir: "Папка, з якої беруться декларації для обробки.",
  processedDir: "Сюди переносяться успішно оброблені JSON (крім deep research).",
  maxFiles: "Скільки файлів обробити за запуск.\n0 означає обробити всі.",
  model: "Назва локальної LLM-моделі Ollama для аналізу.",
  host: "Адреса локального Ollama API.",
  makeReport: "Створює CSV та HTML-звіти після аналізу.",
  moveProcessed: "Після успіху переносить JSON у папку оброблених.",
  noDedupe: "Залишає у звіті повторні результати тієї самої декларації (з різних запусків).",
  timeout: "Скільки секунд чекати відповідь моделі на один запит.",
  retries: "Скільки разів повторити запит, якщо сталася помилка.",
  retryDelay: "Пауза в секундах між повторними спробами.",
  maxChars: "Максимальний розмір тексту декларації, який надсилаємо в модель.",
  numPredict: "Максимальний обсяг відповіді моделі.",
  queueFolder:
    "Вручну обрати JSON-файли з папки декларацій (черга лише з них; порядок як у списку вибору).",
  queueSort:
    "Порядок обробки всіх файлів у папці: за іменем, за датою зміни або за розміром (коли не використовується ручний вибір).",
  showSystemMetrics: "Показує навантаження CPU, RAM та GPU у шапці.",
  playCompletionSound: "Програвати м'який сигнал після завершення пайплайну.",
  thinkEventDebug:
    "Показує THINK_EVENT у картках візуального логу та додає [THINK] у текстовий лог під час пайплайну.",
  pipelineMaxConcurrent:
    "Скільки декларацій одночасно обробляти через OpenRouter (1 = послідовно, до 8). Локальна Ollama та Ollama Cloud ігнорують це. Вища паралельність підвищує швидкість, але також ризик 429/лімітів API, вартість і навантаження.",
  outputJsonl: "Куди зберігати результати аналізу у форматі JSONL.",
  errorsJsonl: "Куди зберігати помилки аналізу у форматі JSONL.",
  summaryCsv: "CSV із коротким зведенням по деклараціях.",
  findingsCsv: "CSV із переліком знайдених ризиків/фактів.",
  tableHtml: "Інтерактивна HTML-таблиця з результатами аналізу.",
  compactEconomical:
    "Компактизація: лише стисла структура — менше токенів і швидший аналіз (за замовчуванням).",
  compactDetailed:
    "Компактизація: до стислої структури додаються сирі кроки JSON — повніше, але дорожче за токенами.",
  auditModeEnabled:
    "Debug-only режим: зберігає артефакти пайплайну у case-папки в каталозі аудиту.",
  auditModeDir: "Кореневий каталог для артефактів режиму аудиту.",
};

function api() {
  return window.pywebview && window.pywebview.api;
}

function isDeepResearchInput(dir) {
  const n = String(dir || "").replace(/\\/g, "/").toLowerCase();
  return n.includes("/deep_research/") || n.endsWith("/deep_research");
}

/** Whether the file/folder path is inside deep_research (stale settings left after exiting dossier mode). */
function pathUnderDeepResearch(path) {
  return isDeepResearchInput(path);
}

const NORMAL_REPORT_PATH_DEFAULTS = {
  outputJsonl: "analysis_results.jsonl",
  errorsJsonl: "analysis_errors.jsonl",
  summaryCsv: "report_summary.csv",
  findingsCsv: "report_findings.csv",
  tableHtml: "report_table.html",
};

/** An empty `{}` is truthy too — wait until pywebview calls `_createApi` and methods appear. */
function isPywebviewApiReady() {
  const a = window.pywebview && window.pywebview.api;
  return Boolean(a && typeof a.load_settings === "function");
}

/** Delay after overlay fade-out before unmounting from the DOM (≥ CSS transition 0.3s). */
const MODAL_EXIT_MS = 350;
/** Duration of tab-switch animation inside modals. */
const MODAL_TAB_SWITCH_MS = 700;
/** File picker: expanding the search panel (matched to the CSS transition). */
const FILE_PICKER_SEARCH_REVEAL_MS = 920;
/** Hide the [?] next to Run after the last tip (matched to CSS). */
const LAUNCH_HELP_FADE_MS = 1500;
/** Report-button highlight after a successful pipeline / fade after click (matched to CSS). */
const REPORT_BTN_PULSE_FADE_MS = 1500;
/** Collapse duration for `.adv-content` (matched to `--cloud-cluster-dur` in index.css). */
const ADV_PANEL_COLLAPSE_MS = 800;
/** Shift + 4 clicks on the «Д» logo: enable debug UI without restart (see unlock_debug_ui_mode). */
const LOGO_DEBUG_UNLOCK_TAPS = 4;
const LOGO_DEBUG_UNLOCK_WINDOW_MS = 2000;
const AUTOSAVE_INDICATOR_FADE_MS = 1000;
/** Fallback list when OpenRouter /models is unavailable or returns empty. */
const OPENROUTER_FALLBACK_MODELS = [
  "meta-llama/llama-3.3-70b-instruct",
  "meta-llama/llama-3.1-8b-instruct",
  "openai/gpt-4o-mini",
  "openai/gpt-4o",
  "anthropic/claude-3.5-haiku",
  "google/gemini-2.0-flash-001",
  "qwen/qwen3-32b",
];

/** Word after count n for «N declarations» (Ukrainian plural forms). */
function ukDeclWordAfterN(n) {
  const x = Math.abs(Number(n)) | 0;
  const m100 = x % 100;
  const m10 = x % 10;
  if (m100 >= 11 && m100 <= 14) return "декларацій";
  if (m10 === 1) return "декларацію";
  if (m10 >= 2 && m10 <= 4) return "декларації";
  return "декларацій";
}

/** Rough tokens-per-declaration estimate for the UI cost hint. */
function estimateOpenrouterTokensOneDeclaration(maxChars, numPredict) {
  const mc = Math.max(0, Number(maxChars) || 0);
  const np = Math.max(0, Number(numPredict) || 0);
  const inputTok = Math.ceil(mc / 4) + 4500;
  const outputTok = np > 0 ? Math.min(np, 14000) : 7000;
  return { inputTok, outputTok };
}

/** USD total for n declarations from /models per-token rates, or null. */
function estimateOpenrouterUsdForSelection(nSelected, modelId, pricingPerToken, maxChars, numPredict) {
  const n = Math.max(0, Number(nSelected) || 0);
  if (n <= 0) return null;
  const mid = String(modelId || "").trim();
  if (!mid || !pricingPerToken || typeof pricingPerToken !== "object") return null;
  const rates = pricingPerToken[mid];
  if (!rates || typeof rates !== "object") return null;
  const rpRaw = rates.prompt;
  const rcRaw = rates.completion;
  const rp =
    typeof rpRaw === "number" && Number.isFinite(rpRaw)
      ? rpRaw
      : typeof rpRaw === "string" && String(rpRaw).trim() !== ""
        ? Number(rpRaw)
        : null;
  const rc =
    typeof rcRaw === "number" && Number.isFinite(rcRaw)
      ? rcRaw
      : typeof rcRaw === "string" && String(rcRaw).trim() !== ""
        ? Number(rcRaw)
        : null;
  const rpOk = rp != null && Number.isFinite(rp) ? rp : null;
  const rcOk = rc != null && Number.isFinite(rc) ? rc : null;
  if (rpOk == null && rcOk == null) return null;
  const { inputTok, outputTok } = estimateOpenrouterTokensOneDeclaration(maxChars, numPredict);
  let per = 0;
  if (rpOk != null) per += inputTok * rpOk;
  if (rcOk != null) per += outputTok * rcOk;
  if (!(per > 0)) return null;
  return per * n;
}

/**
 * Fade-in/out for modals via CSS opacity transition.
 *
 * Mechanics:
 *  – "rendered" keeps the element in the DOM while exiting.
 *  – "active" adds class --in, which runs opacity 0→1.
 *  – While --in is absent, .cloud-modal-overlay/.cloud-help-overlay use
 *    pointer-events: none — no click blocking mid-motion.
 *  – Double-rAF ensures the first paint happens before the transition
 *    (avoids animation-fill-mode:both, which applied opacity:0 before mount).
 */
function AnimatedModalPresence({ when, children }) {
  const [rendered, setRendered] = useState(when);
  const [active, setActive] = useState(when);
  const timerRef = useRef(null);
  const rafRef = useRef(null);

  useEffect(() => {
    window.clearTimeout(timerRef.current);
    window.cancelAnimationFrame(rafRef.current);

    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (when) {
      setRendered(true);
      if (reduced) {
        setActive(true);
      } else {
        rafRef.current = window.requestAnimationFrame(() => {
          rafRef.current = window.requestAnimationFrame(() => setActive(true));
        });
      }
    } else {
      setActive(false);
      timerRef.current = window.setTimeout(
        () => setRendered(false),
        reduced ? 0 : MODAL_EXIT_MS
      );
    }

    return () => {
      window.clearTimeout(timerRef.current);
      window.cancelAnimationFrame(rafRef.current);
    };
  }, [when]);

  if (!rendered) return null;
  return (
    <div className={active ? "modal-animate-root modal-animate-root--in" : "modal-animate-root"}>
      {children}
    </div>
  );
}

/** Smooth fade/slide when switching tabs inside modals. */
function AnimatedTabPanel({ tabKey, render }) {
  const [shownTab, setShownTab] = useState(tabKey);
  const [phase, setPhase] = useState("in");

  useEffect(() => {
    if (tabKey === shownTab) return;
    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      setShownTab(tabKey);
      setPhase("in");
      return;
    }
    setPhase("out");
    const id = window.setTimeout(() => {
      setShownTab(tabKey);
      setPhase("in");
    }, MODAL_TAB_SWITCH_MS);
    return () => window.clearTimeout(id);
  }, [tabKey, shownTab]);

  return (
    <div className={`modal-tab-panel-switch modal-tab-panel-switch--${phase}`}>
      <div key={shownTab} className="modal-tab-panel-content">
        {render(shownTab)}
      </div>
    </div>
  );
}

/** Smoothly animate modal height when content actually changes. */
function useSmoothModalResize(modalRef) {
  useLayoutEffect(() => {
    const modal = modalRef.current;
    if (!modal || typeof ResizeObserver === "undefined") return;
    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) return;

    let rafId = 0;
    let timeoutId = 0;
    let animating = false;
    let prevHeight = Math.ceil(modal.getBoundingClientRect().height);

    const cleanupAfterAnimation = () => {
      modal.style.height = "";
      modal.style.overflow = "";
      animating = false;
      prevHeight = Math.ceil(modal.getBoundingClientRect().height);
    };

    const onTransitionEnd = (event) => {
      if (event.propertyName !== "height") return;
      cleanupAfterAnimation();
    };

    const observer = new ResizeObserver(() => {
      if (animating) return;
// Do not run the animation while a <select> inside the modal is open:
// in Chromium/Electron opening the dropdown changes layout and fires the observer,
// and overflow:hidden clips the popup so selection becomes impossible.
      const ae = document.activeElement;
      if (ae && ae.tagName === "SELECT" && modal.contains(ae)) return;

      const nextHeight = Math.ceil(modal.getBoundingClientRect().height);
      if (!nextHeight) return;
      if (Math.abs(nextHeight - prevHeight) < 2) {
        prevHeight = nextHeight;
        return;
      }

      window.clearTimeout(timeoutId);
      modal.removeEventListener("transitionend", onTransitionEnd);
      window.cancelAnimationFrame(rafId);

      animating = true;
      modal.style.height = `${prevHeight}px`;
// overflow:clip instead of overflow:hidden — clips content without creating a new
// block formatting context, so the native <select> popup renders correctly.
      modal.style.overflow = "clip";
      void modal.offsetHeight;
      modal.addEventListener("transitionend", onTransitionEnd, { once: true });
      rafId = window.requestAnimationFrame(() => {
        modal.style.height = `${nextHeight}px`;
      });

      // Fallback if transitionend never fires.
      timeoutId = window.setTimeout(() => {
        if (animating) cleanupAfterAnimation();
      }, MODAL_TAB_SWITCH_MS + 120);
    });

    observer.observe(modal);
    return () => {
      observer.disconnect();
      window.cancelAnimationFrame(rafId);
      window.clearTimeout(timeoutId);
      modal.removeEventListener("transitionend", onTransitionEnd);
    };
  }, [modalRef]);
}

function sortModelsAZ(list) {
  if (!Array.isArray(list)) return [];
  return [...list].sort((a, b) =>
    String(a || "").localeCompare(String(b || ""), "en", {
      sensitivity: "base",
      numeric: true,
    })
  );
}

/**
 * Tooltip rendered into `document.body` via a React portal.
 * That way it is NOT clipped by `overflow: hidden` on parent containers
 * (.sidebar, .card, etc.), which caused "tooltips not showing".
 */
function PortalTooltip({ anchorRef, tip, visible }) {
  const [pos, setPos] = useState(null);
  const bubbleRef = useRef(null);

  useLayoutEffect(() => {
    if (!visible || !anchorRef.current) {
      setPos(null);
      return undefined;
    }
    const update = () => {
      const el = anchorRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      setPos({ left: rect.left, top: rect.bottom + 8 });
    };
    update();
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [visible, anchorRef]);

  if (!visible || !pos || !tip) return null;

  // Keep the tooltip within the window horizontally.
  let left = pos.left;
  if (typeof window !== "undefined") {
    const maxLeft = window.innerWidth - 16 - 240;
    if (left > maxLeft) left = Math.max(8, maxLeft);
  }

  return createPortal(
    <span
      ref={bubbleRef}
      className="tooltip-bubble tooltip-bubble--portal"
      role="tooltip"
      style={{ left, top: pos.top }}
    >
      {tip}
    </span>,
    document.body
  );
}

function useTooltipVisibility() {
  const [visible, setVisible] = useState(false);
  const showTimerRef = useRef(null);

  const onMouseEnter = useCallback(() => {
    if (showTimerRef.current) window.clearTimeout(showTimerRef.current);
    showTimerRef.current = window.setTimeout(() => setVisible(true), 600);
  }, []);
  const onMouseLeave = useCallback(() => {
    if (showTimerRef.current) {
      window.clearTimeout(showTimerRef.current);
      showTimerRef.current = null;
    }
    setVisible(false);
  }, []);
  const onFocus = useCallback(() => setVisible(true), []);
  const onBlur = useCallback(() => setVisible(false), []);

  useEffect(
    () => () => {
      if (showTimerRef.current) window.clearTimeout(showTimerRef.current);
    },
    []
  );

  return { visible, onMouseEnter, onMouseLeave, onFocus, onBlur };
}

function LabelWithTooltip({ text, tip = "", className, as = "span" }) {
  const Tag = as;
  const anchorRef = useRef(null);
  const t = useTooltipVisibility();
  return (
    <Tag
      ref={anchorRef}
      className={`${className} tooltip-anchor`}
      tabIndex={tip ? 0 : undefined}
      onMouseEnter={tip ? t.onMouseEnter : undefined}
      onMouseLeave={tip ? t.onMouseLeave : undefined}
      onFocus={tip ? t.onFocus : undefined}
      onBlur={tip ? t.onBlur : undefined}
    >
      <span className="tooltip-text">{text}</span>
      {tip ? (
        <PortalTooltip anchorRef={anchorRef} tip={tip} visible={t.visible} />
      ) : null}
    </Tag>
  );
}

/** Portal tooltip bubble (independent of parent overflow). */
function TooltipWrap({ tip, children, className = "" }) {
  const anchorRef = useRef(null);
  const t = useTooltipVisibility();
  if (!tip) return children;
  return (
    <span
      ref={anchorRef}
      className={`tooltip-anchor${className ? ` ${className}` : ""}`}
      onMouseEnter={t.onMouseEnter}
      onMouseLeave={t.onMouseLeave}
      onFocus={t.onFocus}
      onBlur={t.onBlur}
    >
      {children}
      <PortalTooltip anchorRef={anchorRef} tip={tip} visible={t.visible} />
    </span>
  );
}

function AdvancedRequestSettingsModal({
  onDismiss,
  onConfirm,
  hasRetryTarget,
  timeout,
  setTimeout_,
  retries,
  setRetries,
  retryDelay,
  setRetryDelay,
  maxChars,
  setMaxChars,
  numPredict,
  setNumPredict,
}) {
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onDismiss();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onDismiss]);

  return (
    <div className="cloud-modal-overlay" role="presentation" onClick={onDismiss}>
      <div
        className="cloud-modal adv-settings-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="adv-request-settings-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="cloud-modal-title" id="adv-request-settings-title">
          Налаштування запитів
        </div>
        <div className="cloud-modal-body adv-settings-modal-body">
          <div className="adv-settings-form">
            <div className="adv-settings-form-row adv-settings-form-row--triple">
              <div className="adv-settings-field-cell">
                <LabelWithTooltip as="label" className="cloud-label" text="Таймаут (сек)" tip={SIDEBAR_TOOLTIPS.timeout} />
                <input className="field-input" type="number" value={timeout} onChange={(e) => setTimeout_(sanitizeInt(e.target.value, { fallback: 600, min: 1 }))} />
              </div>
              <div className="adv-settings-field-cell">
                <LabelWithTooltip as="label" className="cloud-label" text="Повторів" tip={SIDEBAR_TOOLTIPS.retries} />
                <input className="field-input" type="number" value={retries} onChange={(e) => setRetries(sanitizeInt(e.target.value, { fallback: 2, min: 0 }))} />
              </div>
              <div className="adv-settings-field-cell">
                <LabelWithTooltip as="label" className="cloud-label" text="Пауза між повт." tip={SIDEBAR_TOOLTIPS.retryDelay} />
                <input className="field-input" type="number" value={retryDelay} onChange={(e) => setRetryDelay(sanitizeInt(e.target.value, { fallback: 5, min: 0 }))} />
              </div>
            </div>
            <div className="adv-settings-form-row adv-settings-form-row--double">
              <div className="adv-settings-field-cell">
                <LabelWithTooltip as="label" className="cloud-label" text="Макс. розмір запиту" tip={SIDEBAR_TOOLTIPS.maxChars} />
                <input className="field-input" type="number" value={maxChars} onChange={(e) => setMaxChars(sanitizeInt(e.target.value, { fallback: 64000, min: 1 }))} />
              </div>
              <div className="adv-settings-field-cell">
                <LabelWithTooltip as="label" className="cloud-label" text="Макс. обсяг відповіді" tip={SIDEBAR_TOOLTIPS.numPredict} />
                <input className="field-input" type="number" value={numPredict} onChange={(e) => setNumPredict(sanitizeInt(e.target.value, { fallback: 16000 }))} />
              </div>
            </div>
          </div>
        </div>
        <div className="cloud-modal-actions">
          <button type="button" className="btn-secondary" onClick={onDismiss}>
            Скасувати
          </button>
          <button type="button" className="btn-primary" onClick={onConfirm}>
            {hasRetryTarget ? "Застосувати й повторити" : "Готово"}
          </button>
        </div>
      </div>
    </div>
  );
}

function AdvancedOutputFilesModal({
  onClose,
  outputJsonl,
  setOutputJsonl,
  errorsJsonl,
  setErrorsJsonl,
  summaryCsv,
  setSummaryCsv,
  findingsCsv,
  setFindingsCsv,
  tableHtml,
  setTableHtml,
  onPickFile,
}) {
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="cloud-modal-overlay" role="presentation" onClick={onClose}>
      <div
        className="cloud-modal adv-settings-modal adv-settings-modal--wide"
        role="dialog"
        aria-modal="true"
        aria-labelledby="adv-output-files-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="cloud-modal-title" id="adv-output-files-title">
          Файли виводу
        </div>
        <div className="cloud-modal-body adv-settings-modal-body">
          <FilePathInput
            label="Результати (JSONL)"
            tooltip={SIDEBAR_TOOLTIPS.outputJsonl}
            value={outputJsonl}
            onChange={setOutputJsonl}
            onBrowse={() => onPickFile(setOutputJsonl)}
          />
          <FilePathInput
            label="Помилки (JSONL)"
            tooltip={SIDEBAR_TOOLTIPS.errorsJsonl}
            value={errorsJsonl}
            onChange={setErrorsJsonl}
            onBrowse={() => onPickFile(setErrorsJsonl)}
          />
          <FilePathInput
            label="Summary (CSV)"
            tooltip={SIDEBAR_TOOLTIPS.summaryCsv}
            value={summaryCsv}
            onChange={setSummaryCsv}
            onBrowse={() => onPickFile(setSummaryCsv)}
          />
          <FilePathInput
            label="Findings (CSV)"
            tooltip={SIDEBAR_TOOLTIPS.findingsCsv}
            value={findingsCsv}
            onChange={setFindingsCsv}
            onBrowse={() => onPickFile(setFindingsCsv)}
          />
          <FilePathInput
            label="Таблиця (HTML)"
            tooltip={SIDEBAR_TOOLTIPS.tableHtml}
            value={tableHtml}
            onChange={setTableHtml}
            onBrowse={() => onPickFile(setTableHtml)}
          />
        </div>
        <div className="cloud-modal-actions">
          <button type="button" className="btn-primary" onClick={onClose}>
            Готово
          </button>
        </div>
      </div>
    </div>
  );
}

function CompactModeHelpModal({ onClose }) {
  const { locale } = useI18n();
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="cloud-modal-overlay" role="presentation" onClick={onClose}>
      <div
        className="cloud-modal compact-mode-help-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="compact-mode-help-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="cloud-modal-title" id="compact-mode-help-title">
          Режим компактизації
        </div>
        <div className="cloud-modal-body about-program-body compact-mode-help-body">
          {locale === "en" ? (
            <CompactModeHelpBodyEn />
          ) : (
            <>
          <p className="about-program-lead">
            Декларація з реєстру НАЗК — це великий і «шумний» JSON: десятки технічних полів,
            службові коди, дублі та порожні розділи. Передавати його моделі цілком — дорого,
            повільно й часто гірше за якістю.
          </p>

          <h3 className="compact-mode-help-h3">Що таке компактизація</h3>
          <p>
            Перед аналізом програма проганяє декларацію через <strong>компактизацію</strong> —
            перетворює сирий JSON на стислу, впорядковану структуру, зрозумілу і людині, і моделі.
            На цьому етапі програма:
          </p>
          <ul className="welcome-help-list">
            <li>залишає лише змістовні розділи: профіль, доходи, нерухомість, транспорт, готівку, корпоративні права, сім’ю, зобов’язання, суттєві зміни;</li>
            <li>рахує підсумки (загальний дохід, готівка, вартість авто/нерухомості) і складає їх у блок <code className="deep-research-code">quick_totals</code>;</li>
            <li>розшифровує коди: тип і період декларації, зв’язки власників майна, членів сім’ї, банківські установи;</li>
            <li>прибирає порожні кроки, технічне «сміття» та конфіденційні заглушки.</li>
          </ul>
          <p>
            Результат — компактний JSON, який і надсилається моделі як вхідні дані для пошуку
            ризиків.             Перемикач у розширених налаштуваннях керує тим, <strong>скільки сирих даних</strong>{" "}
            додавати до цієї стислої структури.
          </p>

          <h3 className="compact-mode-help-h3">
            <span className="compact-mode-help-dot compact-mode-help-dot--green" aria-hidden /> Економніше
            <span className="compact-mode-help-tag">за замовчуванням</span>
          </h3>
          <p>
            Надсилає лише <strong>компактну структуру</strong> + банківські установи. Рідкісні
            нестандартні кроки додаються коротко (без повної сирої копії).
          </p>
          <ul className="welcome-help-list">
            <li>Найменший запит → найшвидше та найдешевше за токенами.</li>
            <li>Достатньо для типових щорічних декларацій.</li>
            <li>Оптимально для масової обробки десятків файлів поспіль.</li>
          </ul>

          <h3 className="compact-mode-help-h3">
            <span className="compact-mode-help-dot compact-mode-help-dot--blue" aria-hidden /> Детальніше
          </h3>
          <p>
            До компактної структури <strong>додається повна сира копія</strong> всіх заповнених
            кроків декларації — так, як вони є в оригінальному JSON реєстру.
          </p>
          <ul className="welcome-help-list">
            <li>Модель бачить усі поля та оригінальні формулювання, нічого не «згублено» при стисканні.</li>
            <li>Корисно для складних років, декларацій змін і рідкісних кроків, де важливі деталі.</li>
            <li>Запит у кілька разів більший → аналіз триває довше й коштує дорожче.</li>
          </ul>

          <p className="compact-mode-help-tip">
            <strong>Порада.</strong> Починайте з <strong>Економніше</strong>. Якщо звіт виходить
            порожнім, поверхневим або модель «не побачила» якийсь актив — увімкніть{" "}
            <strong>Детальніше</strong> й перезапустіть аналіз цієї декларації.
          </p>
            </>
          )}
        </div>
        <div className="cloud-modal-actions">
          <button type="button" className="btn-primary" onClick={onClose}>
            Зрозуміло
          </button>
        </div>
      </div>
    </div>
  );
}

/** Segmented Local / Cloud switch with an animated pill. */
function ModeSegmentToggle({ cloudMode, onLocal, onCloud }) {
  return (
    <div
      className="mode-segment"
      role="group"
      aria-label="Режим підключення до Ollama"
    >
      <div className={`mode-segment__track ${cloudMode ? "is-cloud" : "is-local"}`}>
        <span className="mode-segment__pill" aria-hidden />
        <button
          type="button"
          className={`mode-segment__btn ${!cloudMode ? "is-active" : ""}`}
          aria-pressed={!cloudMode}
          onClick={onLocal}
        >
          Local
        </button>
        <button
          type="button"
          className={`mode-segment__btn ${cloudMode ? "is-active" : ""}`}
          aria-pressed={cloudMode}
          onClick={onCloud}
        >
          Cloud
        </button>
      </div>
    </div>
  );
}

function FolderInput({ label, tooltip, value, onChange, onBrowse }) {
  return (
    <div className="field-row">
      <LabelWithTooltip as="label" className="field-label" text={label} tip={tooltip} />
      <div className="field-input-group">
        <input
          className="field-input field-input--folder-path"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
        <button className="btn-browse" onClick={onBrowse}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
          </svg>
        </button>
      </div>
    </div>
  );
}

function FilePathInput({ label, tooltip, value, onChange, onBrowse, disabled = false }) {
  return (
    <div className={`file-path-row${disabled ? " file-path-row--disabled" : ""}`}>
      <LabelWithTooltip as="label" className="file-path-label" text={label} tip={tooltip} />
      <div className="field-input-group">
        <input
          className="field-input"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
        />
        <TooltipWrap tip="Обрати папку">
          <button className="btn-browse" type="button" onClick={onBrowse} disabled={disabled}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
            </svg>
          </button>
        </TooltipWrap>
      </div>
    </div>
  );
}

export function Toggle({ label, tooltip, checked, onChange, disabled = false, compact = false, className = "" }) {
  return (
    <label
      className={`toggle-row${disabled ? " toggle-row--disabled" : ""}${compact ? " toggle-row--compact" : ""}${className ? ` ${className}` : ""}`}
      aria-disabled={disabled}
    >
      <span
        className={`toggle-switch ${checked ? "on" : ""}`}
        role="switch"
        aria-checked={checked}
        onClick={() => {
          if (!disabled) onChange(!checked);
        }}
      >
        <span className="toggle-thumb" />
      </span>
      <LabelWithTooltip className="toggle-label" text={label} tip={tooltip} />
    </label>
  );
}

function LogLine({ line }) {
  let cls = "log-line";
  if (line.startsWith("[THINK]")) cls += " log-info";
  else if (line.includes("[DEEP]")) cls += " log-deep";
  else if (line.includes("[OK]") || line.includes("Готово") || line.includes("успішно")) cls += " log-ok";
  else if (line.includes("[ПОМИЛКА]") || line.includes("ERR")) cls += " log-err";
  else if (line.includes("[INFO]") || line.includes("===")) cls += " log-info";
  else if (line.includes("exit=")) cls += " log-warn";
  return <div className={cls}>{line}</div>;
}

function fmtNumber(v, suffix = "") {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  return `${Math.round(Number(v))}${suffix}`;
}

function formatDurationClock(totalSec) {
  const s = Math.max(0, Math.floor(Number(totalSec) || 0));
  const mm = Math.floor(s / 60);
  const ss = s % 60;
  if (mm <= 0) return `${ss} с`;
  return `${mm}:${String(ss).padStart(2, "0")}`;
}

function MetricMiniBar({ label, value, max = 100, text }) {
  const safe = value === null || value === undefined ? null : Number(value);
  const pct = safe === null || Number.isNaN(safe) ? 0 : Math.max(0, Math.min(100, (safe / max) * 100));
  return (
    <div className="metric-mini">
      <div className="metric-mini-top">
        <span className="metric-mini-label">{label}</span>
        <span className="metric-mini-value">{text}</span>
      </div>
      <div className="metric-mini-track">
        <div className="metric-mini-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function SlidingLabelText({ text, direction = "ltr" }) {
  const [current, setCurrent] = useState(text);
  const [outgoing, setOutgoing] = useState(null);
  const [animClass, setAnimClass] = useState("");
  const clearTimerRef = useRef(null);

  useEffect(() => {
    if (text === current) return;
    setOutgoing(current);
    setCurrent(text);
    setAnimClass(direction === "rtl" ? "slide-rtl" : "slide-ltr");
    if (clearTimerRef.current) {
      window.clearTimeout(clearTimerRef.current);
      clearTimerRef.current = null;
    }
    clearTimerRef.current = window.setTimeout(() => {
      setOutgoing(null);
      setAnimClass("");
      clearTimerRef.current = null;
    }, 700);
  }, [text, direction, current]);

  useEffect(() => () => {
    if (clearTimerRef.current) {
      window.clearTimeout(clearTimerRef.current);
      clearTimerRef.current = null;
    }
  }, []);

  return (
    <span className="sliding-label-text">
      <span className={`sliding-label-text-item is-static ${animClass}`}>{current}</span>
      {outgoing ? (
        <span className={`sliding-label-text-item is-ghost ${animClass}`}>{outgoing}</span>
      ) : null}
    </span>
  );
}

function CloudSettingsModal({
  value,
  onChange,
  onCancel,
  onSave,
  onOpenComparison,
  debugMode = false,
  ollamaModels,
  openrouterModels,
  openrouterPricing = null,
  openrouterCreditsLoading = false,
  openrouterCreditsLabel = "",
  openrouterCreditsHint = "",
  onRefreshOpenrouterCredits,
  onReloadOllamaModels,
  onReloadOpenrouterModels,
  modelListError = "",
  pipelineMaxConcurrent = 1,
  onPipelineMaxConcurrentChange,
}) {
  const { locale } = useI18n();
  const [error, setError] = useState("");
  const [testState, setTestState] = useState({ loading: false, ok: null, message: "" });
  const [cloudHelpOpen, setCloudHelpOpen] = useState(false);
  const modalRef = useRef(null);
  useSmoothModalResize(modalRef);

  // Safe reads of nested blocks (legacy settings shape).
  const provider = value?.provider === "openrouter" ? "openrouter" : "ollama";
  const ollama = value?.ollama || { host: "", model: "", api_key: "" };
  const openrouter = value?.openrouter || { host: "", model: "", api_key: "" };
  const prevProviderRef = useRef(provider);
  const [textSlideDir, setTextSlideDir] = useState("ltr");

  useEffect(() => {
    if (prevProviderRef.current === provider) return;
    setTextSlideDir(provider === "openrouter" ? "ltr" : "rtl");
    prevProviderRef.current = provider;
  }, [provider]);

  const updateOllama = (patch) =>
    onChange({ ...value, provider, ollama: { ...ollama, ...patch }, openrouter });
  const updateOpenrouter = (patch) =>
    onChange({ ...value, provider, ollama, openrouter: { ...openrouter, ...patch } });
  const setProvider = (next) => {
    if (next === provider) return;
    setError("");
    onChange({ ...value, provider: next, ollama, openrouter });
  };

  useEffect(() => {
    if (!cloudHelpOpen) return;
    const onKey = (e) => {
      if (e.key === "Escape") setCloudHelpOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cloudHelpOpen]);

  const handleSave = () => {
    if (provider === "openrouter") {
      const host = (openrouter.host || "").trim();
      const model = (openrouter.model || "").trim();
      const key = (openrouter.api_key || "").trim();
      if (!host) return setError("Вкажіть OpenRouter host.");
      if (!model) return setError("Вкажіть OpenRouter model.");
      if (!key) return setError("Вкажіть OpenRouter API key (sk-or-v1-...).");
      if (!/^https?:\/\//i.test(host)) {
        return setError("OpenRouter host має починатися з http:// або https://");
      }
      setError("");
      onSave();
      return;
    }
    const host = (ollama.host || "").trim();
    const model = (ollama.model || "").trim();
    const key = (ollama.api_key || "").trim();
    if (!host) return setError("Вкажіть Cloud host.");
    if (!model) return setError("Вкажіть Cloud model.");
    if (!key) return setError("Вкажіть API key.");
    if (!/^https?:\/\//i.test(host)) {
      return setError("Cloud host має починатися з http:// або https://");
    }
    setError("");
    onSave();
  };

  const activeValues = provider === "openrouter" ? openrouter : ollama;
  const setActiveValues = provider === "openrouter" ? updateOpenrouter : updateOllama;
  const activeModels = (() => {
    const raw =
      provider === "openrouter"
        ? [...(openrouterModels || []), ...OPENROUTER_FALLBACK_MODELS]
        : (ollamaModels || []);
    // Dedupe while keeping values stable (all model ids are strings).
    const unique = Array.from(
      new Set(
        raw
          .filter((m) => m !== null && m !== undefined)
          .map((m) => String(m))
          .filter((m) => m.trim())
      )
    );
    return sortModelsAZ(unique);
  })();
  const reloadModels = provider === "openrouter" ? onReloadOpenrouterModels : onReloadOllamaModels;
  const hostLabel = provider === "openrouter" ? "OpenRouter host" : "Cloud host";
  const modelLabel = provider === "openrouter" ? "OpenRouter model" : "Cloud model";
  const keyLabel = provider === "openrouter" ? "OpenRouter API key" : "API key";
  const hostPlaceholder =
    provider === "openrouter" ? "https://openrouter.ai/api/v1" : "https://ollama.com";
  const modelPlaceholder =
    provider === "openrouter" ? "meta-llama/llama-3.3-70b-instruct" : "gpt-oss:120b-cloud";
  const keyPlaceholder = provider === "openrouter" ? "sk-or-v1-..." : "sk-...";
  const reloadTip =
    provider === "openrouter"
      ? "Оновити список OpenRouter-моделей"
      : "Оновити список cloud-моделей";
  const saveText =
    "Зберегти і увімкнути";

  // NOTE: we intentionally don't use <datalist> here.
  // Native datalist dropdown is not reliably constrained by modal bounds and often doesn't scroll.
  const [modelQuery, setModelQuery] = useState("");
  const [modelOpen, setModelOpen] = useState(false);
  const modelComboboxRef = useRef(null);

  useEffect(() => {
    setModelOpen(false);
    setModelQuery("");
  }, [provider]);

  useEffect(() => {
    if (!modelOpen) return;
    const onDocMouseDown = (e) => {
      const el = modelComboboxRef.current;
      if (!el) return;
      // Close only when the click is outside the combobox.
      if (e.target instanceof Node && !el.contains(e.target)) {
        setModelOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [modelOpen]);

  const normalizedModelQuery = String(modelQuery || "").trim().toLowerCase();
  const filteredModels = (activeModels || []).filter((m) => {
    const mm = String(m || "");
    if (!normalizedModelQuery) return true;
    return mm.toLowerCase().includes(normalizedModelQuery);
  });

  const selectModel = (m) => {
    setActiveValues({ model: m });
    setModelQuery(m);
    setModelOpen(false);
  };

  const handleTestConnection = async () => {
    if (!api()) return;
    const isOpenrouter = provider === "openrouter";
    const host = String(isOpenrouter ? (openrouter.host || "") : (ollama.host || "")).trim();
    const key = String(openrouter.api_key || "").trim();
    const model = String(isOpenrouter ? (openrouter.model || "") : (ollama.model || "")).trim();
    if (!host) {
      setTestState({
        loading: false,
        ok: false,
        message: `Для тесту вкажіть ${isOpenrouter ? "OpenRouter host" : "Ollama host"}.`,
      });
      return;
    }
    if (isOpenrouter && !key) {
      setTestState({
        loading: false,
        ok: false,
        message: "Для тесту вкажіть OpenRouter API key.",
      });
      return;
    }
    setTestState({ loading: true, ok: null, message: "Перевірка підключення..." });
    try {
      const bridge = api();
      const methodName = isOpenrouter ? "test_openrouter_connection" : "test_ollama_connection";
      if (typeof bridge[methodName] !== "function") {
        setTestState({
          loading: false,
          ok: false,
          message: `Метод ${methodName} недоступний. Перезапустіть app.`,
        });
        return;
      }
      const raw = isOpenrouter
        ? await bridge.test_openrouter_connection(host, key, model)
        : await bridge.test_ollama_connection(host, model);
      const res = typeof raw === "string" ? JSON.parse(raw) : raw;
      const ok = Boolean(res?.ok);
      setTestState({
        loading: false,
        ok,
        message: String(res?.message || (ok ? "OK" : "Помилка перевірки")),
      });
    } catch (e) {
      setTestState({
        loading: false,
        ok: false,
        message: `Помилка тесту: ${String(e)}`,
      });
    }
  };

  return (
    <div className="cloud-modals-stack">
    <div className="cloud-modal-overlay">
      <div ref={modalRef} className="cloud-modal cloud-modal--smooth-size">
        <div className="cloud-modal-title">Налаштування Cloud режиму</div>
        <div
          className="deep-research-tabs cloud-provider-tabs"
          role="tablist"
          aria-label="Cloud провайдер"
          style={{ "--active-tab-index": provider === "ollama" ? 0 : 1, "--tabs-count": 2 }}
        >
          <button
            type="button"
            role="tab"
            className={`deep-research-tab${provider === "ollama" ? " deep-research-tab--active" : ""}`}
            aria-selected={provider === "ollama"}
            onClick={() => setProvider("ollama")}
          >
            Ollama
          </button>
          <button
            type="button"
            role="tab"
            className={`deep-research-tab${provider === "openrouter" ? " deep-research-tab--active" : ""}`}
            aria-selected={provider === "openrouter"}
            onClick={() => setProvider("openrouter")}
          >
            OpenRouter
          </button>
        </div>
        <div className="cloud-modal-body">
          <label className="cloud-label">
            <SlidingLabelText text={hostLabel} direction={textSlideDir} />
          </label>
          <input
            className="field-input"
            value={activeValues.host || ""}
            onChange={(e) => setActiveValues({ host: e.target.value })}
            placeholder={hostPlaceholder}
          />
          <label className="cloud-label">
            <SlidingLabelText text={modelLabel} direction={textSlideDir} />
          </label>
          <div className="field-input-group">
            <div className="model-combobox-root" ref={modelComboboxRef}>
              <input
                className="field-input model-combobox-input"
                value={activeValues.model || ""}
                onChange={(e) => {
                  const val = e.target.value;
                  setActiveValues({ model: val });
                  setModelQuery(val);
                  setModelOpen(true);
                }}
                onFocus={() => {
                  setModelOpen(true);
                  setModelQuery(activeValues.model || "");
                }}
                placeholder={modelPlaceholder}
              />
              {modelOpen && (
                <div className="model-combobox-dropdown" role="listbox" aria-label="Список моделей">
                  {(filteredModels || []).slice(0, 200).map((m) => {
                    const priceLine =
                      provider === "openrouter" && openrouterPricing && typeof openrouterPricing === "object"
                        ? String(openrouterPricing[m] || "").trim()
                        : "";
                    return (
                    <button
                      key={m}
                      type="button"
                      className="model-combobox-option"
                      title={priceLine ? `${m}\n${priceLine}` : m}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => selectModel(m)}
                    >
                      <span className="model-combobox-option-main">{m}</span>
                      {priceLine ? (
                        <span className="model-combobox-option-meta">{priceLine}</span>
                      ) : null}
                    </button>
                    );
                  })}
                  {filteredModels.length === 0 ? (
                    <div className="model-combobox-empty">Немає моделей для цього запиту</div>
                  ) : null}
                </div>
              )}
            </div>
            <TooltipWrap tip={reloadTip}>
              <button
                type="button"
                className="btn-browse"
                onClick={reloadModels}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/>
                  <path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/>
                </svg>
              </button>
            </TooltipWrap>
          </div>
          <label className="cloud-label">
            <SlidingLabelText text={keyLabel} direction={textSlideDir} />
          </label>
          <input
            className="field-input"
            type="password"
            value={activeValues.api_key || ""}
            onChange={(e) => setActiveValues({ api_key: e.target.value })}
            placeholder={keyPlaceholder}
          />
          {provider === "openrouter" ? (
            <div className="cloud-openrouter-meta-row">
              <div className="cloud-modal-openrouter-balance" title={openrouterCreditsHint || undefined}>
                <span className="cloud-modal-openrouter-balance-label">
                  {openrouterCreditsLoading
                    ? "Баланс: …"
                    : openrouterCreditsLabel
                      ? `Баланс: ${openrouterCreditsLabel}`
                      : openrouterCreditsHint
                        ? "Баланс: —"
                        : "Баланс: (введіть ключ)"}
                </span>
                {openrouterCreditsHint && !openrouterCreditsLabel ? (
                  <span className="cloud-modal-openrouter-balance-hint">{openrouterCreditsHint}</span>
                ) : null}
                <TooltipWrap tip="Оновити баланс OpenRouter (/credits)">
                  <button
                    type="button"
                    className="btn-browse cloud-modal-balance-refresh"
                    aria-label="Оновити баланс OpenRouter"
                    disabled={
                      openrouterCreditsLoading
                      || !String(activeValues.api_key || "").trim()
                      || typeof onRefreshOpenrouterCredits !== "function"
                    }
                    onClick={() => {
                      if (typeof onRefreshOpenrouterCredits === "function") {
                        onRefreshOpenrouterCredits(activeValues.host || "", activeValues.api_key || "");
                      }
                    }}
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/>
                      <path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/>
                    </svg>
                  </button>
                </TooltipWrap>
              </div>
              <div className="cloud-openrouter-parallel-group">
                <LabelWithTooltip
                  as="label"
                  className="cloud-label cloud-label--inline"
                  text="Паралель:"
                  tip={SIDEBAR_TOOLTIPS.pipelineMaxConcurrent}
                />
                <input
                  className="field-input field-input--short cloud-parallel-input"
                  type="number"
                  min={1}
                  max={8}
                  step={1}
                  value={pipelineMaxConcurrent}
                  onChange={(e) => {
                    const v = Math.floor(Number(e.target.value));
                    if (typeof onPipelineMaxConcurrentChange === "function") {
                      onPipelineMaxConcurrentChange(
                        Number.isFinite(v) ? Math.min(8, Math.max(1, v)) : 1
                      );
                    }
                  }}
                />
              </div>
            </div>
          ) : null}
          {(error || modelListError) && <div className="cloud-error">{error || modelListError}</div>}
        </div>
        <div className="cloud-modal-footer-bar">
          <div className="cloud-modal-footer-buttons-row">
          <button type="button" className="btn-secondary cloud-modal-footer-cancel" onClick={onCancel}>
            Скасувати
          </button>
          <div className="cloud-modal-footer-spacer" aria-hidden />
          <div className="cloud-modal-footer-actions">
            {debugMode && typeof onOpenComparison === "function" && (
              <button
                type="button"
                className="btn-secondary cloud-test-btn"
                onClick={() => {
                  if (typeof onOpenComparison === "function") {
                    onOpenComparison({
                      provider,
                      host: activeValues.host || "",
                      api_key: activeValues.api_key || "",
                      table_html: "",
                    });
                  }
                }}
                disabled={testState.loading}
              >
                Порівняння
              </button>
            )}
            {debugMode && (
              <TooltipWrap tip="Перевірити з'єднання">
                <button
                  type="button"
                  className={`btn-cloud-test-connection${testState.loading ? " btn-cloud-test-connection--loading" : ""}`}
                  aria-label="Перевірити з'єднання"
                  onClick={handleTestConnection}
                  disabled={testState.loading}
                >
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    aria-hidden
                  >
                    <circle cx="12" cy="12" r="10" />
                    <path d="M2 12h20" />
                    <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
                  </svg>
                </button>
              </TooltipWrap>
            )}
            <TooltipWrap tip="Як налаштувати Cloud режим">
              <button
                type="button"
                className="btn-cloud-help"
                aria-label="Довідка: як налаштувати Cloud режим"
                onClick={() => setCloudHelpOpen(true)}
              >
                ?
              </button>
            </TooltipWrap>
            <button type="button" className="btn-primary" onClick={handleSave}>
              <SlidingLabelText text={saveText} direction={textSlideDir} />
            </button>
          </div>
          </div>
        </div>
        {debugMode && testState.message ? (
          <div className={`cloud-test-status cloud-test-status--footer ${testState.ok === true ? "ok" : testState.ok === false ? "err" : ""}`}>
            {testState.message}
          </div>
        ) : null}
      </div>
    </div>
    <AnimatedModalPresence when={cloudHelpOpen}>
      <div
        className="cloud-help-overlay"
        role="presentation"
        onClick={() => setCloudHelpOpen(false)}
      >
        <div
          className="cloud-help-dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="cloud-help-heading"
          onClick={(e) => e.stopPropagation()}
        >
          <h2 id="cloud-help-heading" className="cloud-help-title">
            Як налаштувати Cloud режим
          </h2>
          <div className="cloud-help-body">
            {locale === "en" ? (
              <CloudHelpBodyEn />
            ) : (
              <>
            <h3 className="cloud-help-subtitle">Що це взагалі таке?</h3>
            <p>
              У програми є два режими роботи. <strong>Local</strong> — модель працює прямо на вашому комп&apos;ютері
              (потрібен потужний ПК). <strong>Cloud</strong> — модель працює на чужому сервері в інтернеті, а ваш
              комп&apos;ютер просто надсилає запити. Це зручно, якщо ваш ПК слабкий або ви не хочете нічого
              встановлювати локально.
            </p>

            <h3 className="cloud-help-subtitle">Покрокова інструкція: отримати безкоштовний API ключ</h3>
            <ol className="cloud-help-steps">
              <li>
                Зайдіть на сайт{" "}
                <a href="https://ollama.com" target="_blank" rel="noopener noreferrer">
                  ollama.com
                </a>{" "}
                і зареєструйтесь (кнопка Sign Up). Достатньо увійти через Google, або ввести пошту та пароль.
              </li>
              <li>
                Після входу перейдіть у розділ Settings (налаштування профілю, зазвичай у правому верхньому куті).
              </li>
              <li>
                Знайдіть розділ Keys/API Keys і натисніть &quot;Create new key&quot; (Створити новий ключ). Скопіюйте
                його — це довгий рядок символів, схожий на sk-abc123.... Збережіть його в надійному місці, бо вдруге
                він не покажеться повністю.
              </li>
              <li>Поверніться до програми ДекларраторLM і натисніть кнопку Cloud у верхній панелі.</li>
              <li>
                У вікні що з&apos;явилось заповніть три поля:
                <ul className="cloud-help-fields">
                  <li>
                    <strong>Cloud host</strong> — залиште як є: https://ollama.com
                  </li>
                  <li>
                    <strong>Cloud model</strong> — оберіть або залиште модель (наприклад kimi-k2.5)
                  </li>
                  <li>
                    <strong>API key</strong> — вставте сюди ключ, який скопіювали на кроці 3
                  </li>
                </ul>
              </li>
            </ol>
            <p>
              Натисніть &quot;Зберегти і увімкнути Cloud&quot;. Готово!
            </p>

            <h3 className="cloud-help-subtitle">Чи коштує це грошей?</h3>
            <p>
              Ollama надає певну кількість безкоштовних запитів. Для обробки декларацій у помірній кількості цього
              зазвичай достатньо.
            </p>

            <h3 className="cloud-help-subtitle">Альтернатива: OpenRouter</h3>
            <p>
              У вкладці <strong>OpenRouter</strong> налаштовується окремий, незалежний від Ollama шлях.{" "}
              OpenRouter надає доступ до сотень моделей (Llama, Claude, Gemini, GPT, Qwen тощо) через один API key —
              переключатися між Ollama і OpenRouter можна сегментованим перемикачем угорі цього вікна,
              дані обох вкладок зберігаються окремо.
            </p>
            <ol className="cloud-help-steps">
              <li>
                Зайдіть на сайт{" "}
                <a href="https://openrouter.ai" target="_blank" rel="noopener noreferrer">
                  openrouter.ai
                </a>{" "}
                і зареєструйтесь.
              </li>
              <li>
                У розділі{" "}
                <a href="https://openrouter.ai/settings/keys" target="_blank" rel="noopener noreferrer">
                  Settings → Keys
                </a>{" "}
                натисніть &quot;Create Key&quot; і скопіюйте отриманий ключ
                (починається з <code>sk-or-v1-</code>).
              </li>
              <li>
                У вкладці <strong>OpenRouter</strong> цього вікна заповніть три поля:
                <ul className="cloud-help-fields">
                  <li>
                    <strong>OpenRouter host</strong> — залиште як є: https://openrouter.ai/api/v1
                  </li>
                  <li>
                    <strong>OpenRouter model</strong> — оберіть модель (наприклад meta-llama/llama-3.3-70b-instruct)
                  </li>
                  <li>
                    <strong>OpenRouter API key</strong> — вставте сюди ключ <code>sk-or-v1-...</code>
                  </li>
                </ul>
              </li>
            </ol>
              </>
            )}
          </div>
          <div className="cloud-help-footer">
            <button type="button" className="btn-primary" onClick={() => setCloudHelpOpen(false)}>
              Зрозуміло
            </button>
          </div>
        </div>
      </div>
    </AnimatedModalPresence>
    </div>
  );
}

function AboutProgramModal({ onClose, onOpenWelcome, showHeaderTaglines, onShowHeaderTaglinesChange }) {
  const { locale } = useI18n();
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="cloud-modal-overlay" role="presentation" onClick={onClose}>
      <div
        className="cloud-modal about-program-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="about-program-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="cloud-modal-title" id="about-program-title">
          Про ДеклараторLM
        </div>
        <div className="cloud-modal-body about-program-body">
          {locale === "en" ? (
            <AboutProgramBodyEn version={APP_UI_VERSION} />
          ) : (
            <>
          <p className="about-program-lead">
            <strong>DeclaratorLM</strong>
            {" "}
            — це інструмент для автоматичного аналізу електронних декларацій.
          </p>
          <p>
            Програма завантажує <code className="deep-research-code">JSON</code>-декларації, стискає їх у зрозумілий формат і використовує{" "}
            <strong>штучний інтелект</strong>
            {" "}
            для пошуку{" "}
            <strong>ризиків, аномалій та підозрілих зв’язків</strong>.
          </p>
          <p>
            Результат подається у вигляді структурованих звітів (
            <code className="deep-research-code">JSON</code>
            {", "}
            <code className="deep-research-code">CSV</code>
            {", "}
            <code className="deep-research-code">HTML</code>
            ), які зручно переглядати та аналізувати.
          </p>
          <p>
            Підтримується робота з <strong>локальними моделями</strong> або через{" "}
            <code className="deep-research-code">API</code>
            , а також режим <strong>«досьє»</strong>
            {" "}
            — для комплексного аналізу кількох декларацій одного суб’єкта.
          </p>
          <p>
            Програма призначена для{" "}
            <strong>дослідників, журналістів, аналітиків</strong>
            {" "}
            та всіх, хто працює з <strong>антикорупційними даними</strong> або{" "}
            <strong>відкритими реєстрами</strong>.
          </p>
          <p>
            Створено для тих, хто хоче витрачати <strong>менше часу</strong> на читання декларацій і{" "}
            <strong>більше — на розуміння</strong>.
          </p>
          <div className="about-program-section">
            <p className="about-program-tagline">Декларації цифрові з 2016. Аналіз цифровим став тільки зараз.</p>
            <p className="about-program-credits">
              Зроблено Олександром Матвієнко.
              <br />
              Зворотний зв’язок:{" "}
              <a href="mailto:ctrlredtape@gmail.com">ctrlredtape@gmail.com</a>
            </p>
          </div>
          <p className="about-program-meta">
            Статус: <span className="about-program-status">[бета-версія]</span>
            {" · "}
            Версія: <code className="deep-research-code about-program-version">{APP_UI_VERSION}</code>
          </p>
            </>
          )}
        </div>
        <div className="cloud-modal-actions about-program-modal-actions">
          <div className="about-program-footer-toggle">
            <Toggle
              label="Показувати різні слогани в шапці."
              tooltip=""
              checked={showHeaderTaglines}
              onChange={(next) => {
                void onShowHeaderTaglinesChange(next);
              }}
            />
          </div>
          <div className="about-program-footer-actions">
            <TooltipWrap tip="Вітальне вікно та підказки">
              <button
                type="button"
                className="welcome-help-btn about-program-welcome-help"
                aria-label="Відкрити вітальне вікно"
                onClick={(e) => {
                  e.stopPropagation();
                  onOpenWelcome();
                }}
              >
                ?
              </button>
            </TooltipWrap>
            <button type="button" className="btn-secondary" onClick={onClose}>
              Закрити
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

const WIPE_CONFIRM_PHRASE = "ВИДАЛИТИ";

function WipeUsageTracesModal({ onClose, onConfirm, busy }) {
  const [confirmText, setConfirmText] = useState("");
  const canConfirm =
    !busy &&
    (confirmText.trim() === WIPE_CONFIRM_PHRASE || confirmText.trim() === "DELETE");

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, busy]);

  return (
    <div className="cloud-modal-overlay" role="presentation" onClick={busy ? undefined : onClose}>
      <div
        className="cloud-modal wipe-traces-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="wipe-traces-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="cloud-modal-title" id="wipe-traces-modal-title">
          Видалити сліди використання
        </div>
        <div className="cloud-modal-body">
          <p className="dossier-debug-hint">
            Буде видалено файли декларацій, звітів (JSONL, CSV, HTML), результати compare та deep
            research, audit-артефакти, <code className="deep-research-code">settings.json</code> та
            інші службові файли поруч із програмою. <strong>Папки залишаться</strong> (можуть бути
            порожніми). Дію не можна скасувати.
          </p>
          <label className="cloud-label" htmlFor="wipe-traces-confirm">
            Введіть <strong>{WIPE_CONFIRM_PHRASE}</strong> для підтвердження
          </label>
          <input
            id="wipe-traces-confirm"
            className="field-input"
            type="text"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder={WIPE_CONFIRM_PHRASE}
            disabled={busy}
            autoComplete="off"
            spellCheck={false}
          />
        </div>
        <div className="cloud-modal-actions">
          <button type="button" className="btn-secondary" onClick={onClose} disabled={busy}>
            Скасувати
          </button>
          <button
            type="button"
            className="btn-danger"
            onClick={onConfirm}
            disabled={!canConfirm}
          >
            {busy ? "Видалення…" : "Видалити назавжди"}
          </button>
        </div>
      </div>
    </div>
  );
}

const WELCOME_HELP_TOPICS = {
  folder: {
    title: "Папка з деклараціями",
    body: (
      <>
        <p>З DeclaratorLM працюють JSON-файли декларацій.</p>
        <p>Це можуть бути:</p>
        <ul className="welcome-help-list">
          <li>уже готові файли, які ви завантажили раніше</li>
          <li>результати парсингу через саму програму</li>
          <li>або експорт із інших інструментів</li>
        </ul>
        <p>
          Після вибору папки система автоматично знайде всі декларації всередині та підготує їх до аналізу.
        </p>
        <p>
          Переглянути, відсортувати та додати в чергу декларації можна натиснувши на значок{" "}
          <span className="welcome-help-file-icon" aria-hidden="true">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
            </svg>
          </span>
          , який знаходиться біля поля «Файли:».
        </p>
        <p>
          <strong>Одна декларація = один JSON-файл.</strong>
        </p>
      </>
    ),
  },
  mode: {
    title: "Локальний або хмарний режим",
    body: (
      <>
        <p>DeclaratorLM підтримує два способи роботи AI-моделей.</p>
        <h3 className="cloud-help-subtitle">Локальний режим</h3>
        <ul className="welcome-help-list">
          <li>модель працює прямо на вашому комп’ютері</li>
          <li>не потребує API ключів</li>
          <li>може працювати без інтернету</li>
          <li>навантажує процесор і пам’ять ПК</li>
        </ul>
        <h3 className="cloud-help-subtitle">Хмарний режим</h3>
        <ul className="welcome-help-list">
          <li>аналіз виконується через зовнішній AI-сервіс</li>
          <li>працює швидше</li>
          <li>відкриває доступ до сучасних reasoning-моделей</li>
          <li>потребує API ключа OpenRouter</li>
        </ul>
        <p>Для більшості користувачів хмарний режим простіший для старту.</p>
      </>
    ),
  },
  parsing: {
    title: "Парсинг декларацій",
    body: (
      <>
        <p>
          DeclaratorLM може самостійно завантажувати декларації з відкритого API НАЗК.
        </p>
        <p>Доступні два режими:</p>
        <ul className="welcome-help-list">
          <li>Завантаження конкретної декларації за ID</li>
          <li>Масовий пошук декларацій за роком та текстовим запитом</li>
        </ul>
        <p>
          Усі файли автоматично зберігаються у JSON-форматі та готові до подальшого AI-аналізу.
        </p>
        <p>
          Також доступний <strong>«Режим досьє»</strong> — система може завантажити всі декларації
          конкретного декларанта за різні роки та сформувати хронологічний аналіз.
        </p>
      </>
    ),
  },
  ollama: {
    title: "Ollama",
    body: (
      <>
        <p>
          Ollama — це програма для запуску AI-моделей локально на вашому комп’ютері.
        </p>
        <p>DeclaratorLM використовує Ollama для:</p>
        <ul className="welcome-help-list">
          <li>аналізу декларацій без хмарних сервісів</li>
          <li>роботи без API ключів</li>
          <li>локального або повністю офлайн-режиму</li>
        </ul>
        <p>Що потрібно зробити:</p>
        <ol className="cloud-help-steps">
          <li>Встановити Ollama</li>
          <li>Завантажити AI-модель</li>
          <li>Запустити Ollama перед аналізом</li>
        </ol>
        <p>Приклади моделей:</p>
        <ul className="welcome-help-list">
          <li>llama3.1</li>
          <li>qwen3</li>
        </ul>
        <p className="welcome-help-note">
          (квантизація/кількість параметрів обирайте враховуючи потужність заліза)
        </p>
        <p>
          Якщо Ollama не запущена — локальний режим працювати не буде. Завантажити для Windows:{" "}
          <a href="https://ollama.com/download/windows" target="_blank" rel="noopener noreferrer">
            ollama.com/download/windows
          </a>
          .
        </p>
      </>
    ),
  },
  openrouter: {
    title: "OpenRouter",
    body: (
      <>
        <p>OpenRouter — це сервіс доступу до AI-моделей через API.</p>
        <p>Він дозволяє використовувати:</p>
        <ul className="welcome-help-list">
          <li>Claude</li>
          <li>Kimi</li>
          <li>ChatGPT</li>
          <li>DeepSeek</li>
          <li>Qwen</li>
          <li>та інші сучасні моделі</li>
        </ul>
        <p>
          У хмарному режимі DeclaratorLM надсилає декларації на аналіз через OpenRouter і отримує
          структуровані AI-висновки назад.
        </p>
        <p>Для роботи потрібен API ключ.</p>
        <p>Переваги хмарного режиму:</p>
        <ul className="welcome-help-list">
          <li>швидший аналіз</li>
          <li>доступ до потужніших моделей</li>
          <li>менше навантаження на комп’ютер</li>
          <li>широкий вибір (500+) та підтримка reasoning-моделей</li>
        </ul>
        <p>API ключ додається у налаштуваннях Cloud Mode.</p>
      </>
    ),
  },
  ollamaCloud: {
    title: "Ollama Cloud",
    body: (
      <>
        <p>
          Ollama Cloud — це хмарний сервіс від Ollama для запуску AI-моделей без навантаження на ваш
          комп’ютер.
        </p>
        <p>На відміну від локального режиму:</p>
        <ul className="welcome-help-list">
          <li>моделі не потрібно завантажувати вручну</li>
          <li>не потрібно запускати Ollama локально</li>
          <li>аналіз виконується на віддалених серверах</li>
        </ul>
        <p>Переваги:</p>
        <ul className="welcome-help-list">
          <li>простіший старт</li>
          <li>не потрібна потужна відеокарта</li>
          <li>знайомий інтерфейс Ollama</li>
          <li>багато безкоштовних моделей, великі ліміти</li>
        </ul>
        <p>Для роботи потрібно:</p>
        <ol className="cloud-help-steps">
          <li>Увійти в акаунт Ollama</li>
          <li>Згенерувати API ключ в налаштуваннях</li>
          <li>Ввести його в налаштування Ollama Cloud</li>
          <li>Обрати модель у Cloud Mode</li>
          <li>Запустити аналіз</li>
        </ol>
        <p>Ollama Cloud добре підходить для першого знайомства з DeclaratorLM.</p>
      </>
    ),
  },
};

const LAUNCH_HELP_STEPS = [
  {
    title: "Кнопка «Запустити»",
    body: (
      <>
        <p>Кнопка «Запустити» знаходиться внизу ліворуч.</p>
        <p>Вона маленька. Синя. Важлива.</p>
      </>
    ),
  },
  {
    title: "Кнопка «Запустити»",
    body: (
      <>
        <p>Так, це знову інформація про кнопку «Запустити».</p>
        <p>Вона все ще внизу ліворуч.</p>
      </>
    ),
  },
  {
    title: "Кнопка «Запустити»",
    body: (
      <>
        <p>Легенди кажуть, що після натискання починається аналіз декларацій.</p>
        <p>Наука поки не спростувала це.</p>
      </>
    ),
  },
  {
    title: "Кнопка «Запустити»",
    body: (
      <>
        <p>Так, це вона.</p>
        <p>Та сама маленька синя кнопка внизу ліворуч.</p>
        <p>Вона не рухається. Це ви рухаєтесь до неминучого.</p>
      </>
    ),
  },
  {
    title: "Кнопка «Запустити»",
    body: (
      <>
        <p>Маленька синя кнопка терпляче чекає.</p>
        <p>Вона вірила у вас із самого початку.</p>
      </>
    ),
  },
  {
    title: "Кнопка «Запустити»",
    body: (
      <p>Система більше не знає, як пояснювати існування кнопки «Запустити».</p>
    ),
  },
  {
    title: "Кнопка «Запустити»",
    body: (
      <p>⚠️ DeclaratorLM тепер трохи вас боїться.</p>
    ),
  },
];

function WelcomeHelpButton({ topicId, label, onOpen, className = "" }) {
  return (
    <button
      type="button"
      className={`welcome-help-btn${className ? ` ${className}` : ""}`}
      aria-label={label}
      onClick={(e) => {
        e.stopPropagation();
        onOpen(topicId);
      }}
    >
      ?
    </button>
  );
}

function WelcomeHelpModal({ topicId, launchStepIndex = 0, onClose }) {
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const topic =
    topicId === "launch"
      ? LAUNCH_HELP_STEPS[
          Math.min(Math.max(0, launchStepIndex), LAUNCH_HELP_STEPS.length - 1)
        ]
      : WELCOME_HELP_TOPICS[topicId];
  if (!topic) return null;

  return (
    <div
      className="cloud-help-overlay welcome-help-overlay"
      role="presentation"
      onClick={onClose}
    >
      <div
        className="cloud-help-dialog welcome-help-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="welcome-help-heading"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="welcome-help-heading" className="cloud-help-title">
          {topic.title}
        </h2>
        <div className="cloud-help-body welcome-help-body">
          {topic.body}
          <div className="welcome-help-ok-row">
            <button type="button" className="btn-primary" onClick={onClose}>
              Зрозуміло
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function WelcomeModal({ onDismiss, onOpenBulkParsing, bulkParseDisabled }) {
  const [helpTopic, setHelpTopic] = useState(null);
  const [launchHelpClickCount, setLaunchHelpClickCount] = useState(0);
  const [launchHelpOpenIndex, setLaunchHelpOpenIndex] = useState(0);
  const [launchHelpBtnHiding, setLaunchHelpBtnHiding] = useState(false);
  const [launchHelpBtnHidden, setLaunchHelpBtnHidden] = useState(false);
  const launchHideTimerRef = useRef(null);

  const handleHelpOpen = useCallback(
    (topicId) => {
      if (topicId === "launch") {
        if (launchHelpBtnHidden || launchHelpBtnHiding) return;
        if (launchHelpClickCount >= LAUNCH_HELP_STEPS.length) return;
        setLaunchHelpOpenIndex(launchHelpClickCount);
        setHelpTopic("launch");
        return;
      }
      setHelpTopic(topicId);
    },
    [launchHelpBtnHidden, launchHelpBtnHiding, launchHelpClickCount]
  );

  const handleHelpClose = useCallback(() => {
    if (helpTopic === "launch") {
      setHelpTopic(null);
      const next = launchHelpOpenIndex + 1;
      setLaunchHelpClickCount(next);
      if (next >= LAUNCH_HELP_STEPS.length) {
        const reduced =
          typeof window !== "undefined" &&
          window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        if (reduced) {
          setLaunchHelpBtnHidden(true);
          setLaunchHelpBtnHiding(false);
          return;
        }
        setLaunchHelpBtnHiding(true);
        launchHideTimerRef.current = window.setTimeout(() => {
          setLaunchHelpBtnHidden(true);
          setLaunchHelpBtnHiding(false);
          launchHideTimerRef.current = null;
        }, LAUNCH_HELP_FADE_MS);
      }
      return;
    }
    setHelpTopic(null);
  }, [helpTopic, launchHelpOpenIndex]);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      if (helpTopic) handleHelpClose();
      else onDismiss();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onDismiss, helpTopic, handleHelpClose]);

  useEffect(
    () => () => {
      if (launchHideTimerRef.current != null) {
        window.clearTimeout(launchHideTimerRef.current);
      }
    },
    []
  );

  return (
    <>
    <div className="cloud-modal-overlay welcome-modal-overlay" role="presentation" onClick={onDismiss}>
      <div
        className="cloud-modal welcome-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="welcome-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="cloud-modal-title" id="welcome-modal-title">
          Ласкаво просимо в DeclaratorLM
        </div>
        <div className="cloud-modal-body welcome-modal-body">
          <p>
            Зліва — усе необхідне для запуску.
            <br />
            Справа — журнал аналізу та подій пайплайну.
          </p>
          <p className="welcome-modal-section-label">Щоб почати:</p>
          <ul className="welcome-modal-checklist">
            <li>
              Вкажіть папку з деклараціями (якщо вже маєте готові файли)
              <WelcomeHelpButton
                topicId="folder"
                label="Довідка: папка з деклараціями"
                onOpen={handleHelpOpen}
              />
            </li>
            <li>
              Оберіть та налаштуйте локальний або хмарний режим
              <WelcomeHelpButton
                topicId="mode"
                label="Довідка: локальний або хмарний режим"
                onOpen={handleHelpOpen}
              />
            </li>
            <li>
              Натисніть «Запустити»
              {!launchHelpBtnHidden ? (
                <WelcomeHelpButton
                  topicId="launch"
                  label="Довідка: кнопка «Запустити»"
                  onOpen={handleHelpOpen}
                  className={launchHelpBtnHiding ? "welcome-help-btn--hiding" : ""}
                />
              ) : null}
            </li>
          </ul>
          <p className="welcome-modal-section-label">DeclaratorLM по черзі:</p>
          <ul className="welcome-modal-dashlist">
            <li>аналізує декларації</li>
            <li>формує структуровані AI-висновки</li>
            <li>генерує HTML-звіт із результатами</li>
          </ul>
          <p>
            <strong>Немає готових файлів?</strong>
            <br />
            У блоці «Інструменти» натисніть «Парсинг» — система може самостійно
            завантажити декларації з відкритих джерел (API НАЗК).
            <WelcomeHelpButton
              topicId="parsing"
              label="Довідка: парсинг декларацій"
              onOpen={handleHelpOpen}
            />
          </p>
          <p>
            <strong>Режими роботи:</strong>
            <br />
            Для локального режиму потрібна Ollama.
            <WelcomeHelpButton topicId="ollama" label="Довідка: Ollama" onOpen={handleHelpOpen} />
            <br />
            Для хмарного — API ключ OpenRouter
            <WelcomeHelpButton
              topicId="openrouter"
              label="Довідка: OpenRouter"
              onOpen={handleHelpOpen}
            />{" "}
            або Ollama Cloud
            <WelcomeHelpButton
              topicId="ollamaCloud"
              label="Довідка: Ollama Cloud"
              onOpen={handleHelpOpen}
            />
            .
          </p>
          <p>
            Після завершення аналізу звіт можна відкрити кнопкою поруч із «Запустити».
          </p>
        </div>
        <div className="cloud-modal-actions welcome-modal-actions">
          <button type="button" className="btn-secondary" onClick={onDismiss}>
            Сам розберусь, дякую
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={bulkParseDisabled}
            onClick={() => {
              void onOpenBulkParsing();
            }}
          >
            Відкрити парсинг
          </button>
        </div>
      </div>
    </div>
    <AnimatedModalPresence when={Boolean(helpTopic)}>
      <WelcomeHelpModal
        topicId={helpTopic}
        launchStepIndex={launchHelpOpenIndex}
        onClose={handleHelpClose}
      />
    </AnimatedModalPresence>
    </>
  );
}

function CloudComparisonModal({
  open = true,
  provider,
  host,
  tableHtml,
  models,
  initialCount = 2,
  defaultSelection,
  openrouterPricing = null,
  onReloadModels,
  onCancel,
  onConfirm,
}) {
  const modalRef = useRef(null);
  useSmoothModalResize(modalRef);
  const [count, setCount] = useState(2);
  const [selection, setSelection] = useState(() => Array.isArray(defaultSelection) ? defaultSelection.slice(0, 4) : ["", "", "", ""]);
  const [error, setError] = useState("");
  const [modelQueries, setModelQueries] = useState(["", "", "", ""]);
  const [openComboboxIdx, setOpenComboboxIdx] = useState(-1);
  const comboboxRefs = useRef([null, null, null, null]);

  useEffect(() => {
    if (!open) return;
    const base = Array.isArray(defaultSelection) ? defaultSelection.slice(0, 4) : [];
    while (base.length < 4) base.push("");
    setSelection(base);
    const parsedCount = Math.floor(Number(initialCount));
    const fallbackCount = base.filter(Boolean).length || 2;
    setCount(Number.isFinite(parsedCount) ? Math.min(4, Math.max(2, parsedCount)) : Math.min(4, Math.max(2, fallbackCount)));
    setError("");
    setModelQueries(base.map((m) => String(m || "")));
    setOpenComboboxIdx(-1);
  }, [open, defaultSelection, initialCount]);

  useEffect(() => {
    if (openComboboxIdx < 0) return;
    const onDocMouseDown = (e) => {
      const el = comboboxRefs.current[openComboboxIdx];
      if (!el) return;
      if (e.target instanceof Node && !el.contains(e.target)) {
        setOpenComboboxIdx(-1);
      }
    };
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [openComboboxIdx]);

  const activeModels = sortModelsAZ(
    Array.from(
      new Set(
        (models || [])
          .filter((m) => m !== null && m !== undefined)
          .map((m) => String(m))
          .filter((m) => m.trim())
      )
    )
  );
  const providerLabel = provider === "openrouter" ? "OpenRouter" : "Ollama";

  const selectedNow = selection.slice(0, count).map((m) => String(m || "").trim());
  const selectedNonEmpty = selectedNow.filter(Boolean);
  const uniqueCount = new Set(selectedNonEmpty).size;
  const canConfirm = selectedNonEmpty.length >= 2 && uniqueCount === selectedNonEmpty.length;

  const setAt = (idx, value) => {
    setSelection((prev) => {
      const next = prev.slice(0, 4);
      while (next.length < 4) next.push("");
      next[idx] = value;
      return next;
    });
  };

  const setQueryAt = (idx, value) => {
    setModelQueries((prev) => {
      const next = prev.slice(0, 4);
      while (next.length < 4) next.push("");
      next[idx] = value;
      return next;
    });
  };

  const selectModelAt = (idx, value) => {
    setAt(idx, value);
    setQueryAt(idx, value);
    setOpenComboboxIdx(-1);
  };

  const handleConfirm = () => {
    if (!canConfirm) {
      setError("Оберіть 2-4 різні моделі.");
      return;
    }
    setError("");
    if (typeof onConfirm === "function") {
      onConfirm({
        count,
        compare_models: selectedNonEmpty,
      });
    }
    if (typeof onCancel === "function") onCancel();
  };

  const content = (
    <>
        <div className="cloud-modal-title">Порівняння моделей (debug)</div>
        <div className="cloud-modal-body">
          <div className="dossier-debug-hint">
            Провайдер: <strong>{providerLabel}</strong>. Host: <code>{host || "(not set)"}</code>
            <br />
            HTML-джерело: <code>{tableHtml || "(not set)"}</code>
          </div>
          <div className="field-row">
            <label className="field-label">Кількість моделей</label>
            <input
              className="field-input field-input--short"
              type="number"
              min={2}
              max={4}
              step={1}
              value={count}
              onChange={(e) => {
                const v = Math.floor(Number(e.target.value));
                setCount(Number.isFinite(v) ? Math.min(4, Math.max(2, v)) : 2);
              }}
            />
          </div>
          {Array.from({ length: count }).map((_, idx) => (
            <div className="field-row" key={`cmp-model-${idx}`}>
              <label className="field-label">Модель {idx + 1}</label>
              <div
                className="model-combobox-root"
                ref={(el) => {
                  comboboxRefs.current[idx] = el;
                }}
              >
                <input
                  className="field-input model-combobox-input"
                  value={selection[idx] || ""}
                  onChange={(e) => {
                    const val = e.target.value;
                    setAt(idx, val);
                    setQueryAt(idx, val);
                    setOpenComboboxIdx(idx);
                  }}
                  onFocus={() => {
                    setOpenComboboxIdx(idx);
                    setQueryAt(idx, selection[idx] || "");
                  }}
                  placeholder="— Оберіть модель —"
                />
                {openComboboxIdx === idx && (
                  <div className="model-combobox-dropdown" role="listbox" aria-label={`Список моделей ${idx + 1}`}>
                    {activeModels
                      .filter((m) => {
                        const q = String(modelQueries[idx] || "").trim().toLowerCase();
                        return !q || String(m).toLowerCase().includes(q);
                      })
                      .slice(0, 200)
                      .map((m) => {
                        const priceLine =
                          provider === "openrouter" && openrouterPricing && typeof openrouterPricing === "object"
                            ? String(openrouterPricing[m] || "").trim()
                            : "";
                        return (
                        <button
                          key={`${idx}-${m}`}
                          type="button"
                          className="model-combobox-option"
                          title={priceLine ? `${m}\n${priceLine}` : m}
                          onMouseDown={(e) => e.preventDefault()}
                          onClick={() => selectModelAt(idx, m)}
                        >
                          <span className="model-combobox-option-main">{m}</span>
                          {priceLine ? (
                            <span className="model-combobox-option-meta">{priceLine}</span>
                          ) : null}
                        </button>
                        );
                      })}
                    {activeModels.filter((m) => {
                      const q = String(modelQueries[idx] || "").trim().toLowerCase();
                      return !q || String(m).toLowerCase().includes(q);
                    }).length === 0 ? (
                      <div className="model-combobox-empty">Немає моделей для цього запиту</div>
                    ) : null}
                  </div>
                )}
              </div>
            </div>
          ))}
          {error ? <div className="cloud-error">{error}</div> : null}
        </div>
        <div className="cloud-modal-actions">
          <TooltipWrap tip="Оновити список моделей поточного провайдера">
            <button type="button" className="btn-browse" onClick={onReloadModels}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/>
                <path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/>
              </svg>
            </button>
          </TooltipWrap>
          <button type="button" className="btn-secondary" onClick={onCancel}>Скасувати</button>
          <button type="button" className="btn-primary" onClick={handleConfirm} disabled={!canConfirm}>
            OK
          </button>
        </div>
    </>
  );

  return (
    <div className="cloud-modal-overlay">
      <div ref={modalRef} className="cloud-modal cloud-modal--smooth-size">
        {content}
      </div>
    </div>
  );
}

function CloudWarningModal({ onConfirm, onCancel }) {
  const { locale } = useI18n();
  return (
    <div className="cloud-modal-overlay">
      <div className="cloud-modal cloud-warning-modal">
        <div className="cloud-modal-title">Увімкнути Cloud Mode?</div>
        <div className="cloud-warning-text">
          {locale === "en" ? (
            <CloudWarningBodyEn />
          ) : (
            <>
          <p>
            У цьому режимі DeclaratorLM використовує зовнішні AI-сервіси (Ollama Cloud або
            OpenRouter) для аналізу декларацій.
          </p>
          <p>
            Публічні декларації НАЗК зазвичай безпечно обробляти у Cloud Mode.
          </p>
          <p>Для приватних або чутливих документів рекомендується Local Mode.</p>
            </>
          )}
          <div className="cloud-warning-footer">
            <p className="cloud-warning-privacy">
              Детальніше про обробку даних та політику конфіденційності:
              <br />
              <a href="https://ollama.com/privacy" target="_blank" rel="noopener noreferrer">
                ollama.com/privacy
              </a>
              <br />
              <a href="https://openrouter.ai/privacy" target="_blank" rel="noopener noreferrer">
                openrouter.ai/privacy
              </a>
            </p>
            <div className="cloud-modal-actions cloud-modal-actions--warning">
              <button type="button" className="btn-secondary" onClick={onCancel}>
                Скасувати
              </button>
              <button type="button" className="btn-primary" onClick={onConfirm}>
                Увімкнути
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// DEEP_RESEARCH: modal — download from NAZK or pick an existing deep_research folder
function DeepResearchModal({
  tab,
  onTab,
  userDeclarantId,
  onChangeId,
  folders,
  foldersLoading,
  selectedFolder,
  onSelectFolder,
  onRefreshFolders,
  loading,
  loadingHint,
  downloadProgress,
  error,
  onCancel,
  onSubmitDownload,
  onApplyExisting,
}) {
  const { locale } = useI18n();
  const hasReadyFolders = folders.some((f) => f.decl_count > 0);
  const modalRef = useRef(null);
  useSmoothModalResize(modalRef);
  return (
    <div className="cloud-modal-overlay">
      <div ref={modalRef} className="cloud-modal deep-research-modal cloud-modal--smooth-size">
        <div className="cloud-modal-title">Режим досьє</div>
        <div
          className="deep-research-tabs"
          role="tablist"
          style={{ "--active-tab-index": tab === "download" ? 0 : 1, "--tabs-count": 2 }}
        >
          <button
            type="button"
            role="tab"
            className={`deep-research-tab${tab === "download" ? " deep-research-tab--active" : ""}`}
            aria-selected={tab === "download"}
            onClick={() => !loading && onTab("download")}
            disabled={loading}
          >
            Завантажити з API
          </button>
          <button
            type="button"
            role="tab"
            className={`deep-research-tab${tab === "existing" ? " deep-research-tab--active" : ""}`}
            aria-selected={tab === "existing"}
            onClick={() => !loading && onTab("existing")}
            disabled={loading}
          >
            Існуюча папка
          </button>
        </div>
        <div className="cloud-modal-body">
          {error && <div className="cloud-error">{error}</div>}
          <AnimatedTabPanel
            tabKey={tab}
            render={(activeTab) =>
              activeTab === "download" ? (
                <>
                  {locale === "en" ? (
                    <DeepResearchDownloadHintEn />
                  ) : (
                  <p className="deep-research-hint">
                    Вкажіть <strong>user_declarant_id</strong> з відкритого API НАЗК. Будуть завантажені доступні
                    декларації цієї особи у каталог <code className="deep-research-code">deep_research/</code> під
                    іменем за прізвищем.
                  </p>
                  )}
                  <label className="cloud-label">user_declarant_id</label>
                  <input
                    className="field-input"
                    type="number"
                    min={1}
                    step={1}
                    value={userDeclarantId}
                    onChange={(e) => onChangeId(e.target.value)}
                    placeholder="наприклад 2219565"
                    disabled={loading}
                  />
                </>
              ) : (
                <>
                  {locale === "en" ? (
                    <DeepResearchExistingHintEn />
                  ) : (
                  <p className="deep-research-hint">
                    Оберіть підкаталог у <code className="deep-research-code">deep_research/</code> з уже завантаженими
                    файлами <code className="deep-research-code">decl_*.json</code>. Пайплайн використає їх як чергу
                    без звернення до API.
                  </p>
                  )}
                  <div className="deep-research-folder-row">
                    <label className="cloud-label">Папка</label>
                    <button
                      type="button"
                      className="btn-secondary deep-research-refresh"
                      onClick={onRefreshFolders}
                      disabled={loading || foldersLoading}
                    >
                      Оновити список
                    </button>
                  </div>
                  {foldersLoading ? (
                    <div className="deep-research-loading deep-research-loading--inline">
                      <div className="deep-research-spinner" aria-hidden="true" />
                      <span className="deep-research-loading-text">Читаю deep_research…</span>
                    </div>
                  ) : (
                    <select
                      className="field-input deep-research-select"
                      value={selectedFolder}
                      onChange={(e) => onSelectFolder(e.target.value)}
                      disabled={loading || !hasReadyFolders}
                    >
                      <option value="">
                        {hasReadyFolders ? "— оберіть папку —" : "— немає папок з decl_*.json —"}
                      </option>
                      {folders.map((f) => (
                        <option key={f.name} value={f.name} disabled={f.decl_count < 1}>
                          {f.name} ({f.decl_count} декл.)
                        </option>
                      ))}
                    </select>
                  )}
                </>
              )
            }
          />

          {loading && tab === "download" && downloadProgress ? (
            <div className="deep-research-dl-stats" aria-live="polite">
              <div className="deep-research-dl-stat">
                <span className="deep-research-dl-stat-label">Знайдено</span>
                <span className="deep-research-dl-stat-value">{downloadProgress.found ?? 0}</span>
              </div>
              <div className="deep-research-dl-stat">
                <span className="deep-research-dl-stat-label">Завантажено</span>
                <span className="deep-research-dl-stat-value">{downloadProgress.downloaded ?? 0}</span>
              </div>
              {(downloadProgress.skipped ?? 0) > 0 ? (
                <div className="deep-research-dl-stat deep-research-dl-stat--muted">
                  <span className="deep-research-dl-stat-label">Вже на диску</span>
                  <span className="deep-research-dl-stat-value">{downloadProgress.skipped}</span>
                </div>
              ) : null}
            </div>
          ) : null}

          {loading && (
            <div className="deep-research-loading">
              <div className="deep-research-spinner" aria-hidden="true" />
              <span className="deep-research-loading-text">{loadingHint || "…"}</span>
            </div>
          )}
        </div>
        <div className="cloud-modal-actions">
          <div className="modal-tab-actions-slot">
            <AnimatedTabPanel
              tabKey={tab}
              render={(activeTab) =>
                activeTab === "download" ? (
                  <>
                    <button className="btn-secondary" onClick={onCancel} disabled={loading}>
                      Скасувати
                    </button>
                    <button className="btn-primary" onClick={onSubmitDownload} disabled={loading}>
                      Завантажити
                    </button>
                  </>
                ) : (
                  <>
                    <button className="btn-secondary" onClick={onCancel} disabled={loading}>
                      Скасувати
                    </button>
                    <button
                      className="btn-primary"
                      onClick={onApplyExisting}
                      disabled={loading || foldersLoading || !selectedFolder}
                    >
                      У чергу без завантаження
                    </button>
                  </>
                )
              }
            />
          </div>
        </div>
      </div>
    </div>
  );
}

const NAZK_DECLARATION_TYPE_OPTIONS = [
  { value: "", label: "Усі види" },
  { value: "1", label: "Щорічна" },
  { value: "2", label: "Перед звільненням" },
  { value: "3", label: "Після звільнення" },
  { value: "4", label: "Кандидата на посаду" },
];

const NAZK_DOCUMENT_TYPE_OPTIONS = [
  { value: "", label: "Усі типи" },
  { value: "1", label: "Декларація" },
  { value: "2", label: "Повідомлення про зміни" },
  { value: "3", label: "Виправлена декларація" },
];

function nazkFilterOptionLabel(options, value) {
  const v = String(value || "");
  const hit = options.find((o) => o.value === v);
  return hit && hit.value ? hit.label : null;
}

function ParseDeclarationModal({
  tab,
  onTab,
  declarationId,
  onChangeId,
  bulkYear,
  bulkUseYear,
  onChangeBulkUseYear,
  bulkQuery,
  onChangeBulkQuery,
  bulkCount,
  bulkDeclarationType,
  bulkDocumentType,
  bulkTargetDir,
  onChangeBulkYear,
  onChangeBulkCount,
  onChangeBulkDeclarationType,
  onChangeBulkDocumentType,
  onChangeBulkTargetDir,
  onBrowseBulkTarget,
  loading,
  loadingHint,
  error,
  onCancel,
  onSubmitSingle,
  onSubmitBulk,
}) {
  const maxYear = new Date().getFullYear();
  const modalRef = useRef(null);
  useSmoothModalResize(modalRef);
  return (
    <div className="cloud-modal-overlay">
      <div ref={modalRef} className="cloud-modal parse-modal cloud-modal--smooth-size">
        <div className="cloud-modal-title">Парсинг декларацій (НАЗК)</div>
        <div
          className="deep-research-tabs parse-modal-tabs"
          role="tablist"
          style={{ "--active-tab-index": tab === "single" ? 0 : 1, "--tabs-count": 2 }}
        >
          <button
            type="button"
            role="tab"
            className={`deep-research-tab${tab === "single" ? " deep-research-tab--active" : ""}`}
            aria-selected={tab === "single"}
            onClick={() => !loading && onTab("single")}
            disabled={loading}
          >
            Одна декларація
          </button>
          <button
            type="button"
            role="tab"
            className={`deep-research-tab${tab === "bulk" ? " deep-research-tab--active" : ""}`}
            aria-selected={tab === "bulk"}
            onClick={() => !loading && onTab("bulk")}
            disabled={loading}
          >
            Множинний парсинг
          </button>
        </div>
        <div className="cloud-modal-body">
          {error && <div className="cloud-error">{error}</div>}
          <AnimatedTabPanel
            tabKey={tab}
            render={(activeTab) =>
              activeTab === "single" ? (
                <>
                  <p className="deep-research-hint">
                    Введіть <strong>declaration_id</strong> (UUID). Файл буде збережено у{" "}
                    <strong>папку декларацій</strong> з блоку «Основні параметри» (як при множинному парсингу).
                  </p>
                  <label className="cloud-label">declaration_id</label>
                  <input
                    className="field-input"
                    value={declarationId}
                    onChange={(e) => onChangeId(e.target.value)}
                    placeholder="наприклад 9f4f0f34-...."
                    disabled={loading}
                  />
                </>
              ) : (
                <>
                  <p className="deep-research-hint">
                    За відкритим API НАЗК завантажуються перші <strong>нові</strong> декларації за обраними
                    фільтрами (рік, пошук, вид, тип документа), поки не набереться потрібна кількість. Файли, що вже
                    є у папці, пропускаються.
                  </p>
                  <div className="parse-bulk-form">
                    <div className="parse-bulk-form-row parse-bulk-form-row--triple">
                      <div
                        className={`parse-bulk-field-cell${
                          !bulkUseYear ? " parse-bulk-field-cell--inactive" : ""
                        }`}
                      >
                        <label className="cloud-label">Рік декларації</label>
                        <input
                          className="field-input"
                          type="number"
                          min={2015}
                          max={maxYear}
                          step={1}
                          value={bulkYear}
                          onChange={(e) => onChangeBulkYear(e.target.value)}
                          disabled={loading || !bulkUseYear}
                        />
                      </div>
                      <div className="parse-bulk-field-cell">
                        <label className="cloud-label">Вид декларації</label>
                        <select
                          className="field-input parse-bulk-filter-select"
                          value={bulkDeclarationType}
                          onChange={(e) => onChangeBulkDeclarationType(e.target.value)}
                          disabled={loading}
                          aria-label="Вид декларації"
                        >
                          {NAZK_DECLARATION_TYPE_OPTIONS.map((o) => (
                            <option key={o.value || "all"} value={o.value}>
                              {o.label}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="parse-bulk-field-cell">
                        <label className="cloud-label">Тип документа</label>
                        <select
                          className="field-input parse-bulk-filter-select"
                          value={bulkDocumentType}
                          onChange={(e) => onChangeBulkDocumentType(e.target.value)}
                          disabled={loading}
                          aria-label="Тип документа"
                        >
                          {NAZK_DOCUMENT_TYPE_OPTIONS.map((o) => (
                            <option key={o.value || "all"} value={o.value}>
                              {o.label}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                    <div className="parse-bulk-form-row parse-bulk-form-row--double">
                      <div className="parse-bulk-field-cell">
                        <label className="cloud-label">Кількість</label>
                        <input
                          className="field-input"
                          type="number"
                          min={1}
                          max={500}
                          step={1}
                          value={bulkCount}
                          onChange={(e) => onChangeBulkCount(e.target.value)}
                          disabled={loading}
                        />
                      </div>
                      <div className="parse-bulk-field-cell">
                        <label className="cloud-label">Пошуковий запит</label>
                        <input
                          className="field-input"
                          value={bulkQuery}
                          onChange={(e) => onChangeBulkQuery(e.target.value)}
                          placeholder="від 3х символів"
                          disabled={loading}
                          maxLength={255}
                          autoComplete="off"
                        />
                      </div>
                    </div>
                  </div>
                  <label className="cloud-label">Папка призначення</label>
                  <div className="field-input-group">
                    <input
                      className="field-input"
                      value={bulkTargetDir}
                      onChange={(e) => onChangeBulkTargetDir(e.target.value)}
                      placeholder="відносний або абсолютний шлях у межах проєкту"
                      disabled={loading}
                    />
                    <button type="button" className="btn-browse" onClick={onBrowseBulkTarget} disabled={loading}>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
                      </svg>
                    </button>
                  </div>
                </>
              )
            }
          />

          {loading && (
            <div className="deep-research-loading">
              <div className="deep-research-spinner" aria-hidden="true" />
              <span className="deep-research-loading-text">{loadingHint || "…"}</span>
            </div>
          )}
        </div>
        <div className="cloud-modal-actions">
          <AnimatedTabPanel
            tabKey={tab}
            render={(activeTab) =>
              activeTab === "bulk" ? (
                <div className="parse-bulk-actions-content">
                  <Toggle
                    compact
                    label="Враховувати рік декларації"
                    tooltip=""
                    checked={bulkUseYear}
                    onChange={onChangeBulkUseYear}
                    disabled={loading}
                  />
                  <div className="parse-modal-actions-end">
                    <button type="button" className="btn-secondary" onClick={onCancel} disabled={loading}>
                      Скасувати
                    </button>
                    <button type="button" className="btn-primary" onClick={onSubmitBulk} disabled={loading}>
                      Завантажити
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <button type="button" className="btn-secondary" onClick={onCancel} disabled={loading}>
                    Скасувати
                  </button>
                  <button type="button" className="btn-primary" onClick={onSubmitSingle} disabled={loading}>
                    Завантажити
                  </button>
                </>
              )
            }
          />
        </div>
      </div>
    </div>
  );
}

function PromptSessionModal({
  tab,
  onTab,
  draft,
  onDraftField,
  loadingBuiltin,
  onClose,
  onApply,
  onResetBuiltin,
}) {
  return (
    <div className="cloud-modal-overlay">
      <div className="cloud-modal prompt-editor-modal">
        <div className="cloud-modal-title">Редагування промптів (лише сесія, debug)</div>
        <p className="deep-research-hint" style={{ marginTop: 0 }}>
          Зміни застосовуються лише до поточного запуску програми й не записуються у файли проєкту.
          Після закриття застосунку все знову береться з коду. Оригінальні рядки у{" "}
          <code className="deep-research-code">main.py</code> та{" "}
          <code className="deep-research-code">dossier_html_summary.py</code> не змінюються.
        </p>
        <div className="deep-research-tabs parse-modal-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            className={`deep-research-tab${tab === "pipeline" ? " deep-research-tab--active" : ""}`}
            aria-selected={tab === "pipeline"}
            onClick={() => !loadingBuiltin && onTab("pipeline")}
            disabled={loadingBuiltin}
          >
            Пайплайн аналізу
          </button>
          <button
            type="button"
            role="tab"
            className={`deep-research-tab${tab === "dossier" ? " deep-research-tab--active" : ""}`}
            aria-selected={tab === "dossier"}
            onClick={() => !loadingBuiltin && onTab("dossier")}
            disabled={loadingBuiltin}
          >
            Досьє (HTML-звіт)
          </button>
        </div>
        <div className="cloud-modal-body prompt-editor-body">
          {loadingBuiltin && (
            <div className="deep-research-loading deep-research-loading--inline">
              <div className="deep-research-spinner" aria-hidden="true" />
              <span className="deep-research-loading-text">Завантаження вбудованих текстів…</span>
            </div>
          )}
          {tab === "pipeline" && !loadingBuiltin && (
            <>
              <p className="deep-research-hint">
                User-шаблон <strong>обов&apos;язково</strong> має містити плейсхолдер{" "}
                <code className="deep-research-code">{"{declaration_payload}"}</code> — туди підставляється JSON
                декларації.
              </p>
              <label className="cloud-label">System (пайплайн)</label>
              <textarea
                className="field-input prompt-editor-textarea"
                value={draft.pipelineSystem}
                onChange={(e) => onDraftField("pipelineSystem", e.target.value)}
                spellCheck={false}
              />
              <label className="cloud-label">User-шаблон (пайплайн)</label>
              <textarea
                className="field-input prompt-editor-textarea"
                value={draft.pipelineUser}
                onChange={(e) => onDraftField("pipelineUser", e.target.value)}
                spellCheck={false}
              />
            </>
          )}
          {tab === "dossier" && !loadingBuiltin && (
            <>
              <p className="deep-research-hint">
                User-шаблон для переаналізу HTML має містити{" "}
                <code className="deep-research-code">{"{html_fragment}"}</code> та{" "}
                <code className="deep-research-code">{"{truncation_note}"}</code>.
              </p>
              <label className="cloud-label">System (досьє)</label>
              <textarea
                className="field-input prompt-editor-textarea"
                value={draft.dossierSystem}
                onChange={(e) => onDraftField("dossierSystem", e.target.value)}
                spellCheck={false}
              />
              <label className="cloud-label">User-шаблон (досьє)</label>
              <textarea
                className="field-input prompt-editor-textarea"
                value={draft.dossierUser}
                onChange={(e) => onDraftField("dossierUser", e.target.value)}
                spellCheck={false}
              />
            </>
          )}
        </div>
        <div className="cloud-modal-actions prompt-editor-actions">
          <button type="button" className="btn-secondary" onClick={onResetBuiltin} disabled={loadingBuiltin}>
            Скинути до вбудованих
          </button>
          <div className="prompt-editor-actions-end">
            <button type="button" className="btn-secondary" onClick={onClose} disabled={loadingBuiltin}>
              Закрити
            </button>
            <button type="button" className="btn-primary" onClick={onApply} disabled={loadingBuiltin}>
              Застосувати до сесії
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function sortOrderShortLabel(order) {
  switch (order) {
    case "alpha-desc": return "Я→А";
    case "mtime":      return "Дата↓";
    case "mtime-asc":  return "Дата↑";
    case "size":       return "Розм↓";
    case "size-asc":   return "Розм↑";
    default:           return "А→Я";
  }
}

const SORT_DROPDOWN_EXIT_MS = 160;
const SORT_MENU_WIDTH = 280;
const SORT_MENU_EST_HEIGHT = 300;

function SortDropdown({
  open,
  sortOrder,
  onPick,
  onToggleOpen,
  anchorRef,
  menuRef,
  sortModeActive,
}) {
  const [rendered, setRendered] = useState(false);
  const [exiting, setExiting] = useState(false);
  const [menuPos, setMenuPos] = useState({ top: 0, left: 0 });

  const updateMenuPosition = useCallback(() => {
    const anchor = anchorRef?.current;
    if (!anchor || typeof window === "undefined") return;
    const r = anchor.getBoundingClientRect();
    const pad = 8;
    const w = SORT_MENU_WIDTH;
    let left = r.left;
    let top = r.bottom + 4;
    if (left + w > window.innerWidth - pad) {
      left = window.innerWidth - w - pad;
    }
    if (left < pad) left = pad;
    if (top + SORT_MENU_EST_HEIGHT > window.innerHeight - pad) {
      top = Math.max(pad, r.top - 4 - SORT_MENU_EST_HEIGHT);
    }
    setMenuPos({ top, left });
  }, [anchorRef]);

  useLayoutEffect(() => {
    if (open) {
      setExiting(false);
      setRendered(true);
    } else if (rendered && !exiting) {
      setExiting(true);
      const t = setTimeout(() => {
        setRendered(false);
        setExiting(false);
      }, SORT_DROPDOWN_EXIT_MS);
      return () => clearTimeout(t);
    }
  }, [open]);

  useLayoutEffect(() => {
    if (!rendered || exiting || !open) return;
    updateMenuPosition();
    const onWin = () => updateMenuPosition();
    window.addEventListener("resize", onWin);
    window.addEventListener("scroll", onWin, true);
    return () => {
      window.removeEventListener("resize", onWin);
      window.removeEventListener("scroll", onWin, true);
    };
  }, [rendered, exiting, open, updateMenuPosition]);

  const item = (value, label) => (
    <button
      type="button"
      role="menuitem"
      className={`sort-dropdown-item${sortOrder === value ? " sort-dropdown-item--active" : ""}`}
      onClick={() => onPick(value)}
    >
      {label}
    </button>
  );

  const menuNode =
    rendered &&
    typeof document !== "undefined" &&
    createPortal(
      <div
        ref={menuRef}
        className={`sort-dropdown sort-dropdown--portal${exiting ? " sort-dropdown--exiting" : ""}`}
        style={{
          position: "fixed",
          top: menuPos.top,
          left: menuPos.left,
          width: SORT_MENU_WIDTH,
          zIndex: 12000,
        }}
        role="menu"
        aria-label="Порядок файлів"
      >
        <div className="sort-dropdown-group-label">За алфавітом</div>
        {item("alpha", "А→Я (a→z)")}
        {item("alpha-desc", "Я→А (z→a)")}
        <div className="sort-dropdown-sep" role="separator" />
        <div className="sort-dropdown-group-label">За датою зміни</div>
        {item("mtime", "Спочатку новіші")}
        {item("mtime-asc", "Спочатку старіші")}
        <div className="sort-dropdown-sep" role="separator" />
        <div className="sort-dropdown-group-label">За розміром</div>
        {item("size", "Спочатку більші")}
        {item("size-asc", "Спочатку менші")}
      </div>,
      document.body
    );

  return (
    <div className="sort-queue-anchor" ref={anchorRef}>
      <TooltipWrap tip={SIDEBAR_TOOLTIPS.queueSort}>
        <button
          type="button"
          className={`queue-btn${sortModeActive ? " queue-btn--active" : ""}`}
          aria-pressed={sortModeActive}
          aria-expanded={open}
          onClick={onToggleOpen}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
            <path d="M4 6h16M4 12h10M4 18h6" />
            <path d="M19 8v13M16 5l3-3 3 3" />
          </svg>
          <span className="queue-btn__sort-label">{sortOrderShortLabel(sortOrder)}</span>
        </button>
      </TooltipWrap>
      {menuNode}
    </div>
  );
}

const FILE_PICKER_TIP_SHOW_MS = 480;
const FILE_PICKER_TIP_HIDE_MS = 140;

/** Cell tooltip via portal so scroll containers do not clip it; max 5 lines then ellipsis (CSS). */
function FilePickerCellEllipsis({ tip, children }) {
  const raw = tip != null ? String(tip).trim() : "";
  const [visible, setVisible] = useState(false);
  const [tipStyle, setTipStyle] = useState({ left: 0, bottom: 0, maxW: 288 });
  const showTimerRef = useRef(null);
  const hideTimerRef = useRef(null);
  const anchorRef = useRef(null);

  const clearTimers = () => {
    if (showTimerRef.current) {
      window.clearTimeout(showTimerRef.current);
      showTimerRef.current = null;
    }
    if (hideTimerRef.current) {
      window.clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
    }
  };

  const placeTip = () => {
    const el = anchorRef.current;
    if (!el || !raw) return;
    const r = el.getBoundingClientRect();
    const maxW = Math.min(288, window.innerWidth - 16);
    let left = r.left;
    if (left + maxW > window.innerWidth - 8) left = Math.max(8, window.innerWidth - maxW - 8);
    if (left < 8) left = 8;
    const bottom = window.innerHeight - r.top + 8;
    setTipStyle({ left, bottom, maxW });
  };

  const onEnter = () => {
    if (!raw) return;
    clearTimers();
    showTimerRef.current = window.setTimeout(() => {
      showTimerRef.current = null;
      placeTip();
      setVisible(true);
    }, FILE_PICKER_TIP_SHOW_MS);
  };

  const onLeave = () => {
    clearTimers();
    hideTimerRef.current = window.setTimeout(() => {
      hideTimerRef.current = null;
      setVisible(false);
    }, FILE_PICKER_TIP_HIDE_MS);
  };

  useEffect(() => {
    if (!visible) return;
    const onScroll = () => setVisible(false);
    window.addEventListener("scroll", onScroll, true);
    return () => window.removeEventListener("scroll", onScroll, true);
  }, [visible]);

  useEffect(() => () => clearTimers(), []);

  if (!raw) {
    return <span className="file-picker-cell-ellipsis">{children}</span>;
  }

  return (
    <>
      <span
        ref={anchorRef}
        className="file-picker-cell-ellipsis"
        onMouseEnter={onEnter}
        onMouseLeave={onLeave}
      >
        {children}
      </span>
      {visible &&
        typeof document !== "undefined" &&
        createPortal(
          <div
            className="file-picker-cell-tip-popup"
            style={{
              position: "fixed",
              left: tipStyle.left,
              bottom: tipStyle.bottom,
              maxWidth: tipStyle.maxW,
              zIndex: 13000,
            }}
            role="tooltip"
          >
            {raw}
          </div>,
          document.body
        )}
    </>
  );
}

function FilePickerModal({
  loading,
  listError,
  files,
  draftSelected,
  draftSelectedCount,
  onToggleFile,
  onSelectAllFiltered,
  onCancel,
  onApply,
  applyDisabled,
  onOverlayMouseDown,
  declFolderCount,
  procFolderCount,
  onOpenDeclarationsFolder,
  openrouterCostHint = { kind: "hidden" },
}) {
  const selectedCount =
    draftSelectedCount != null ? draftSelectedCount : draftSelected.size;
  const [search, setSearch] = useState("");
  const [searchPost, setSearchPost] = useState("");
  const [searchWorkplace, setSearchWorkplace] = useState("");
  const [tableSort, setTableSort] = useState({ col: null, dir: "asc" });
  const [searchPanelOpen, setSearchPanelOpen] = useState(false);
  /** Lock the table frame height during search animation — modal does not grow/shrink. */
  const [lockedTableWrapPx, setLockedTableWrapPx] = useState(null);
  const innerRef = useRef(null);
  const fpBodyInnerRef = useRef(null);
  const tableWrapRef = useRef(null);

  const hasFilter = search.trim() !== "" || searchPost.trim() !== "" || searchWorkplace.trim() !== "";

  useLayoutEffect(() => {
    const host = fpBodyInnerRef.current;
    const inner = innerRef.current;
    if (!host || !inner) return;
    host.style.setProperty("--fp-search-h", `${inner.offsetHeight}px`);
  }, []);

  useEffect(() => {
    if (searchPanelOpen || lockedTableWrapPx == null) return undefined;
    const id = window.setTimeout(() => {
      setLockedTableWrapPx(null);
    }, FILE_PICKER_SEARCH_REVEAL_MS);
    return () => window.clearTimeout(id);
  }, [searchPanelOpen, lockedTableWrapPx]);

  const handleToggleSearch = () => {
    const reduced =
      typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (searchPanelOpen) {
      if (hasFilter) {
        setSearch("");
        setSearchPost("");
        setSearchWorkplace("");
      }
      setSearchPanelOpen(false);
      if (reduced) setLockedTableWrapPx(null);
      return;
    }
    const wrap = tableWrapRef.current;
    if (wrap) setLockedTableWrapPx(Math.round(wrap.getBoundingClientRect().height));
    setSearchPanelOpen(true);
  };

  const q = search.trim().toLowerCase();
  const qPost = searchPost.trim().toLowerCase();
  const qWork = searchWorkplace.trim().toLowerCase();

  const filtered = files.filter((f) => {
    const name = String(f.name || "").toLowerCase();
    const decl = String(f.full_name || "").toLowerCase();
    const pos = String(f.position || "").toLowerCase();
    const wp = String(f.workplace || "").toLowerCase();
    if (q && !name.includes(q) && !decl.includes(q)) return false;
    if (qPost && !pos.includes(qPost)) return false;
    if (qWork && !wp.includes(qWork)) return false;
    return true;
  });

  const displayRows = tableSort.col
    ? [...filtered].sort((a, b) => {
        let va, vb;
        switch (tableSort.col) {
          case "name":      va = (a.name || "").toLowerCase();      vb = (b.name || "").toLowerCase();      break;
          case "full_name": va = (a.full_name || "").toLowerCase(); vb = (b.full_name || "").toLowerCase(); break;
          case "year":      va = Number(a.declaration_year) || 0;   vb = Number(b.declaration_year) || 0;   break;
          case "workplace": va = (a.workplace || "").toLowerCase(); vb = (b.workplace || "").toLowerCase(); break;
          default:          va = ""; vb = "";
        }
        if (typeof va === "number") {
          return tableSort.dir === "asc" ? va - vb : vb - va;
        }
        const cmp = va.localeCompare(vb, "uk");
        return tableSort.dir === "asc" ? cmp : -cmp;
      })
    : filtered;

  const allFilteredSelected =
    displayRows.length > 0 && displayRows.every((f) => draftSelected.has(f.name));

  const onSortCol = (col) => {
    if (loading) return;
    setTableSort((prev) => ({
      col,
      dir: prev.col === col && prev.dir === "asc" ? "desc" : "asc",
    }));
  };

  const sortIcon = (col) => {
    if (tableSort.col !== col) return <i className="file-picker-col-sort-icon">↕</i>;
    return (
      <i className="file-picker-col-sort-icon">
        {tableSort.dir === "asc" ? "↑" : "↓"}
      </i>
    );
  };

  const thClass = (col) =>
    `sortable-col${tableSort.col === col ? " sortable-col--active" : ""}`;

  return (
    <div className="cloud-modals-stack">
      <div
        className="cloud-modal-overlay"
        role="presentation"
        onMouseDown={(e) => {
          if (e.target === e.currentTarget) onOverlayMouseDown();
        }}
      >
        <div
          className="cloud-modal file-picker-modal"
          onMouseDown={(e) => e.stopPropagation()}
        >
          <div className="cloud-modal-title file-picker-modal-title">
            <span>Файли у папці декларацій</span>
            <div className="file-picker-modal-title-end">
              <span
                className={`file-picker-found-count${hasFilter ? " file-picker-found-count--visible" : ""}`}
                aria-hidden={!hasFilter}
              >
                Знайдено: {displayRows.length}
              </span>
              <button
                type="button"
                className={`file-picker-search-toggle${searchPanelOpen ? " file-picker-search-toggle--open" : ""}${hasFilter && !searchPanelOpen ? " file-picker-search-toggle--has-filter" : ""}`}
                onClick={handleToggleSearch}
                aria-expanded={searchPanelOpen}
                aria-controls="fp-search-panel"
                aria-label={searchPanelOpen ? "Сховати фільтри" : "Показати фільтри"}
              >
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <circle cx="6.5" cy="6.5" r="4" />
                  <line x1="10" y1="10" x2="14" y2="14" />
                </svg>
                {hasFilter && !searchPanelOpen && (
                  <span className="file-picker-search-toggle__dot" aria-label="є активні фільтри" />
                )}
              </button>
            </div>
          </div>
          <div className="cloud-modal-body file-picker-modal-body">
            <div
              ref={fpBodyInnerRef}
              className={`file-picker-modal-body-inner${loading ? " file-picker-modal-body-inner--loading" : ""}`}
            >
              {loading ? (
                <div
                  className="file-picker-loading-overlay file-picker-loading-overlay--modal"
                  aria-busy="true"
                  aria-live="polite"
                >
                  <div className="file-picker-spinner" aria-hidden />
                  <span className="file-picker-loading-text">Завантаження списку декларацій…</span>
                </div>
              ) : null}
              <div
                ref={tableWrapRef}
                className={`file-picker-table-wrap${lockedTableWrapPx != null ? " file-picker-table-wrap--height-locked" : ""}`}
                style={lockedTableWrapPx != null ? { height: lockedTableWrapPx } : undefined}
              >
                <div
                  id="fp-search-panel"
                  className={`file-picker-search-panel${searchPanelOpen ? " file-picker-search-panel--open" : ""}`}
                >
                  <div className="file-picker-search-row" ref={innerRef} role="search" aria-label="Фільтри списку">
                    <div className="file-picker-search-cell file-picker-search-cell--span4">
                      <input
                        className="field-input"
                        type="search"
                        placeholder="Пошук за іменем файлу або ПІБ…"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        disabled={loading}
                        aria-label="Пошук за іменем файлу або ПІБ"
                        tabIndex={searchPanelOpen ? 0 : -1}
                      />
                    </div>
                    <div className="file-picker-search-cell file-picker-search-cell--col5">
                      <input
                        className="field-input"
                        type="search"
                        placeholder="Пошук за посадою…"
                        value={searchPost}
                        onChange={(e) => setSearchPost(e.target.value)}
                        disabled={loading}
                        aria-label="Пошук за посадою"
                        tabIndex={searchPanelOpen ? 0 : -1}
                      />
                    </div>
                    <div className="file-picker-search-cell file-picker-search-cell--col6">
                      <input
                        className="field-input"
                        type="search"
                        placeholder="Пошук за місцем роботи…"
                        value={searchWorkplace}
                        onChange={(e) => setSearchWorkplace(e.target.value)}
                        disabled={loading}
                        aria-label="Пошук за місцем роботи"
                        tabIndex={searchPanelOpen ? 0 : -1}
                      />
                    </div>
                  </div>
                </div>
                {listError ? <div className="file-picker-list-error">{listError}</div> : null}
                <div className="file-picker-table-scroll">
                  <table className="file-picker-table">
                  <colgroup>
                    <col className="col-cb" />
                    <col className="col-file" />
                    <col className="col-decl" />
                    <col className="col-year" />
                    <col className="col-pos" />
                    <col className="col-wp" />
                  </colgroup>
                  <thead>
                    <tr>
                      <th className="col-cb file-picker-th-cb" scope="col" aria-label="Усі видимі рядки">
                        <input
                          type="checkbox"
                          checked={displayRows.length > 0 && allFilteredSelected}
                          ref={(el) => {
                            if (!el) return;
                            el.indeterminate =
                              !allFilteredSelected &&
                              displayRows.some((f) => draftSelected.has(f.name));
                          }}
                          onChange={() => onSelectAllFiltered(displayRows)}
                          disabled={loading || displayRows.length === 0}
                          aria-label="Усі видимі рядки"
                        />
                      </th>
                      <th className={thClass("name")} onClick={() => onSortCol("name")}>
                        Файл{sortIcon("name")}
                      </th>
                      <th className={thClass("full_name")} onClick={() => onSortCol("full_name")}>
                        Декларант{sortIcon("full_name")}
                      </th>
                      <th className={thClass("year")} onClick={() => onSortCol("year")}>
                        Рік{sortIcon("year")}
                      </th>
                      <th>Посада</th>
                      <th className={thClass("workplace")} onClick={() => onSortCol("workplace")}>
                        Місце роботи{sortIcon("workplace")}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {displayRows.map((f) => {
                      const name = f.name || "";
                      const full = f.full_name || "";
                      const yr = f.declaration_year != null && f.declaration_year !== "" ? String(f.declaration_year) : "";
                      const pos = f.position || "";
                      const wp = f.workplace || "";
                      const checked = draftSelected.has(name);
                      return (
                        <tr key={name}>
                          <td>
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => onToggleFile(name)}
                              aria-label={`Вибрати ${name}`}
                            />
                          </td>
                          <td>
                            <FilePickerCellEllipsis tip={name}>{name}</FilePickerCellEllipsis>
                          </td>
                          <td>
                            <FilePickerCellEllipsis tip={full}>{full || "—"}</FilePickerCellEllipsis>
                          </td>
                          <td>
                            <FilePickerCellEllipsis tip={yr}>{yr || "—"}</FilePickerCellEllipsis>
                          </td>
                          <td>
                            <FilePickerCellEllipsis tip={pos}>{pos || "—"}</FilePickerCellEllipsis>
                          </td>
                          <td>
                            <FilePickerCellEllipsis tip={wp}>{wp || "—"}</FilePickerCellEllipsis>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>
          <div className="cloud-modal-actions file-picker-modal-actions">
            <div className="file-picker-modal-footer-stats">
              <button
                type="button"
                className="file-picker-open-folder-btn"
                onClick={onOpenDeclarationsFolder}
                title="Відкрити папку декларацій"
                aria-label="Відкрити папку декларацій"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
                </svg>
              </button>
              Файлів: <strong>{declFolderCount}</strong> Оброблено: <strong>{procFolderCount}</strong>
            </div>
            {openrouterCostHint &&
            openrouterCostHint.kind !== "hidden" &&
            openrouterCostHint.kind !== "empty" ? (
              <div
                className={`file-picker-modal-footer-cost${
                  openrouterCostHint.kind === "no_rates" || openrouterCostHint.kind === "no_model"
                    ? " file-picker-modal-footer-cost--warn"
                    : ""
                }`}
                title={openrouterCostHint.kind === "ok" ? openrouterCostHint.title : undefined}
              >
                {openrouterCostHint.kind === "ok" ? (
                  <span className="file-picker-modal-footer-cost--muted">{openrouterCostHint.line}</span>
                ) : (
                  openrouterCostHint.line
                )}
              </div>
            ) : null}
            <div className="file-picker-modal-actions-end">
              <button type="button" className="btn-secondary" onClick={onCancel}>
                Скасувати
              </button>
              <button type="button" className="btn-primary" onClick={onApply} disabled={applyDisabled}>
                Застосувати ({selectedCount} вибрано)
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [inputDir, setInputDir] = useState("dataset_declarations");
  const [processedDir, setProcessedDir] = useState("dataset_declarations_done");
  const [outputJsonl, setOutputJsonl] = useState("analysis_results.jsonl");
  const [errorsJsonl, setErrorsJsonl] = useState("analysis_errors.jsonl");
  const [summaryCsv, setSummaryCsv] = useState("report_summary.csv");
  const [findingsCsv, setFindingsCsv] = useState("report_findings.csv");
  const [tableHtml, setTableHtml] = useState("report_table.html");

  const [maxFiles, setMaxFiles] = useState(1);
  const [fileQueueMode, setFileQueueMode] = useState("sort"); // "sort" | "pick"
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [sortOrder, setSortOrder] = useState("alpha");
  const [filePickerOpen, setFilePickerOpen] = useState(false);
  const [sortDropdownOpen, setSortDropdownOpen] = useState(false);
  const [availableFiles, setAvailableFiles] = useState([]);
  const [filePickerLoading, setFilePickerLoading] = useState(false);
  const [filePickerListError, setFilePickerListError] = useState("");
  const [pickerDeclCount, setPickerDeclCount] = useState(0);
  const [pickerProcCount, setPickerProcCount] = useState(0);
  const [filePickerDraft, setFilePickerDraft] = useState(() => new Set());
  const sortDropdownAnchorRef = useRef(null);
  const sortDropdownMenuRef = useRef(null);
  const filePickerCacheRef = useRef({
    inputDir: "",
    processedDir: "",
    fpInput: "",
    fpProc: "",
    files: [],
  });
  const filePickerLoadIdRef = useRef(0);
  const [model, setModel] = useState("llama3.1");
  const [models, setModels] = useState([]);
  const [cloudModels, setCloudModels] = useState([]);
  const [host, setHost] = useState("http://127.0.0.1:11434");
  const [timeout, setTimeout_] = useState(600);
  const [retries, setRetries] = useState(2);
  const [retryDelay, setRetryDelay] = useState(5);
  const [maxChars, setMaxChars] = useState(64000);
  const [numPredict, setNumPredict] = useState(16000);

  const [makeReport, setMakeReport] = useState(true);
  const [moveProcessed, setMoveProcessed] = useState(true);
  const [noDedupe, setNoDedupe] = useState(false);
  const [auditModeEnabled, setAuditModeEnabled] = useState(false);
  const [auditModeDir, setAuditModeDir] = useState("audit");
  const [auditSettingsOpen, setAuditSettingsOpen] = useState(false);
  const [auditCaptureRawDeclaration, setAuditCaptureRawDeclaration] = useState(true);
  const [auditCaptureCompactDeclaration, setAuditCaptureCompactDeclaration] = useState(true);
  const [auditCaptureRequestPayload, setAuditCaptureRequestPayload] = useState(true);
  const [auditCaptureResponseRaw, setAuditCaptureResponseRaw] = useState(true);
  const [auditCaptureResponseParsed, setAuditCaptureResponseParsed] = useState(true);
  const [auditCaptureNormalizedAnalysis, setAuditCaptureNormalizedAnalysis] = useState(true);
  const [auditCaptureAttemptMeta, setAuditCaptureAttemptMeta] = useState(true);
  const [compactLegacyPayload, setCompactLegacyPayload] = useState(false);
  const [debugUiMode, setDebugUiMode] = useState(false);
  /** Visual feedback after gesture unlock (not used when debug UI was already on at launch). */
  const [logoUnlockRippling, setLogoUnlockRippling] = useState(false);
  const [debugBadgeReveal, setDebugBadgeReveal] = useState(false);
  const [showSystemMetrics, setShowSystemMetrics] = useState(false);
  const [playCompletionSound, setPlayCompletionSound] = useState(true);
  const [thinkEventDebug, setThinkEventDebug] = useState(false);
  /** idle | pulse (after successful pipeline) | fade-out (after "open report" click) */
  const [reportBtnPulse, setReportBtnPulse] = useState("idle");
  const [pipelineMaxConcurrent, setPipelineMaxConcurrent] = useState(1);
  const [cloudMode, setCloudMode] = useState(false);
  const [cloudProvider, setCloudProvider] = useState("ollama");
  const [cloudHost, setCloudHost] = useState("https://ollama.com");
  const [cloudModel, setCloudModel] = useState("");
  const [cloudApiKey, setCloudApiKey] = useState("");
  // OpenRouter is a separate, isolated path; its data is stored independently of Ollama Cloud.
  const [openrouterHost, setOpenrouterHost] = useState("https://openrouter.ai/api/v1");
  const [openrouterModel, setOpenrouterModel] = useState("meta-llama/llama-3.3-70b-instruct");
  const [openrouterApiKey, setOpenrouterApiKey] = useState("");
  const [openrouterModels, setOpenrouterModels] = useState([]);
  /** id → short OpenRouter price string ($/1M in/out) for the dropdown */
  const [openrouterModelPricing, setOpenrouterModelPricing] = useState({});
  /** id → { prompt, completion } USD per token (from /models for catalog estimates) */
  const [openrouterPricingPerToken, setOpenrouterPricingPerToken] = useState({});
  const [openrouterCreditsLoading, setOpenrouterCreditsLoading] = useState(false);
  const [openrouterCreditsLabel, setOpenrouterCreditsLabel] = useState("");
  const [openrouterCreditsHint, setOpenrouterCreditsHint] = useState("");
  const [showCloudModal, setShowCloudModal] = useState(false);
  const [showCloudComparisonModal, setShowCloudComparisonModal] = useState(false);
  const [cloudComparisonCount, setCloudComparisonCount] = useState(2);
  const [cloudComparisonSeedModels, setCloudComparisonSeedModels] = useState(["", "", "", ""]);
  const [cloudComparisonEnabled, setCloudComparisonEnabled] = useState(false);
  const [cloudCompareBusy, setCloudCompareBusy] = useState(false);
  const [showCloudWarning, setShowCloudWarning] = useState(false);
  const [cloudWarningAcceptedSession, setCloudWarningAcceptedSession] = useState(false);
  const [cloudDraft, setCloudDraft] = useState({
    provider: "ollama",
    ollama: {
      host: "https://ollama.com",
      model: "",
      api_key: "",
    },
    openrouter: {
      host: "https://openrouter.ai/api/v1",
      model: "meta-llama/llama-3.3-70b-instruct",
      api_key: "",
    },
  });

  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [requestSettingsModalOpen, setRequestSettingsModalOpen] = useState(false);
  const [outputFilesModalOpen, setOutputFilesModalOpen] = useState(false);
  const [compactModeHelpOpen, setCompactModeHelpOpen] = useState(false);
  const [debugSettingsOpen, setDebugSettingsOpen] = useState(false);
  const [wipSettingsOpen, setWipSettingsOpen] = useState(false);
  const thinkEventDebugRef = useRef(false);
  const [showAboutProgramDock, setShowAboutProgramDock] = useState(true);
  const [aboutDockFadeIn, setAboutDockFadeIn] = useState(true);
  const [aboutProgramOpen, setAboutProgramOpen] = useState(false);
  const [welcomeModalOpen, setWelcomeModalOpen] = useState(false);
  const [showHeaderTaglines, setShowHeaderTaglines] = useState(true);
  const [headerSlogan, setHeaderSlogan] = useState("");
  const advPanelRef = useRef(null);
  const everOpenedAdvancedRef = useRef(false);
  const aboutDockDelayRef = useRef(null);
  const logoDebugUnlockTapCountRef = useRef(0);
  const logoDebugUnlockTimerRef = useRef(null);

  useLayoutEffect(() => {
    const el = advPanelRef.current;
    if (!el) return;
    if (advancedOpen) el.removeAttribute("inert");
    else el.setAttribute("inert", "");
  }, [advancedOpen]);

  useEffect(() => {
    if (aboutDockDelayRef.current) {
      clearTimeout(aboutDockDelayRef.current);
      aboutDockDelayRef.current = null;
    }
    if (advancedOpen) {
      everOpenedAdvancedRef.current = true;
      setShowAboutProgramDock(false);
      return;
    }
    if (!everOpenedAdvancedRef.current) {
      setShowAboutProgramDock(true);
      return;
    }
    setShowAboutProgramDock(false);
    const delayMs =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? 0
        : ADV_PANEL_COLLAPSE_MS;
    aboutDockDelayRef.current = window.setTimeout(() => {
      aboutDockDelayRef.current = null;
      setShowAboutProgramDock(true);
    }, delayMs);
    return () => {
      if (aboutDockDelayRef.current) {
        clearTimeout(aboutDockDelayRef.current);
        aboutDockDelayRef.current = null;
      }
    };
  }, [advancedOpen]);

  useEffect(() => {
    if (!showAboutProgramDock) {
      setAboutDockFadeIn(false);
      return;
    }
    if (!everOpenedAdvancedRef.current) {
      setAboutDockFadeIn(true);
      return;
    }
    setAboutDockFadeIn(false);
    const id = window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => setAboutDockFadeIn(true));
    });
    return () => window.cancelAnimationFrame(id);
  }, [showAboutProgramDock]);

  // DEEP_RESEARCH
  const [deepResearchOpen, setDeepResearchOpen] = useState(false);
  const [deepResearchTab, setDeepResearchTab] = useState("download");
  const [deepResearchUid, setDeepResearchUid] = useState("");
  const [deepResearchLoading, setDeepResearchLoading] = useState(false);
  const [deepResearchLoadingHint, setDeepResearchLoadingHint] = useState("");
  const [deepResearchDownloadProgress, setDeepResearchDownloadProgress] = useState(null);
  const deepResearchLoadingRef = useRef(false);
  const [deepResearchError, setDeepResearchError] = useState("");
  const [deepResearchActive, setDeepResearchActive] = useState(false);
  const [deepResearchFolders, setDeepResearchFolders] = useState([]);
  const [deepResearchFoldersLoading, setDeepResearchFoldersLoading] = useState(false);
  const [deepResearchSelectedFolder, setDeepResearchSelectedFolder] = useState("");
  const [parseModalOpen, setParseModalOpen] = useState(false);
  const [parseTab, setParseTab] = useState("single");
  const [parseDeclId, setParseDeclId] = useState("");
  const [parseBulkYear, setParseBulkYear] = useState(() => String(new Date().getFullYear()));
  const [parseBulkUseYear, setParseBulkUseYear] = useState(true);
  const [parseBulkQuery, setParseBulkQuery] = useState("");
  const [parseBulkCount, setParseBulkCount] = useState("10");
  const [parseBulkDeclarationType, setParseBulkDeclarationType] = useState("");
  const [parseBulkDocumentType, setParseBulkDocumentType] = useState("");
  const [parseBulkDir, setParseBulkDir] = useState("");
  const [parseLoading, setParseLoading] = useState(false);
  const [parseLoadingHint, setParseLoadingHint] = useState("");
  const [parseDownloadProgress, setParseDownloadProgress] = useState(null);
  const [parseError, setParseError] = useState("");
  const parseLoadingRef = useRef(false);
  const [dossierSummaryBusy, setDossierSummaryBusy] = useState(false);
  const [extraReportBusy, setExtraReportBusy] = useState(false);
  const [wipeBusy, setWipeBusy] = useState(false);
  const [wipeModalOpen, setWipeModalOpen] = useState(false);

  /** Session-only prompt overrides (debug); null = use project code defaults */
  const [sessionPromptOverrides, setSessionPromptOverrides] = useState(null);
  const [promptEditorOpen, setPromptEditorOpen] = useState(false);
  const [promptEditorTab, setPromptEditorTab] = useState("pipeline");
  const [promptDraft, setPromptDraft] = useState({
    pipelineSystem: "",
    pipelineUser: "",
    dossierSystem: "",
    dossierUser: "",
  });
  const [promptBuiltinLoading, setPromptBuiltinLoading] = useState(false);

  const [isRunning, setIsRunning] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [statusText, setStatusText] = useState("Очікує запуску");
  const [taskText, setTaskText] = useState("");
  const [progress, setProgress] = useState({ cur: 0, total: 0 });
  const [systemMetrics, setSystemMetrics] = useState(null);
  const [elapsedSec, setElapsedSec] = useState(0);
  const [runTimerVisible, setRunTimerVisible] = useState(false);
  const [runTimerExiting, setRunTimerExiting] = useState(false);

  const [logLines, setLogLines] = useState([]);
  const [logViewMode, setLogViewMode] = useState(readLogViewMode);
  const [visualEntries, setVisualEntries] = useState([]);
  const [pendingThink, setPendingThink] = useState("");
  const [activeProcessing, setActiveProcessing] = useState([]);
  const [exitingProcessing, setExitingProcessing] = useState([]);
  const exitingTimersRef = useRef(new Map());
  const processingEntry = useMemo(
    () => (activeProcessing.length === 1 ? activeProcessing[0] : null),
    [activeProcessing],
  );
  const [visualRunTotals, setVisualRunTotals] = useState(null);
  const [errorActionBusy, setErrorActionBusy] = useState(null);
  const [errorActionTargetFile, setErrorActionTargetFile] = useState(null);
  const logRef = useRef(null);
  const visualLogRef = useRef(null);
  const logViewModeRef = useRef(logViewMode);
  useEffect(() => {
    thinkEventDebugRef.current = thinkEventDebug;
  }, [thinkEventDebug]);
  const [usageStats, setUsageStats] = useState(null);
  const [usageStatsLoading, setUsageStatsLoading] = useState(false);
  const [dossierChartData, setDossierChartData] = useState(null);
  const [dossierChartLoading, setDossierChartLoading] = useState(false);
  const [dossierChartError, setDossierChartError] = useState("");
  const [dossierMainView, setDossierMainView] = useState("dossier");
  const dossierRefreshTimerRef = useRef(null);
  const [usageStatsError, setUsageStatsError] = useState("");
  const [modelListError, setModelListError] = useState("");
  const usageStatsReqRef = useRef(0);
  const [ready, setReady] = useState(false);
  /** One random slogan per session (next app launch picks a new one). */
  const sessionHeaderTaglineRef = useRef(null);
  const normalPathsSnapshotRef = useRef(null);
  const runStartedAtRef = useRef(null);
  const runTimerHideRef = useRef(null);
  /** Synchronous guard against double-clicking Start before isRunning re-renders (validate() is awaited first). */
  const startInFlightRef = useRef(false);
  const autosaveTimerRef = useRef(null);
  const lastAutosavedPayloadRef = useRef("");
  const autosaveFlashTimerRef = useRef(null);
  const autosaveIndicatorFadeTimerRef = useRef(null);
  const [autosaveStatus, setAutosaveStatus] = useState("idle");
  const [autosaveIndicatorMounted, setAutosaveIndicatorMounted] = useState(false);
  const [autosaveIndicatorVisible, setAutosaveIndicatorVisible] = useState(false);
  /** One AudioContext per session: autoplay policy requires resume in a user gesture before long awaits. */
  const pipelineAudioContextRef = useRef(null);

  const primePipelineAudioContext = useCallback(() => {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      let ctx = pipelineAudioContextRef.current;
      if (!ctx) {
        ctx = new Ctx();
        pipelineAudioContextRef.current = ctx;
      }
      if (ctx.state === "suspended") {
        void ctx.resume();
      }
    } catch (_) {}
  }, []);

  const playPipelineDoneSound = useCallback(async () => {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      let ctx = pipelineAudioContextRef.current;
      if (!ctx) {
        ctx = new Ctx();
        pipelineAudioContextRef.current = ctx;
      }
      if (ctx.state === "suspended") {
        await ctx.resume();
      }
      const now = ctx.currentTime;
      const master = ctx.createGain();
      master.gain.setValueAtTime(0.0001, now);
      master.gain.exponentialRampToValueAtTime(0.05, now + 0.03);
      master.gain.exponentialRampToValueAtTime(0.0001, now + 0.9);
      master.connect(ctx.destination);

      const tone = (freq, start, dur, gain = 0.045) => {
        const osc = ctx.createOscillator();
        const g = ctx.createGain();
        osc.type = "sine";
        osc.frequency.setValueAtTime(freq, start);
        g.gain.setValueAtTime(0.0001, start);
        g.gain.exponentialRampToValueAtTime(gain, start + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, start + dur);
        osc.connect(g);
        g.connect(master);
        osc.start(start);
        osc.stop(start + dur + 0.03);
      };

      tone(523.25, now, 0.24, 0.04); // C5
      tone(659.25, now + 0.18, 0.26, 0.045); // E5
      tone(783.99, now + 0.36, 0.34, 0.05); // G5
    } catch (_) {}
  }, []);

  const appendLog = useCallback((text) => {
    const lines = text.split("\n").filter((l) => l.trim() !== "" || text.endsWith("\n"));
    setLogLines((prev) => [...prev, ...lines.filter((l) => l !== "")].slice(-2000));
  }, []);

  const scheduleProcessingExit = useCallback((procEntry) => {
    const file = String(procEntry?.source_file || "").trim();
    if (!file) return;
    setExitingProcessing((prev) => {
      const without = prev.filter((e) => e.source_file !== file);
      return [...without, procEntry];
    });
    const existing = exitingTimersRef.current.get(file);
    if (existing) window.clearTimeout(existing);
    const timerId = window.setTimeout(() => {
      setExitingProcessing((prev) => prev.filter((e) => e.source_file !== file));
      exitingTimersRef.current.delete(file);
    }, MODAL_TAB_SWITCH_MS);
    exitingTimersRef.current.set(file, timerId);
  }, []);

  const resetLogSession = useCallback(() => {
    exitingTimersRef.current.forEach((id) => window.clearTimeout(id));
    exitingTimersRef.current.clear();
    setLogLines([]);
    setVisualEntries([]);
    setPendingThink("");
    setActiveProcessing([]);
    setExitingProcessing([]);
    setVisualRunTotals(null);
    setErrorActionBusy(null);
    setErrorActionTargetFile(null);
  }, []);

  const setLogViewModePersist = useCallback((mode) => {
    setLogViewMode(mode);
    logViewModeRef.current = mode;
    try {
      localStorage.setItem(LOG_VIEW_MODE_KEY, mode);
    } catch (_) {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    logViewModeRef.current = logViewMode;
  }, [logViewMode]);

  useEffect(() => {
    deepResearchLoadingRef.current = deepResearchLoading;
  }, [deepResearchLoading]);

  useEffect(() => {
    parseLoadingRef.current = parseLoading;
  }, [parseLoading]);

  const refreshUsageStats = useCallback(async () => {
    if (!api()) return;
    const reqId = ++usageStatsReqRef.current;
    setUsageStatsLoading(true);
    setUsageStatsError("");
    try {
      const raw = await api().get_usage_dashboard_stats({
        output_jsonl: outputJsonl,
        no_dedupe: noDedupe,
        input_dir: inputDir,
      });
      if (reqId !== usageStatsReqRef.current) return;
      const parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (!parsed?.ok) {
        setUsageStatsError(parsed?.error || "Помилка завантаження статистики");
        setUsageStats(null);
        return;
      }
      setUsageStats(parsed);
    } catch (e) {
      if (reqId !== usageStatsReqRef.current) return;
      setUsageStatsError(String(e));
      setUsageStats(null);
    } finally {
      if (reqId === usageStatsReqRef.current) {
        setUsageStatsLoading(false);
      }
    }
  }, [outputJsonl, noDedupe, inputDir]);

  const refreshDossierCharts = useCallback(async () => {
    if (!api() || !deepResearchActive || !isDeepResearchInput(inputDir)) return;
    setDossierChartLoading(true);
    setDossierChartError("");
    try {
      const raw = await api().get_dossier_chart_data({
        input_dir: inputDir,
        output_jsonl: outputJsonl,
        errors_jsonl: errorsJsonl,
        no_dedupe: noDedupe,
      });
      const parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (!parsed?.ok) {
        setDossierChartError(parsed?.error || "Помилка завантаження графіків досьє");
        setDossierChartData(null);
        return;
      }
      setDossierChartData(parsed);
    } catch (e) {
      setDossierChartError(String(e));
      setDossierChartData(null);
    } finally {
      setDossierChartLoading(false);
    }
  }, [deepResearchActive, inputDir, outputJsonl, errorsJsonl, noDedupe]);

  const scheduleDossierChartsRefresh = useCallback(() => {
    if (!deepResearchActive || !isDeepResearchInput(inputDir)) return;
    if (dossierRefreshTimerRef.current) {
      window.clearTimeout(dossierRefreshTimerRef.current);
    }
    dossierRefreshTimerRef.current = window.setTimeout(() => {
      dossierRefreshTimerRef.current = null;
      void refreshDossierCharts();
    }, 300);
  }, [deepResearchActive, inputDir, refreshDossierCharts]);

  const showDossierLive = deepResearchActive && isDeepResearchInput(inputDir);
  const showUsageDashboard = !showDossierLive && !isRunning && logLines.length === 0;
  const dossierProgress = useMemo(
    () => dossierProgressMeta(dossierChartData, isRunning),
    [dossierChartData, isRunning],
  );

  const pendingErrorCount = useMemo(
    () =>
      visualEntries.filter((e) => e.action_required && !e.resolution).length,
    [visualEntries]
  );

  const handlePipelineErrorAction = useCallback(
    async (file, action, limits = {}) => {
      if (!api() || !file) return;
      setErrorActionBusy(file);
      try {
        const payload = {
          file,
          action,
          ...limits,
        };
        if (action === "raise_limits") {
          payload.max_chars = maxChars;
          payload.num_predict = numPredict;
        }
        await api().pipeline_error_action(payload);
      } catch (e) {
        appendLog(`[ПОМИЛКА] Дія по помилці: ${e}\n`);
      } finally {
        setErrorActionBusy(null);
      }
    },
    [appendLog, maxChars, numPredict]
  );

  const handleErrorRaiseLimits = useCallback((file) => {
    setErrorActionTargetFile(file);
    setRequestSettingsModalOpen(true);
  }, []);

  const dismissRequestSettingsModal = useCallback(() => {
    setRequestSettingsModalOpen(false);
    setErrorActionTargetFile(null);
  }, []);

  const confirmRequestSettingsModal = useCallback(() => {
    const target = errorActionTargetFile;
    setRequestSettingsModalOpen(false);
    setErrorActionTargetFile(null);
    if (target) {
      void handlePipelineErrorAction(target, "raise_limits");
    }
  }, [errorActionTargetFile, handlePipelineErrorAction]);

  useEffect(() => {
    if (!ready || !api()) return;
    if (showUsageDashboard) {
      refreshUsageStats();
    }
  }, [ready, showUsageDashboard, refreshUsageStats]);

  useEffect(() => {
    if (!ready || !api() || !showDossierLive) return;
    void refreshDossierCharts();
  }, [ready, showDossierLive, inputDir, outputJsonl, errorsJsonl, refreshDossierCharts]);

  useEffect(() => {
    if (!showDossierLive) return undefined;
    return () => {
      if (dossierRefreshTimerRef.current) {
        window.clearTimeout(dossierRefreshTimerRef.current);
        dossierRefreshTimerRef.current = null;
      }
    };
  }, [showDossierLive]);

  useEffect(() => {
    if (!showDossierLive) return;
    scheduleDossierChartsRefresh();
  }, [showDossierLive, visualEntries, activeProcessing, scheduleDossierChartsRefresh]);

  useEffect(() => {
    if (!showDossierLive || isRunning) return;
    void refreshDossierCharts();
  }, [showDossierLive, isRunning, refreshDossierCharts]);

  useEffect(() => {
    window._onLogLine = (line) => {
      const trimmed = line.trim();

      const totalsEv = VISUAL_RUN_TOTALS_RE.exec(trimmed);
      if (totalsEv) {
        try {
          setVisualRunTotals(JSON.parse(totalsEv[1]));
        } catch (_) {
          /* ignore malformed */
        }
        return;
      }

      const reviewEv = PIPELINE_ERR_REVIEW_RE.exec(trimmed);
      if (reviewEv) {
        try {
          const data = JSON.parse(reviewEv[1]);
          const n = Number(data?.count) || 0;
          if (n > 0) {
            setTaskText(`Очікує рішення: ${n} декларацій`);
          }
        } catch (_) {
          /* ignore malformed */
        }
        return;
      }

      const deepDlEv = DEEP_DOWNLOAD_PROGRESS_RE.exec(trimmed);
      if (deepDlEv) {
        try {
          const data = JSON.parse(deepDlEv[1]);
          if (deepResearchLoadingRef.current) {
            setDeepResearchDownloadProgress({
              found: Number(data.found) || 0,
              downloaded: Number(data.downloaded) || 0,
              skipped: Number(data.skipped) || 0,
              page: Number(data.page) || 0,
              phase: String(data.phase || ""),
            });
            setDeepResearchLoadingHint(formatDeepDownloadProgress(data));
          }
        } catch (_) {
          /* ignore malformed */
        }
        return;
      }

      const nazkDlEv = NAZK_DOWNLOAD_PROGRESS_RE.exec(trimmed);
      if (nazkDlEv) {
        try {
          const data = JSON.parse(nazkDlEv[1]);
          if (parseLoadingRef.current) {
            setParseDownloadProgress({
              target: Number(data.target) || 0,
              saved: Number(data.saved) || 0,
              skipped: Number(data.skipped) || 0,
              page: Number(data.page) || 0,
              phase: String(data.phase || ""),
            });
            setParseLoadingHint(formatNazkDownloadProgress(data));
          }
        } catch (_) {
          /* ignore malformed */
        }
        return;
      }

      const visualEv = VISUAL_LOG_RE.exec(trimmed);
      if (visualEv) {
        try {
          const entry = JSON.parse(visualEv[1]);
          if (entry.status === "PROCESSING") {
            setActiveProcessing((prev) => upsertActiveProcessing(prev, entry));
          } else {
            const file = String(entry.source_file || "").trim();
            setActiveProcessing((prev) => {
              const proc = file ? prev.find((e) => e.source_file === file) : null;
              if (proc) scheduleProcessingExit(proc);
              return removeActiveProcessing(prev, entry);
            });
            setVisualEntries((prev) => upsertVisualEntry(prev, entry));
          }
        } catch (_) {
          /* ignore malformed */
        }
        return;
      }

      const think = THINK_EVENT_RE.exec(trimmed);
      if (think) {
        if (thinkEventDebugRef.current) {
          const text = (think[1] || "").trim();
          if (text) {
            setPendingThink(text);
            if (logViewModeRef.current === "text") appendLog(`[THINK] ${text}`);
          }
        }
        return;
      }

      appendLog(line);

      const totalEv = PIPELINE_TOTAL_RE.exec(trimmed);
      if (totalEv) {
        const total = Number(totalEv[1]);
        setProgress({ cur: 0, total });
        setTaskText("Обробка декларацій…");
        return;
      }
      const foundEv = PIPELINE_FOUND_RE.exec(trimmed);
      if (foundEv) {
        const total = Number(foundEv[1]);
        setProgress((prev) => ({ cur: prev.cur || 0, total }));
        setTaskText("Обробка декларацій…");
        return;
      }
      const m = PROGRESS_RE.exec(trimmed);
      if (m) {
        const [, cur, total, status] = m;
        const curN = Number(cur);
        const totalN = Number(total);
        setProgress({ cur: curN, total: totalN });
        setPendingThink("");
        const icon = status === "OK" ? "\u2713" : status === "LIMIT_EXCEEDED" ? "\u26a0" : "\u2717";
        setTaskText(`Обробка декларацій ${icon}`);
      }
    };
    return () => { delete window._onLogLine; };
  }, [appendLog, scheduleProcessingExit]);

  useEffect(() => {
    if (reportBtnPulse !== "fade-out") return undefined;
    const t = window.setTimeout(() => setReportBtnPulse("idle"), REPORT_BTN_PULSE_FADE_MS);
    return () => window.clearTimeout(t);
  }, [reportBtnPulse]);

  const dismissReportBtnPulse = useCallback(() => {
    setReportBtnPulse((prev) => {
      if (prev === "idle") return prev;
      const reduced =
        typeof window !== "undefined" &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      return reduced ? "idle" : "fade-out";
    });
  }, []);

  const loadModels = useCallback(async (hostUrl) => {
    if (!api()) return;
    setModelListError("");
    try {
      const list = await api().fetch_models(hostUrl || "http://127.0.0.1:11434");
      if (Array.isArray(list) && list.length > 0) {
        setModels(sortModelsAZ(list));
      }
    } catch (e) {
      setModelListError(`Не вдалося оновити список моделей Ollama: ${e}`);
    }
  }, []);

  const loadCloudModels = useCallback(async (hostUrl, apiKey) => {
    if (!api()) return;
    setModelListError("");
    try {
      const list = await api().fetch_models(
        hostUrl || "https://ollama.com",
        apiKey || ""
      );
      if (Array.isArray(list) && list.length > 0) {
        setCloudModels(sortModelsAZ(list));
      }
    } catch (e) {
      setModelListError(`Не вдалося оновити список cloud-моделей: ${e}`);
    }
  }, []);

  // Alternate path: load the model list from OpenRouter /models.
  const loadOpenrouterModels = useCallback(async (hostUrl, apiKey) => {
    if (!api()) return;
    setModelListError("");
    try {
      const bridge = api();
      const host = hostUrl || "https://openrouter.ai/api/v1";
      const key = apiKey || "";
      if (typeof bridge.fetch_openrouter_models_enriched === "function") {
        const raw = await bridge.fetch_openrouter_models_enriched(host, key);
        const pack = typeof raw === "string" ? JSON.parse(raw) : raw;
        const list = Array.isArray(pack?.models) ? pack.models : [];
        const pricing = pack?.pricing && typeof pack.pricing === "object" ? pack.pricing : {};
        const ppt =
          pack?.pricing_per_token && typeof pack.pricing_per_token === "object"
            ? pack.pricing_per_token
            : {};
        if (list.length > 0) {
          setOpenrouterModels(sortModelsAZ(list));
        }
        setOpenrouterModelPricing(pricing);
        setOpenrouterPricingPerToken(ppt);
        return;
      }
      if (typeof bridge.fetch_openrouter_models === "function") {
        const list = await bridge.fetch_openrouter_models(host, key);
        if (Array.isArray(list) && list.length > 0) {
          setOpenrouterModels(sortModelsAZ(list));
        }
        setOpenrouterModelPricing({});
        setOpenrouterPricingPerToken({});
      }
    } catch (e) {
      setModelListError(`Не вдалося оновити список OpenRouter-моделей: ${e}`);
    }
  }, []);

  const refreshOpenrouterCredits = useCallback(async (hostUrl, apiKey) => {
    if (!api()) return;
    const bridge = api();
    if (typeof bridge.fetch_openrouter_credits !== "function") return;
    const host = (hostUrl || "").trim() || "https://openrouter.ai/api/v1";
    const key = String(apiKey || "").trim();
    if (!key) {
      setOpenrouterCreditsLabel("");
      setOpenrouterCreditsHint("");
      return;
    }
    setOpenrouterCreditsLoading(true);
    try {
      const raw = await bridge.fetch_openrouter_credits(host, key);
      const res = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (res?.ok && res.balance_label) {
        setOpenrouterCreditsLabel(String(res.balance_label));
        setOpenrouterCreditsHint("");
      } else {
        setOpenrouterCreditsLabel("");
        const msg = String(res?.message || "Не вдалося отримати баланс").trim();
        setOpenrouterCreditsHint(msg.length > 140 ? `${msg.slice(0, 137)}…` : msg);
      }
    } catch (e) {
      setOpenrouterCreditsLabel("");
      setOpenrouterCreditsHint(String(e));
    } finally {
      setOpenrouterCreditsLoading(false);
    }
  }, []);

  const applySettings = useCallback((s) => {
    if (!s || typeof s !== "object") return "";
    const isDebugMode = Boolean(s.debug_mode_ui);
    setDebugUiMode(isDebugMode);
    if (s.input_dir) setInputDir(s.input_dir);
    if (s.processed_dir) setProcessedDir(s.processed_dir);
    const normalInput = !isDeepResearchInput(s.input_dir || "");
    const pickReportPath = (key, raw) => {
      const v = String(raw || "").trim();
      if (!v) return null;
      if (normalInput && pathUnderDeepResearch(v)) return NORMAL_REPORT_PATH_DEFAULTS[key];
      return v;
    };
    const outJ = pickReportPath("outputJsonl", s.output_jsonl);
    if (outJ) setOutputJsonl(outJ);
    const errJ = pickReportPath("errorsJsonl", s.errors_jsonl);
    if (errJ) setErrorsJsonl(errJ);
    const sumC = pickReportPath("summaryCsv", s.summary_csv);
    if (sumC) setSummaryCsv(sumC);
    const findC = pickReportPath("findingsCsv", s.findings_csv);
    if (findC) setFindingsCsv(findC);
    const tbl = pickReportPath("tableHtml", s.table_html);
    if (tbl) setTableHtml(tbl);
    if (s.max_files !== undefined) setMaxFiles(s.max_files);
    const VALID_SORT_ORDERS = ["alpha", "alpha-desc", "mtime", "mtime-asc", "size", "size-asc"];
    if (VALID_SORT_ORDERS.includes(s.sort_order)) {
      setSortOrder(s.sort_order);
    }
    const savedSel = Array.isArray(s.selected_files)
      ? s.selected_files.map((x) => String(x || "").trim()).filter(Boolean)
      : [];
    let qMode = s.file_queue_mode === "pick" || s.file_queue_mode === "sort" ? s.file_queue_mode : null;
    if (qMode === null) {
      qMode = savedSel.length ? "pick" : "sort";
    }
    if (qMode === "pick" && savedSel.length === 0) {
      qMode = "sort";
    }
    setFileQueueMode(qMode);
    setSelectedFiles(qMode === "pick" ? savedSel : []);
    if (s.model) setModel(s.model);
    if (s.timeout !== undefined) setTimeout_(s.timeout);
    if (s.retries !== undefined) setRetries(s.retries);
    if (s.retry_delay !== undefined) setRetryDelay(s.retry_delay);
    if (s.max_chars !== undefined) setMaxChars(s.max_chars);
    if (s.num_predict !== undefined) setNumPredict(s.num_predict);
    if (s.make_report !== undefined) setMakeReport(isDebugMode ? s.make_report : true);
    if (s.move_processed !== undefined) setMoveProcessed(s.move_processed);
    if (s.no_dedupe !== undefined) setNoDedupe(s.no_dedupe);
    if (s.audit_mode_enabled !== undefined) setAuditModeEnabled(Boolean(s.audit_mode_enabled));
    if (s.audit_mode_dir !== undefined) setAuditModeDir(String(s.audit_mode_dir || "audit"));
    if (s.audit_capture_raw_declaration !== undefined) setAuditCaptureRawDeclaration(Boolean(s.audit_capture_raw_declaration));
    if (s.audit_capture_compact_declaration !== undefined) setAuditCaptureCompactDeclaration(Boolean(s.audit_capture_compact_declaration));
    if (s.audit_capture_request_payload !== undefined) setAuditCaptureRequestPayload(Boolean(s.audit_capture_request_payload));
    if (s.audit_capture_response_raw !== undefined) setAuditCaptureResponseRaw(Boolean(s.audit_capture_response_raw));
    if (s.audit_capture_response_parsed !== undefined) setAuditCaptureResponseParsed(Boolean(s.audit_capture_response_parsed));
    if (s.audit_capture_normalized_analysis !== undefined) setAuditCaptureNormalizedAnalysis(Boolean(s.audit_capture_normalized_analysis));
    if (s.audit_capture_attempt_meta !== undefined) setAuditCaptureAttemptMeta(Boolean(s.audit_capture_attempt_meta));
    if (s.compact_legacy_payload !== undefined) setCompactLegacyPayload(Boolean(s.compact_legacy_payload));
    if (s.show_system_metrics !== undefined) setShowSystemMetrics(Boolean(s.show_system_metrics));
    if (s.play_completion_sound !== undefined) setPlayCompletionSound(Boolean(s.play_completion_sound));
    if (s.think_event_debug !== undefined) setThinkEventDebug(Boolean(s.think_event_debug));
    if (s.pipeline_max_concurrent !== undefined) {
      const n = Number(s.pipeline_max_concurrent);
      setPipelineMaxConcurrent(
        Number.isFinite(n) ? Math.min(8, Math.max(1, Math.floor(n))) : 1
      );
    }
    if (s.cloud_mode !== undefined) setCloudMode(Boolean(s.cloud_mode));
    if (s.cloud_provider !== undefined) {
      setCloudProvider(s.cloud_provider === "openrouter" ? "openrouter" : "ollama");
    }
    if (s.cloud_host !== undefined) setCloudHost(s.cloud_host || "https://ollama.com");
    if (s.cloud_model !== undefined) setCloudModel(s.cloud_model || "");
    if (s.cloud_api_key !== undefined) setCloudApiKey(s.cloud_api_key || "");
    // Support migration from old groq_* keys to openrouter_*
    const orHost = s.openrouter_host ?? s.groq_host;
    const orModel = s.openrouter_model ?? s.groq_model;
    const orKey = s.openrouter_api_key ?? s.groq_api_key;
    if (orHost !== undefined) setOpenrouterHost(orHost || "https://openrouter.ai/api/v1");
    if (orModel !== undefined) setOpenrouterModel(orModel || "meta-llama/llama-3.3-70b-instruct");
    if (orKey !== undefined) setOpenrouterApiKey(orKey || "");
    if (s.compare_count !== undefined) {
      const n = Number(s.compare_count);
      setCloudComparisonCount(Number.isFinite(n) ? Math.min(4, Math.max(2, Math.floor(n))) : 2);
    }
    if (Array.isArray(s.compare_models)) {
      const next = s.compare_models
        .map((m) => String(m || "").trim())
        .filter(Boolean)
        .slice(0, 4);
      while (next.length < 4) next.push("");
      setCloudComparisonSeedModels(next);
    }
    if (s.compare_enabled !== undefined) {
      setCloudComparisonEnabled(Boolean(s.compare_enabled));
    }
    setShowHeaderTaglines(s.show_header_taglines !== false);
    if (s.host) { setHost(s.host); return s.host; }
    return "";
  }, []);

  const handleLogoMarkDebugGesture = useCallback((event) => {
    if (debugUiMode) return;
    if (!event?.shiftKey) {
      logoDebugUnlockTapCountRef.current = 0;
      if (logoDebugUnlockTimerRef.current) {
        clearTimeout(logoDebugUnlockTimerRef.current);
        logoDebugUnlockTimerRef.current = null;
      }
      return;
    }
    if (!isPywebviewApiReady()) return;
    const bridge = api();
    if (typeof bridge.unlock_debug_ui_mode !== "function") return;

    if (logoDebugUnlockTimerRef.current) {
      clearTimeout(logoDebugUnlockTimerRef.current);
      logoDebugUnlockTimerRef.current = null;
    }
    logoDebugUnlockTapCountRef.current += 1;
    if (logoDebugUnlockTapCountRef.current >= LOGO_DEBUG_UNLOCK_TAPS) {
      logoDebugUnlockTapCountRef.current = 0;
      void (async () => {
        try {
          await bridge.unlock_debug_ui_mode();
          const raw = await bridge.load_settings();
          const s = typeof raw === "string" ? JSON.parse(raw) : raw;
          applySettings(s);
          setLogoUnlockRippling(true);
          setDebugBadgeReveal(true);
        } catch (_) {}
      })();
      return;
    }
    logoDebugUnlockTimerRef.current = setTimeout(() => {
      logoDebugUnlockTapCountRef.current = 0;
      logoDebugUnlockTimerRef.current = null;
    }, LOGO_DEBUG_UNLOCK_WINDOW_MS);
  }, [debugUiMode, applySettings]);

  useEffect(
    () => () => {
      if (logoDebugUnlockTimerRef.current) {
        clearTimeout(logoDebugUnlockTimerRef.current);
        logoDebugUnlockTimerRef.current = null;
      }
    },
    []
  );

  useEffect(() => {
    if (!filePickerOpen || !isPywebviewApiReady()) return;
    const loadId = ++filePickerLoadIdRef.current;
    let cancelled = false;

    (async () => {
      setFilePickerListError("");
      try {
        const snapRaw = await api().declaration_folders_snapshot(inputDir, processedDir);
        const snap = typeof snapRaw === "string" ? JSON.parse(snapRaw) : snapRaw;
        if (cancelled || loadId !== filePickerLoadIdRef.current) return;

        if (!snap?.ok) {
          const err = Array.isArray(snap?.errors) ? snap.errors.join(" ") : "Не вдалося перевірити каталоги.";
          setFilePickerListError(err);
          setAvailableFiles([]);
          setPickerDeclCount(0);
          setPickerProcCount(0);
          return;
        }

        const fpIn = snap.input?.fingerprint ?? "";
        const fpProc = snap.processed?.fingerprint ?? "";
        const cIn = Number(snap.input?.count) || 0;
        const cProc = Number(snap.processed?.count) || 0;
        setPickerDeclCount(cIn);
        setPickerProcCount(cProc);

        const cache = filePickerCacheRef.current;
        const inputCacheOk =
          cache.inputDir === inputDir && cache.fpInput === fpIn && Array.isArray(cache.files);

        if (inputCacheOk) {
          setAvailableFiles(cache.files);
          filePickerCacheRef.current = {
            ...cache,
            processedDir,
            fpProc,
          };
          return;
        }

        setFilePickerLoading(true);
        setAvailableFiles([]);

        const raw = await api().list_declaration_files(inputDir);
        if (cancelled || loadId !== filePickerLoadIdRef.current) return;

        const res = typeof raw === "string" ? JSON.parse(raw) : raw;
        if (!res?.ok) {
          const err = Array.isArray(res?.errors) ? res.errors.join(" ") : "Не вдалося прочитати каталог.";
          setFilePickerListError(err);
          setAvailableFiles([]);
          return;
        }

        const list = Array.isArray(res.files) ? res.files : [];
        setAvailableFiles(list);
        filePickerCacheRef.current = {
          inputDir,
          processedDir,
          fpInput: fpIn,
          fpProc: fpProc,
          files: list,
        };
      } catch (e) {
        if (!cancelled && loadId === filePickerLoadIdRef.current) {
          setFilePickerListError(String(e));
          setAvailableFiles([]);
        }
      } finally {
        if (loadId === filePickerLoadIdRef.current) {
          setFilePickerLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [filePickerOpen, inputDir, processedDir]);

  const filePickerDraftEffective = useMemo(
    () => pruneFileNamesToAvailable(filePickerDraft, availableFiles),
    [filePickerDraft, availableFiles]
  );

  useEffect(() => {
    if (filePickerLoading) return;
    const names = new Set(availableFiles.map((f) => f.name));
    setSelectedFiles((prev) => {
      const next = prev.filter((n) => names.has(n));
      return next.length === prev.length ? prev : next;
    });
    if (!filePickerOpen) return;
    setFilePickerDraft((prev) => {
      const next = pruneFileNamesToAvailable(prev, availableFiles);
      if (next.size === prev.size) return prev;
      return next;
    });
  }, [availableFiles, filePickerOpen, filePickerLoading]);

  useEffect(() => {
    if (!filePickerOpen) return;
    if (!cloudMode || cloudProvider !== "openrouter") return;
    void loadOpenrouterModels(openrouterHost, openrouterApiKey);
  }, [filePickerOpen, cloudMode, cloudProvider, openrouterHost, openrouterApiKey, loadOpenrouterModels]);

  const filePickerOpenrouterCostHint = useMemo(() => {
    if (!cloudMode || cloudProvider !== "openrouter") return { kind: "hidden" };
    const n = filePickerDraftEffective.size;
    if (n <= 0) return { kind: "empty" };
    const modelId = String(openrouterModel || "").trim();
    if (!modelId) {
      return {
        kind: "no_model",
        line: "Оберіть модель OpenRouter у режимі Cloud (шапка або «Хмара»).",
      };
    }
    const total = estimateOpenrouterUsdForSelection(
      n,
      modelId,
      openrouterPricingPerToken,
      maxChars,
      numPredict,
    );
    const { inputTok, outputTok } = estimateOpenrouterTokensOneDeclaration(maxChars, numPredict);
    if (total != null) {
      const w = ukDeclWordAfterN(n);
      return {
        kind: "ok",
        title: `Оцінка за ставками OpenRouter (/models). Орієнтир токенів на 1 декларацію: ~${inputTok} in, ~${outputTok} out (поля «Макс. розмір запиту» та «Макс. обсяг відповіді»).`,
        line: `Приблизна вартість: ~$${total.toFixed(2)} USD за ${n} ${w} · ${modelId}`,
      };
    }
    return {
      kind: "no_rates",
      line: `Немає ставок для «${modelId}» у кеші. Відкрийте «Хмара», щоб оновити список моделей.`,
    };
  }, [
    cloudMode,
    cloudProvider,
    filePickerDraftEffective,
    openrouterModel,
    openrouterPricingPerToken,
    maxChars,
    numPredict,
  ]);

  useEffect(() => {
    if (!sortDropdownOpen) return;
    const onDocDown = (e) => {
      const el = sortDropdownAnchorRef.current;
      const menu = sortDropdownMenuRef.current;
      if (el && el.contains(e.target)) return;
      if (menu && menu.contains(e.target)) return;
      setSortDropdownOpen(false);
    };
    document.addEventListener("mousedown", onDocDown);
    return () => document.removeEventListener("mousedown", onDocDown);
  }, [sortDropdownOpen]);

  useEffect(() => {
    let cancelled = false;
    let bootstrapped = false;

    const init = async () => {
      if (cancelled || bootstrapped || !isPywebviewApiReady()) return;
      bootstrapped = true;
      const bridge = window.pywebview.api;
      let loadedHost = "http://127.0.0.1:11434";
      try {
        const raw = await bridge.load_settings();
        const s = (typeof raw === "string") ? JSON.parse(raw) : raw;
        loadedHost = applySettings(s) || loadedHost;
        const taglinesOn = s.show_header_taglines !== false;
        if (taglinesOn) {
          if (sessionHeaderTaglineRef.current == null) {
            sessionHeaderTaglineRef.current = pickRandomHeaderTagline();
          }
          setHeaderSlogan(sessionHeaderTaglineRef.current);
        } else {
          setHeaderSlogan("");
        }
        if (s.welcome_modal_seen !== true) {
          setWelcomeModalOpen(true);
        }
      } catch (e) {
        console.error("Failed to load settings:", e);
        setShowHeaderTaglines(true);
        if (sessionHeaderTaglineRef.current == null) {
          sessionHeaderTaglineRef.current = pickRandomHeaderTagline();
        }
        setHeaderSlogan(sessionHeaderTaglineRef.current);
      } finally {
        setReady(true);
      }
      await loadModels(loadedHost);
    };

    const tryStart = () => {
      if (cancelled || !isPywebviewApiReady()) return;
      void init();
    };

    window.addEventListener("pywebviewready", tryStart, { once: true });

    // pywebviewready may fire before we subscribe; QWebChannel is asynchronous.
    const poll = window.setInterval(() => {
      tryStart();
      if (bootstrapped || cancelled) window.clearInterval(poll);
    }, 48);
    const pollCap = window.setTimeout(() => {
      window.clearInterval(poll);
      if (!cancelled && !bootstrapped) {
        console.error("pywebview API не з’явився за очікуваний час (немає load_settings).");
        setReady(true);
      }
    }, 20000);

    tryStart();

    return () => {
      cancelled = true;
      window.removeEventListener("pywebviewready", tryStart);
      window.clearInterval(poll);
      window.clearTimeout(pollCap);
    };
  }, [loadModels, applySettings]);

// Text log appends at the bottom — keep it scrolled down.
// Do NOT auto-scroll the visual log: cards move/add with animation,
// and scroll position stays stable (user control + scroll anchoring).
  useEffect(() => {
    if (logViewMode !== "text") return;
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logLines, logViewMode]);

  useEffect(() => {
    if (!isRunning) setActiveProcessing([]);
  }, [isRunning]);

// WebView2 on Windows swallows the first click after the window regains focus.
// Force focus onto documentElement so WebView2 registers it before the click.
  useEffect(() => {
    const onFocus = () => {
      if (!document.hasFocus()) return;
      const el = document.activeElement;
      if (!el || el === document.body || el === document.documentElement) {
        document.documentElement.focus({ preventScroll: true });
      }
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, []);

  useEffect(() => {
    if (!runTimerVisible || runTimerExiting || !runStartedAtRef.current) return;
    const tick = () => {
      const dt = Math.floor((Date.now() - runStartedAtRef.current) / 1000);
      setElapsedSec(Math.max(0, dt));
    };
    tick();
    const id = setInterval(tick, 250);
    return () => clearInterval(id);
  }, [runTimerVisible, runTimerExiting]);

  useEffect(() => () => {
    if (runTimerHideRef.current) clearTimeout(runTimerHideRef.current);
  }, []);

  useEffect(() => {
    let timer = null;
    const poll = async () => {
      if (!api()) return;
      try {
        const raw = await api().get_system_metrics();
        const val = (typeof raw === "string") ? JSON.parse(raw) : raw;
        if (val && typeof val === "object") setSystemMetrics(val);
      } catch (_) {}
    };
    if (showSystemMetrics && ready && api()) {
      poll();
      timer = setInterval(poll, 2000);
    }
    return () => {
      if (timer) clearInterval(timer);
    };
  }, [showSystemMetrics, ready]);

  useEffect(() => {
    if (!showCloudModal) return;
    const o = cloudDraft.ollama || {};
    const r = cloudDraft.openrouter || {};
    if (cloudDraft.provider === "openrouter") {
      loadOpenrouterModels(r.host, r.api_key);
    } else {
      loadCloudModels(o.host, o.api_key);
    }
  }, [
    showCloudModal,
    cloudDraft.provider,
    cloudDraft.ollama?.host,
    cloudDraft.ollama?.api_key,
    cloudDraft.openrouter?.host,
    cloudDraft.openrouter?.api_key,
    loadCloudModels,
    loadOpenrouterModels,
  ]);

  useEffect(() => {
    if (!showCloudModal || cloudDraft.provider !== "openrouter") return;
    const r = cloudDraft.openrouter || {};
    const host = String(r.host || "").trim() || "https://openrouter.ai/api/v1";
    const key = String(r.api_key || "").trim();
    if (!key) {
      setOpenrouterCreditsLabel("");
      setOpenrouterCreditsHint("");
      return;
    }
    const t = window.setTimeout(() => {
      void refreshOpenrouterCredits(host, key);
    }, 800);
    return () => window.clearTimeout(t);
  }, [
    showCloudModal,
    cloudDraft.provider,
    cloudDraft.openrouter?.host,
    cloudDraft.openrouter?.api_key,
    refreshOpenrouterCredits,
  ]);

  useEffect(() => {
    if (!showCloudComparisonModal || cloudProvider !== "openrouter") return;
    void loadOpenrouterModels(openrouterHost, openrouterApiKey);
  }, [
    showCloudComparisonModal,
    cloudProvider,
    openrouterHost,
    openrouterApiKey,
    loadOpenrouterModels,
  ]);

  const pickFolder = async (setter) => {
    if (!api()) return;
    try {
      const path = await api().pick_folder();
      if (path) setter(path);
    } catch (e) { console.error(e); }
  };

  const pickFile = async (setter) => {
    if (!api()) return;
    try {
      const path = await api().pick_file();
      if (path) setter(path);
    } catch (e) { console.error(e); }
  };

  const pickHtmlFileOpen = async (setter) => {
    if (!api()) return;
    try {
      const path = await api().pick_html_file_open();
      if (path) setter(path);
    } catch (e) { console.error(e); }
  };

  const openDeclarationsFolder = async () => {
    if (!api()) return;
    try {
      const raw = await api().open_declarations_folder(inputDir);
      const res = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (!res?.ok) {
        setTaskText(res?.errors?.[0] || "Не вдалося відкрити папку декларацій.");
      }
    } catch (e) {
      setTaskText(String(e));
    }
  };

  const openPromptEditor = async () => {
    if (!api()) return;
    setPromptEditorOpen(true);
    setPromptEditorTab("pipeline");
    if (sessionPromptOverrides) {
      setPromptDraft({
        pipelineSystem: sessionPromptOverrides.pipelineSystem,
        pipelineUser: sessionPromptOverrides.pipelineUser,
        dossierSystem: sessionPromptOverrides.dossierSystem,
        dossierUser: sessionPromptOverrides.dossierUser,
      });
      setPromptBuiltinLoading(false);
      return;
    }
    setPromptBuiltinLoading(true);
    try {
      const raw = await api().get_builtin_prompts();
      const d = typeof raw === "string" ? JSON.parse(raw) : raw;
      setPromptDraft({
        pipelineSystem: d.pipeline_system_prompt || "",
        pipelineUser: d.pipeline_user_prompt_template || "",
        dossierSystem: d.dossier_system_prompt || "",
        dossierUser: d.dossier_user_prompt_template || "",
      });
    } catch {
      setPromptDraft({
        pipelineSystem: "",
        pipelineUser: "",
        dossierSystem: "",
        dossierUser: "",
      });
    } finally {
      setPromptBuiltinLoading(false);
    }
  };

  const applyPromptSession = () => {
    const ps = promptDraft.pipelineSystem.trim();
    const pu = promptDraft.pipelineUser.trim();
    const ds = promptDraft.dossierSystem.trim();
    const du = promptDraft.dossierUser.trim();
    if (!ps && !pu && !ds && !du) {
      setSessionPromptOverrides(null);
    } else {
      setSessionPromptOverrides({
        pipelineSystem: ps,
        pipelineUser: pu,
        dossierSystem: ds,
        dossierUser: du,
      });
    }
    setPromptEditorOpen(false);
    setTaskText("Промпти сесії оновлено. Оригінали в репозиторії не змінені.");
  };

  const resetPromptsToBuiltin = async () => {
    if (!api()) return;
    setSessionPromptOverrides(null);
    setPromptBuiltinLoading(true);
    try {
      const raw = await api().get_builtin_prompts();
      const d = typeof raw === "string" ? JSON.parse(raw) : raw;
      setPromptDraft({
        pipelineSystem: d.pipeline_system_prompt || "",
        pipelineUser: d.pipeline_user_prompt_template || "",
        dossierSystem: d.dossier_system_prompt || "",
        dossierUser: d.dossier_user_prompt_template || "",
      });
      setTaskText("Тексти у редакторі скинуто до вбудованих; активні перевизначення сесії вимкнено.");
    } finally {
      setPromptBuiltinLoading(false);
    }
  };

  const gatherArgs = () => ({
    input_dir: inputDir,
    processed_dir: processedDir,
    output_jsonl: outputJsonl,
    errors_jsonl: errorsJsonl,
    summary_csv: summaryCsv,
    findings_csv: findingsCsv,
    table_html: tableHtml,
    max_files: maxFiles,
    file_queue_mode: fileQueueMode,
    selected_files: fileQueueMode === "pick" && selectedFiles.length > 0 ? selectedFiles : [],
    sort_order: fileQueueMode === "sort" ? sortOrder : "alpha",
    model,
    host,
    timeout,
    retries,
    retry_delay: retryDelay,
    max_chars: maxChars,
    num_predict: numPredict,
    make_report: debugUiMode ? makeReport : true,
    move_processed: moveProcessed,
    save_compact_declarations: false,
    no_dedupe: noDedupe,
    audit_mode_enabled: debugUiMode ? auditModeEnabled : false,
    audit_mode_dir: auditModeDir,
    audit_capture_raw_declaration: debugUiMode && auditModeEnabled ? auditCaptureRawDeclaration : false,
    audit_capture_compact_declaration: debugUiMode && auditModeEnabled ? auditCaptureCompactDeclaration : false,
    audit_capture_request_payload: debugUiMode && auditModeEnabled ? auditCaptureRequestPayload : false,
    audit_capture_response_raw: debugUiMode && auditModeEnabled ? auditCaptureResponseRaw : false,
    audit_capture_response_parsed: debugUiMode && auditModeEnabled ? auditCaptureResponseParsed : false,
    audit_capture_normalized_analysis:
      debugUiMode && auditModeEnabled ? auditCaptureNormalizedAnalysis : false,
    audit_capture_attempt_meta: debugUiMode && auditModeEnabled ? auditCaptureAttemptMeta : false,
    compact_legacy_payload: compactLegacyPayload,
    show_system_metrics: showSystemMetrics,
    play_completion_sound: playCompletionSound,
    think_event_debug: thinkEventDebug,
    pipeline_max_concurrent:
      cloudMode && cloudProvider === "openrouter" ? pipelineMaxConcurrent : 1,
    cloud_mode: cloudMode,
    cloud_provider: cloudProvider,
    cloud_host: cloudHost,
    cloud_model: cloudModel,
    cloud_api_key: cloudApiKey,
    openrouter_host: openrouterHost,
    openrouter_model: openrouterModel,
    openrouter_api_key: openrouterApiKey,
    compare_enabled: cloudComparisonEnabled,
    compare_count: cloudComparisonCount,
    compare_models: cloudComparisonSeedModels
      .slice(0, cloudComparisonCount)
      .map((m) => String(m || "").trim())
      .filter(Boolean),
    show_header_taglines: showHeaderTaglines,
    debug_mode_ui: debugUiMode,
    ...(debugUiMode && sessionPromptOverrides
      ? {
          prompt_session_pipeline_system: sessionPromptOverrides.pipelineSystem,
          prompt_session_pipeline_user_template: sessionPromptOverrides.pipelineUser,
          prompt_session_dossier_system: sessionPromptOverrides.dossierSystem,
          prompt_session_dossier_user_template: sessionPromptOverrides.dossierUser,
        }
      : {}),
  });

  // Centralized settings autosave (debounced) so UI changes reliably reach settings.json.
  useEffect(() => {
    if (!ready || !api()) return;
    const payload = gatherArgs();
    const serialized = JSON.stringify(payload);
    if (!lastAutosavedPayloadRef.current) {
      lastAutosavedPayloadRef.current = serialized;
      return;
    }
    if (serialized === lastAutosavedPayloadRef.current) return;
    if (autosaveTimerRef.current) {
      clearTimeout(autosaveTimerRef.current);
    }
    if (autosaveFlashTimerRef.current) {
      clearTimeout(autosaveFlashTimerRef.current);
      autosaveFlashTimerRef.current = null;
    }
    setAutosaveStatus("saving");
    autosaveTimerRef.current = setTimeout(async () => {
      try {
        await api().save_settings(payload);
        lastAutosavedPayloadRef.current = serialized;
        setAutosaveStatus("saved");
        autosaveFlashTimerRef.current = setTimeout(() => {
          setAutosaveStatus("idle");
          autosaveFlashTimerRef.current = null;
        }, 1400);
      } catch (err) {
        console.error("autosave settings failed:", err);
        setAutosaveStatus("error");
        autosaveFlashTimerRef.current = setTimeout(() => {
          setAutosaveStatus("idle");
          autosaveFlashTimerRef.current = null;
        }, 2200);
      } finally {
        autosaveTimerRef.current = null;
      }
    }, 350);
    return () => {
      if (autosaveTimerRef.current) {
        clearTimeout(autosaveTimerRef.current);
        autosaveTimerRef.current = null;
      }
    };
  }, [
    ready,
    inputDir,
    processedDir,
    outputJsonl,
    errorsJsonl,
    summaryCsv,
    findingsCsv,
    tableHtml,
    maxFiles,
    fileQueueMode,
    selectedFiles,
    sortOrder,
    model,
    host,
    timeout,
    retries,
    retryDelay,
    maxChars,
    numPredict,
    makeReport,
    moveProcessed,
    noDedupe,
    auditModeEnabled,
    auditModeDir,
    auditCaptureRawDeclaration,
    auditCaptureCompactDeclaration,
    auditCaptureRequestPayload,
    auditCaptureResponseRaw,
    auditCaptureResponseParsed,
    auditCaptureNormalizedAnalysis,
    auditCaptureAttemptMeta,
    compactLegacyPayload,
    showSystemMetrics,
    playCompletionSound,
    thinkEventDebug,
    pipelineMaxConcurrent,
    cloudMode,
    cloudProvider,
    cloudHost,
    cloudModel,
    cloudApiKey,
    openrouterHost,
    openrouterModel,
    openrouterApiKey,
    cloudComparisonEnabled,
    cloudComparisonCount,
    cloudComparisonSeedModels,
    showHeaderTaglines,
    debugUiMode,
    sessionPromptOverrides,
  ]);

  useEffect(
    () => () => {
      if (autosaveFlashTimerRef.current) {
        clearTimeout(autosaveFlashTimerRef.current);
      }
      if (autosaveIndicatorFadeTimerRef.current) {
        clearTimeout(autosaveIndicatorFadeTimerRef.current);
      }
    },
    []
  );

  useEffect(() => {
    if (!debugUiMode) {
      setAutosaveIndicatorVisible(false);
      setAutosaveIndicatorMounted(false);
      if (autosaveIndicatorFadeTimerRef.current) {
        clearTimeout(autosaveIndicatorFadeTimerRef.current);
        autosaveIndicatorFadeTimerRef.current = null;
      }
      return;
    }
    if (autosaveIndicatorFadeTimerRef.current) {
      clearTimeout(autosaveIndicatorFadeTimerRef.current);
      autosaveIndicatorFadeTimerRef.current = null;
    }
    if (autosaveStatus === "idle") {
      setAutosaveIndicatorVisible(false);
      autosaveIndicatorFadeTimerRef.current = setTimeout(() => {
        setAutosaveIndicatorMounted(false);
        autosaveIndicatorFadeTimerRef.current = null;
      }, AUTOSAVE_INDICATOR_FADE_MS);
      return;
    }
    setAutosaveIndicatorMounted(true);
    const raf = requestAnimationFrame(() => {
      requestAnimationFrame(() => setAutosaveIndicatorVisible(true));
    });
    return () => cancelAnimationFrame(raf);
  }, [autosaveStatus, debugUiMode]);

  const runDebugDossierHtmlSummary = async () => {
    if (!api() || isRunning || dossierSummaryBusy) return;
    setDossierSummaryBusy(true);
    appendLog("\n=== [DEBUG] Запит підсумку досьє по HTML… ===\n");
    try {
      const raw = await api().debug_run_dossier_html_summary(gatherArgs());
      const res = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (res && res.message) appendLog(`${res.message}\n`);
      if (res && !res.ok) appendLog("[DEBUG] Підсумок досьє не застосовано до HTML.\n");
      setTaskText(res?.ok ? "Підсумок досьє (debug) готово" : "Підсумок досьє (debug): помилка");
    } catch (e) {
      appendLog(`[ПОМИЛКА] debug підсумок досьє: ${e}\n`);
      setTaskText(String(e));
    } finally {
      setDossierSummaryBusy(false);
    }
  };

  const runDebugCloudModelComparison = async ({ compare_models }) => {
    if (!api() || cloudCompareBusy) return { ok: false, message: "pywebview API недоступний." };
    setCloudCompareBusy(true);
    appendLog("\n=== [COMPARE] Запуск порівняння моделей (одна декларація) ===\n");
    setTaskText("Порівняння моделей: запуск…");
    const payload = {
      ...gatherArgs(),
      compare_models: Array.isArray(compare_models) ? compare_models : [],
    };
    try {
      const raw = await api().debug_compare_models_html(payload);
      const res = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (res?.message) appendLog(`${res.message}\n`);
      if (res?.path) appendLog(`[COMPARE] HTML: ${res.path}\n`);
      if (res?.ok) {
        try {
          await api().open_file_path(res.path);
          appendLog(`[COMPARE] Відкрито compare-звіт: ${res.path}\n`);
        } catch (openErr) {
          appendLog(`[COMPARE] Не вдалося авто-відкрити compare-звіт: ${openErr}\n`);
        }
        setTaskText("Порівняння моделей завершено");
      } else {
        setTaskText("Порівняння моделей: помилка");
      }
      return res;
    } catch (e) {
      appendLog(`[ПОМИЛКА] compare: ${e}\n`);
      setTaskText(String(e));
      return { ok: false, message: String(e) };
    } finally {
      setCloudCompareBusy(false);
    }
  };

  const runExtraReportHtml = async () => {
    if (!api() || isRunning || extraReportBusy) return;
    setExtraReportBusy(true);
    appendLog("\n=== [REPORT] Перегенерація звітів з JSONL (HTML + CSV) ===\n");
    try {
      const raw = await api().run_extra_report(gatherArgs());
      const res = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (res?.path) appendLog(`${res.message || res.path}\n`);
      if (res?.errors?.length) appendLog(`[REPORT] ${res.errors.join(" ")}\n`);
      if (res?.ok) {
        setTaskText("Звіти оновлено (HTML + CSV)");
      } else {
        setTaskText("Перегенерація звітів: помилка");
      }
    } catch (e) {
      appendLog(`[ПОМИЛКА] перегенерація звітів: ${e}\n`);
      setTaskText(String(e));
    } finally {
      setExtraReportBusy(false);
    }
  };

  const runDebugWipeUsageTraces = async () => {
    if (!api() || isRunning || wipeBusy) return;
    setWipeBusy(true);
    appendLog("\n=== [WIPE] Запит на видалення слідів використання ===\n");
    try {
      const raw = await api().debug_wipe_usage_traces(gatherArgs());
      const res = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (res?.errors?.length) {
        appendLog(`[WIPE] Помилки (${res.errors.length}): ${res.errors.slice(0, 3).join("; ")}\n`);
      }
      const n = Number(res?.deleted_count) || 0;
      if (res?.ok !== false || n > 0) {
        setSessionPromptOverrides(null);
        const settingsRaw = await api().load_settings();
        const s = typeof settingsRaw === "string" ? JSON.parse(settingsRaw) : settingsRaw;
        applySettings(s);
        lastAutosavedPayloadRef.current = "";
        setTaskText(
          n > 0
            ? `Сліди використання видалено (${n} файлів)`
            : "Слідів використання не знайдено"
        );
        setWipeModalOpen(false);
      } else {
        setTaskText("Видалення слідів: помилка");
      }
    } catch (e) {
      appendLog(`[ПОМИЛКА] wipe usage traces: ${e}\n`);
      setTaskText(String(e));
    } finally {
      setWipeBusy(false);
    }
  };

  const saveNormalPathsSnapshot = useCallback(() => {
    if (deepResearchActive || normalPathsSnapshotRef.current) return;
    normalPathsSnapshotRef.current = {
      inputDir,
      outputJsonl,
      errorsJsonl,
      summaryCsv,
      findingsCsv,
      tableHtml,
    };
  }, [deepResearchActive, inputDir, outputJsonl, errorsJsonl, summaryCsv, findingsCsv, tableHtml]);

  /** After leaving deep_research, fields may still point at another dossier folder. */
  useEffect(() => {
    if (deepResearchActive || isDeepResearchInput(inputDir)) return;
    if (pathUnderDeepResearch(outputJsonl)) setOutputJsonl(NORMAL_REPORT_PATH_DEFAULTS.outputJsonl);
    if (pathUnderDeepResearch(errorsJsonl)) setErrorsJsonl(NORMAL_REPORT_PATH_DEFAULTS.errorsJsonl);
    if (pathUnderDeepResearch(summaryCsv)) setSummaryCsv(NORMAL_REPORT_PATH_DEFAULTS.summaryCsv);
    if (pathUnderDeepResearch(findingsCsv)) setFindingsCsv(NORMAL_REPORT_PATH_DEFAULTS.findingsCsv);
    if (pathUnderDeepResearch(tableHtml)) setTableHtml(NORMAL_REPORT_PATH_DEFAULTS.tableHtml);
  }, [
    deepResearchActive,
    inputDir,
    outputJsonl,
    errorsJsonl,
    summaryCsv,
    findingsCsv,
    tableHtml,
  ]);

  /** Report paths under the session subdir — same as webview `_deep_research_session_paths` (aligned with pipeline + DEBUG). */
  const applyDeepResearchSessionOutputPaths = useCallback((dir) => {
    const base = String(dir || "").replace(/[/\\]+$/, "");
    if (!base) return;
    const sep = base.includes("\\") ? "\\" : "/";
    setOutputJsonl(`${base}${sep}analysis_results.jsonl`);
    setErrorsJsonl(`${base}${sep}analysis_errors.jsonl`);
    setSummaryCsv(`${base}${sep}report_summary.csv`);
    setFindingsCsv(`${base}${sep}report_findings.csv`);
    setTableHtml(`${base}${sep}report_table.html`);
  }, []);

  const exitDeepResearchMode = useCallback(() => {
    if (isRunning) return;
    setDeepResearchOpen(false);
    setDeepResearchLoading(false);
    setDeepResearchError("");
    setDeepResearchActive(false);
    setDossierMainView("dossier");

    const snap = normalPathsSnapshotRef.current;
    if (snap) {
      setInputDir(snap.inputDir);
      setOutputJsonl(snap.outputJsonl);
      setErrorsJsonl(snap.errorsJsonl);
      setSummaryCsv(snap.summaryCsv);
      setFindingsCsv(snap.findingsCsv);
      setTableHtml(snap.tableHtml);
      normalPathsSnapshotRef.current = null;
    }
    setTaskText("Звичайний режим: deep research вимкнено.");
    appendLog("[DEEP] Вихід із режиму глибокого дослідження. Повернуто стандартні шляхи.\n");
  }, [isRunning, appendLog]);

  const exitCompareMode = useCallback(async () => {
    if (isRunning) return;
    setCloudComparisonEnabled(false);
    setTaskText("Звичайний режим: порівняння вимкнено.");
    appendLog("[COMPARE] Режим порівняння вимкнено.\n");
    if (!api()) return;
    try {
      const payload = { ...gatherArgs(), compare_enabled: false };
      await api().save_settings(payload);
      lastAutosavedPayloadRef.current = JSON.stringify(payload);
    } catch (err) {
      console.error("exit compare mode save_settings:", err);
    }
  }, [isRunning, appendLog]);

  /** Minimum persisted Cloud fields (aligned with validate in webview_app). */
  const hasSavedCloudPrefs =
    cloudProvider === "openrouter"
      ? String(openrouterModel || "").trim() !== "" &&
        String(openrouterApiKey || "").trim() !== ""
      : String(cloudModel || "").trim() !== "" &&
        String(cloudApiKey || "").trim() !== "";

  useEffect(() => {
    const preferred = (cloudProvider === "openrouter" ? openrouterModel : cloudModel) || "";
    const normalized = String(preferred).trim();
    if (!normalized) return;
    setCloudComparisonSeedModels((prev) => {
      const p0 = String(prev?.[0] || "").trim();
      if (p0) return prev;
      return [normalized, "", "", ""];
    });
  }, [cloudProvider, cloudModel, openrouterModel]);

  const buildCloudDraft = () => ({
    provider: cloudProvider === "openrouter" ? "openrouter" : "ollama",
    ollama: {
      host: cloudHost || "https://ollama.com",
      model: cloudModel || "",
      api_key: cloudApiKey || "",
    },
    openrouter: {
      host: openrouterHost || "https://openrouter.ai/api/v1",
      model: openrouterModel || "meta-llama/llama-3.3-70b-instruct",
      api_key: openrouterApiKey || "",
    },
  });

  const cloudHeaderModelId = cloudProvider === "openrouter" ? openrouterModel : cloudModel;
  const cloudHeaderModelShort = formatCloudHeaderModelShort(cloudHeaderModelId);
  const cloudHeaderModelFull = formatCloudHeaderModelFull(cloudProvider, cloudHeaderModelId);

  const handleCloudSwitch = (nextCloudMode) => {
    if (nextCloudMode) {
      if (!cloudWarningAcceptedSession) {
        setShowCloudWarning(true);
        return;
      }
      if (!hasSavedCloudPrefs) {
        setCloudDraft(buildCloudDraft());
        setShowCloudModal(true);
        return;
      }
      setCloudMode(true);
      return;
    }
    setCloudMode(false);
  };

  const handleStart = async () => {
    if (isRunning || !api() || startInFlightRef.current) return;
    startInFlightRef.current = true;
    setReportBtnPulse("idle");
    primePipelineAudioContext();
    resetLogSession();
    setStatusText("Перевірка...");
    setTaskText("Валідація налаштувань...");
    try {
      const raw = await api().validate(gatherArgs());
      const check = (typeof raw === "string") ? JSON.parse(raw) : raw;
      if (!check.ok) {
        for (const err of check.errors) appendLog(`[ПОМИЛКА] ${err}\n`);
        setStatusText("Помилка");
        setTaskText("Перевірте налаштування перед запуском");
        startInFlightRef.current = false;
        return;
      }
    } catch (e) {
      appendLog(`[ПОМИЛКА] Валідація: ${e}\n`);
      setStatusText("Помилка");
      setTaskText(String(e));
      startInFlightRef.current = false;
      return;
    }
    setIsRunning(true);
    setIsPaused(false);
    setStatusText("Виконується");
    setTaskText("Запуск пайплайну…");
    setProgress({ cur: 0, total: 0 });
    runStartedAtRef.current = Date.now();
    setElapsedSec(0);
    if (runTimerHideRef.current) clearTimeout(runTimerHideRef.current);
    setRunTimerExiting(false);
    setRunTimerVisible(true);
    try {
      if (debugUiMode && cloudComparisonEnabled) {
        const compareModels = cloudComparisonSeedModels
          .slice(0, cloudComparisonCount)
          .map((m) => String(m || "").trim())
          .filter(Boolean);
        if (new Set(compareModels).size < 2) {
          appendLog("[ПОМИЛКА] Для порівняння потрібно щонайменше 2 унікальні моделі.\n");
          setStatusText("Помилка");
          setTaskText("Налаштуйте 2-4 різні моделі для порівняння");
          return;
        }
        const res = await runDebugCloudModelComparison({ compare_models: compareModels });
        if (res?.ok) {
          setStatusText("Завершено");
          setTaskText("Порівняння моделей завершено");
        } else {
          setStatusText("Помилка");
          setTaskText(String(res?.message || "Порівняння моделей завершилось з помилкою"));
        }
        return;
      }
      const result = await api().run_pipeline(gatherArgs());
      if (result === "ok") {
        setStatusText("Завершено");
        setTaskText("Пайплайн успішно завершено");
        setReportBtnPulse("pulse");
      } else if (result === "partial") {
        setStatusText("Завершено з помилками");
        setTaskText("Пайплайн завершено, але є помилки в частині файлів");
      } else {
        setStatusText("Помилка");
        setTaskText(result);
      }
    } catch (e) {
      setStatusText("Помилка");
      setTaskText(String(e));
      appendLog(`\n[ПОМИЛКА] ${e}\n`);
    } finally {
      if (playCompletionSound) {
        void playPipelineDoneSound();
      }
      const finalSec = Math.max(
        0,
        Math.floor((Date.now() - (runStartedAtRef.current || Date.now())) / 1000)
      );
      setElapsedSec(finalSec);
      appendLog(`[INFO] Тривалість пайплайну: ${finalSec} с (${formatDurationClock(finalSec)})\n`);
      setIsRunning(false);
      startInFlightRef.current = false;
      setTimeout(() => setProgress({ cur: 0, total: 0 }), 2500);
      setRunTimerExiting(true);
      runTimerHideRef.current = setTimeout(() => {
        setRunTimerVisible(false);
        setRunTimerExiting(false);
      }, 1040);
      void refreshUsageStats();
      filePickerCacheRef.current = {
        ...filePickerCacheRef.current,
        fpInput: "",
        fpProc: "",
        files: null,
      };
    }
  };

  const handlePause = async () => {
    if (!isRunning || !api()) return;
    const next = !isPaused;
    setIsPaused(next);
    setStatusText(next ? "Пауза" : "Виконується");
    setTaskText(next ? "Пауза після поточної декларації..." : "Відновлено виконання");
    await api().control_pipeline(next ? "pause" : "run");
  };

  const handleStop = async () => {
    if (!isRunning || !api()) return;
    setStatusText("Зупинка...");
    setTaskText("Безпечна зупинка — чекаємо поточну декларацію...");
    await api().control_pipeline("stop");
  };

  const refreshDeepResearchFolders = useCallback(async () => {
    if (!api()) return;
    setDeepResearchFoldersLoading(true);
    try {
      const raw = await api().deep_research_list_folders();
      const data = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (data && data.ok && Array.isArray(data.folders)) {
        setDeepResearchFolders(data.folders);
      } else {
        setDeepResearchFolders([]);
      }
    } catch {
      setDeepResearchFolders([]);
    } finally {
      setDeepResearchFoldersLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!deepResearchOpen || !ready) return;
    refreshDeepResearchFolders();
  }, [deepResearchOpen, ready, refreshDeepResearchFolders]);

  useEffect(() => {
    if (deepResearchTab !== "existing" || deepResearchFoldersLoading) return;
    setDeepResearchSelectedFolder((cur) => {
      if (cur) return cur;
      const first = deepResearchFolders.find((f) => f.decl_count > 0);
      return first ? first.name : "";
    });
  }, [deepResearchTab, deepResearchFolders, deepResearchFoldersLoading]);

  // DEEP_RESEARCH
  const handleDeepResearchSubmit = async () => {
    if (!api() || deepResearchLoading) return;
    const n = parseInt(String(deepResearchUid).trim(), 10);
    if (!n || n < 1) {
      setDeepResearchError("Вкажіть коректний додатний user_declarant_id.");
      return;
    }
    setDeepResearchLoading(true);
    setDeepResearchDownloadProgress({ found: 0, downloaded: 0, skipped: 0, phase: "start" });
    setDeepResearchLoadingHint("Підключення до API НАЗК…");
    setDeepResearchError("");
    try {
      const raw = await api().deep_research_download(n);
      const res = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (res && res.ok && res.dir) {
        saveNormalPathsSnapshot();
        setInputDir(res.dir);
        applyDeepResearchSessionOutputPaths(res.dir);
        setDeepResearchActive(true);
        setDeepResearchOpen(false);
        appendLog(`[DEEP] Режим глибокого дослідження: папка декларацій → ${res.dir}\n`);
        setTaskText(`Deep research: у черзі ${res.saved ?? 0} декларацій (запустіть пайплайн).`);
        await refreshDeepResearchFolders();
      } else {
        const errMsg = (res && res.errors && res.errors.join(" ")) || "Невідома помилка завантаження.";
        setDeepResearchError(errMsg);
      }
    } catch (e) {
      setDeepResearchError(String(e));
    } finally {
      setDeepResearchLoading(false);
      setDeepResearchLoadingHint("");
      setDeepResearchDownloadProgress(null);
    }
  };

  const handleDeepResearchApplyExisting = async () => {
    if (!api() || deepResearchLoading) return;
    const name = String(deepResearchSelectedFolder || "").trim();
    if (!name) {
      setDeepResearchError("Оберіть папку зі списку.");
      return;
    }
    setDeepResearchLoading(true);
    setDeepResearchLoadingHint("Перевірка папки…");
    setDeepResearchError("");
    try {
      const raw = await api().deep_research_apply_folder(name);
      const res = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (res && res.ok && res.dir) {
        saveNormalPathsSnapshot();
        setInputDir(res.dir);
        applyDeepResearchSessionOutputPaths(res.dir);
        setDeepResearchActive(true);
        setDeepResearchOpen(false);
        appendLog(`[DEEP] У черзі ${res.saved ?? 0} декларацій з папки «${name}» (без завантаження).\n`);
        setTaskText(`Deep research: «${name}», ${res.saved ?? 0} файл(ів). Запустіть пайплайн.`);
      } else {
        const errMsg = (res && res.errors && res.errors.join(" ")) || "Не вдалося застосувати папку.";
        setDeepResearchError(errMsg);
      }
    } catch (e) {
      setDeepResearchError(String(e));
    } finally {
      setDeepResearchLoading(false);
      setDeepResearchLoadingHint("");
    }
  };

  const handleParseSingleDeclaration = async () => {
    if (!api() || parseLoading) return;
    const declarationId = String(parseDeclId || "").trim();
    const dir = String(inputDir || "").trim();
    if (!declarationId) {
      setParseError("Вкажіть declaration_id.");
      return;
    }
    if (!dir) {
      setParseError("Вкажіть папку декларацій у «Основних параметрах».");
      return;
    }
    setParseLoading(true);
    setParseError("");
    setParseLoadingHint("Завантаження декларації…");
    try {
      const raw = await api().deep_research_download_one(declarationId, dir);
      const res = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (res && res.ok) {
        const skipped =
          res.skipped_existing != null ? `, пропущено (вже є): ${res.skipped_existing}` : "";
        const savedN = res.new_saved != null ? res.new_saved : 1;
        appendLog(
          `[NAZK] (id) збережено нових декларацій: ${savedN}${skipped}. Папка: ${res.dir || dir}\n`
        );
        setTaskText(`Парсинг: збережено ${savedN} файл(ів).`);
        setParseModalOpen(false);
        setParseDeclId("");
      } else {
        const errMsg = (res && res.errors && res.errors.join(" ")) || "Не вдалося завантажити декларацію.";
        setParseError(errMsg);
      }
    } catch (e) {
      setParseError(String(e));
    } finally {
      setParseLoading(false);
      setParseLoadingHint("");
    }
  };

  const handleParseBulkByYear = async () => {
    if (!api() || parseLoading) return;
    const y = parseInt(String(parseBulkYear).trim(), 10);
    const n = parseInt(String(parseBulkCount).trim(), 10);
    const dir = String(parseBulkDir || "").trim();
    const yMax = new Date().getFullYear();
    const q = String(parseBulkQuery || "").trim();
    if (!dir) {
      setParseError("Вкажіть папку призначення.");
      return;
    }
    if (!parseBulkUseYear && !q) {
      setParseError("Увімкніть «Враховувати рік декларації» або введіть пошук.");
      return;
    }
    if (parseBulkUseYear && (Number.isNaN(y) || y < 2015 || y > yMax)) {
      setParseError(`Рік має бути від 2015 до ${yMax}.`);
      return;
    }
    if (q && q.length < 3) {
      setParseError("Пошук — від 3 символів (обмеження API НАЗК).");
      return;
    }
    if (q.length > 255) {
      setParseError("Пошук не довший за 255 символів.");
      return;
    }
    if (Number.isNaN(n) || n < 1) {
      setParseError("Кількість має бути не менше 1.");
      return;
    }
    if (n > 500) {
      setParseError("Максимум 500 декларацій за один запуск.");
      return;
    }
    const yearArg = parseBulkUseYear ? y : -1;
    setParseLoading(true);
    setParseError("");
    setParseDownloadProgress({ target: n, saved: 0, skipped: 0, page: 0, phase: "start" });
    setParseLoadingHint("Запит до API НАЗК…");
    try {
      const declType = parseInt(String(parseBulkDeclarationType || "").trim(), 10) || 0;
      const docType = parseInt(String(parseBulkDocumentType || "").trim(), 10) || 0;
      const raw = await api().nazk_download_by_year(yearArg, n, dir, q, declType, docType);
      const res = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (res && res.ok) {
        const skipped = res.skipped_existing != null ? `, пропущено (вже є): ${res.skipped_existing}` : "";
        const filterBits = [
          parseBulkUseYear ? `рік ${y}` : null,
          q ? "пошук" : null,
          nazkFilterOptionLabel(NAZK_DECLARATION_TYPE_OPTIONS, parseBulkDeclarationType),
          nazkFilterOptionLabel(NAZK_DOCUMENT_TYPE_OPTIONS, parseBulkDocumentType),
        ]
          .filter(Boolean)
          .join(", ");
        appendLog(
          `[NAZK] (${filterBits}) збережено нових декларацій: ${res.new_saved}${skipped}. Папка: ${res.dir || dir}\n`
        );
        setTaskText(`Множинний парсинг: збережено ${res.new_saved} файл(ів).`);
        setParseModalOpen(false);
      } else {
        const errMsg =
          (res && res.errors && res.errors.join(" ")) || "Не вдалося виконати множинне завантаження.";
        setParseError(errMsg);
      }
    } catch (e) {
      setParseError(String(e));
    } finally {
      setParseLoading(false);
      setParseLoadingHint("");
      setParseDownloadProgress(null);
    }
  };

  const dismissWelcomeModal = useCallback(async () => {
    try {
      if (api()) await api().dismiss_welcome_modal();
    } catch (err) {
      console.error("dismiss_welcome_modal:", err);
    }
    setWelcomeModalOpen(false);
  }, []);

  const openBulkParseFromWelcome = useCallback(async () => {
    await dismissWelcomeModal();
    setParseError("");
    setParseDeclId("");
    setParseTab("bulk");
    setParseBulkDir(inputDir);
    setParseModalOpen(true);
  }, [dismissWelcomeModal, inputDir]);

  const handleShowHeaderTaglinesChange = useCallback(async (next) => {
    setShowHeaderTaglines(next);
    if (next) {
      if (sessionHeaderTaglineRef.current == null) {
        sessionHeaderTaglineRef.current = pickRandomHeaderTagline();
      }
      setHeaderSlogan(sessionHeaderTaglineRef.current);
    } else {
      setHeaderSlogan("");
    }
    try {
      if (api()) await api().save_settings({ show_header_taglines: next });
    } catch (err) {
      console.error("save_settings show_header_taglines:", err);
    }
  }, []);

  const visualModelLabel = useMemo(() => {
    if (cloudMode) {
      const prov = cloudProvider === "openrouter" ? "openrouter" : "ollama";
      const m = cloudProvider === "openrouter" ? openrouterModel : cloudModel;
      return formatCloudHeaderModelFull(prov, m);
    }
    const m = String(model || "").trim();
    return m ? `ollama: ${m}` : "";
  }, [cloudMode, cloudProvider, openrouterModel, cloudModel, model]);

  const hasLogSession = logLines.length > 0 || visualEntries.length > 0;

  const handleCopyLog = async () => {
    const text = logLines.join("\n");
    if (!text) return;
    try {
      // In desktop webview prefer backend clipboard method (more stable on Windows).
      const bridge = api();
      if (bridge && typeof bridge.copy_to_clipboard === "function") {
        const raw = await bridge.copy_to_clipboard(text);
        const res = typeof raw === "string" ? JSON.parse(raw) : raw;
        if (!res?.ok) {
          throw new Error(String(res?.message || "backend clipboard failed"));
        }
      } else if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.setAttribute("readonly", "");
        ta.style.position = "absolute";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      setTaskText("Лог скопійовано в буфер обміну");
    } catch (e) {
      setTaskText(`Не вдалося скопіювати лог: ${e}`);
    }
  };

  const handleOpenReportTable = async () => {
    if (!api()) return;
    dismissReportBtnPulse();
    try {
      const raw = await api().open_report_table(inputDir, tableHtml, deepResearchActive);
      const res = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (res && res.ok) {
        appendLog(`[INFO] Відкрито звіт: ${res.path}\n`);
      } else {
        const errMsg = (res && res.errors && res.errors.join(" ")) || "Не вдалося відкрити report_table.html.";
        appendLog(`[ПОМИЛКА] ${errMsg}\n`);
        setTaskText(errMsg);
      }
    } catch (e) {
      const msg = String(e);
      appendLog(`[ПОМИЛКА] Відкриття звіту: ${msg}\n`);
      setTaskText(msg);
    }
  };

  const pct = progress.total > 0 ? Math.round((progress.cur / progress.total) * 100) : 0;

  return (
    <div className={`app${deepResearchActive ? " app--deep-research" : ""}`}>
      <header className="header">
        <div className="header-left">
          <div
            className={`logo-mark${debugUiMode ? " logo-mark--debug" : ""}${logoUnlockRippling ? " logo-mark--unlock-ripple" : ""}`}
            role="presentation"
            onClick={handleLogoMarkDebugGesture}
            onAnimationEnd={(e) => {
              if (e.target !== e.currentTarget) return;
              if (e.animationName === "logoMarkUnlockGradient") setLogoUnlockRippling(false);
            }}
          >
            Д
          </div>
          <div>
            <h1 className="app-title">
              <span className="app-title__name">DeclaratorLM</span>
              {debugUiMode ? (
                <span
                  className={`app-title__debug${debugBadgeReveal ? " app-title__debug--reveal" : ""}`}
                  onAnimationEnd={(e) => {
                    if (e.animationName === "appTitleDebugReveal") setDebugBadgeReveal(false);
                  }}
                >
                  Debug
                </span>
              ) : null}
            </h1>
            <p
              className={`app-sub${
                ready && showHeaderTaglines && headerSlogan ? " app-sub--tagline" : ""
              }`}
            >
              {ready && showHeaderTaglines && headerSlogan ? headerSlogan : APP_UI_VERSION}
              {debugUiMode ? (
                <>
                  {cloudComparisonEnabled ? (
                    <span className="debug-badge-compare-wrap">
                      <span className="debug-badge debug-badge--compare">ПОРІВНЯННЯ</span>
                      <button
                        type="button"
                        className="debug-badge-compare-exit"
                        aria-label="Вимкнути режим порівняння"
                        title="Вимкнути порівняння"
                        onClick={() => {
                          void exitCompareMode();
                        }}
                        disabled={isRunning}
                      >
                        ×
                      </button>
                    </span>
                  ) : null}
                </>
              ) : null}
            </p>
          </div>
        </div>
        <div
          className={`cloud-switch-wrap cloud-cluster ${cloudMode ? "cloud-cluster--cloud" : "cloud-cluster--local"}`}
        >
          <ModeSegmentToggle
            cloudMode={cloudMode}
            onLocal={() => {
              if (cloudMode) handleCloudSwitch(false);
            }}
            onCloud={() => {
              if (!cloudMode) handleCloudSwitch(true);
            }}
          />
          <div className={`cloud-model-badge-slot ${cloudMode ? "is-open" : ""}`} aria-hidden={!cloudMode}>
            <div className="cloud-model-badge-slot-inner">
              <TooltipWrap tip={cloudHeaderModelFull}>
                <button
                  type="button"
                  className="cloud-model-badge"
                  tabIndex={cloudMode ? undefined : -1}
                  onClick={() => {
                    setCloudDraft(buildCloudDraft());
                    setShowCloudModal(true);
                  }}
                >
                  {cloudHeaderModelShort}
                </button>
              </TooltipWrap>
            </div>
          </div>
        </div>
        {showSystemMetrics && (
          <div className="metrics-hud">
            <MetricMiniBar
              label="CPU"
              value={systemMetrics?.cpu_percent}
              max={100}
              text={fmtNumber(systemMetrics?.cpu_percent, "%")}
            />
            <MetricMiniBar
              label="OLLAMA CPU"
              value={systemMetrics?.ollama_cpu_percent}
              max={100}
              text={fmtNumber(systemMetrics?.ollama_cpu_percent, "%")}
            />
            <MetricMiniBar
              label="APP RAM"
              value={systemMetrics?.app_ram_mb}
              max={4096}
              text={fmtNumber(systemMetrics?.app_ram_mb, "MB")}
            />
            <MetricMiniBar
              label="GPU"
              value={systemMetrics?.gpu_util_percent}
              max={100}
              text={fmtNumber(systemMetrics?.gpu_util_percent, "%")}
            />
            <MetricMiniBar
              label="OLLAMA RAM"
              value={systemMetrics?.ollama_ram_mb}
              max={16384}
              text={fmtNumber(systemMetrics?.ollama_ram_mb, "MB")}
            />
            <div className="metrics-temps metric-mini">
              <span>CPU {fmtNumber(systemMetrics?.cpu_temp_c, "°C")}</span>
              <span>GPU {fmtNumber(systemMetrics?.gpu_temp_c, "°C")}</span>
            </div>
          </div>
        )}
        <div className="header-right">
          {runTimerVisible && (
            <span className={`run-timer ${runTimerExiting ? "is-leaving" : "is-entering"}`}>
              {formatDurationClock(elapsedSec)}
            </span>
          )}
          <span className="status-pill-wrap">
            {debugUiMode && autosaveIndicatorMounted && (
              <span
                className={`autosave-indicator autosave-indicator--${autosaveStatus} autosave-indicator--overlay${autosaveIndicatorVisible ? " autosave-indicator--shown" : ""}`}
                role="status"
                aria-live="polite"
                aria-label={
                  autosaveStatus === "saving"
                    ? "Збереження"
                    : autosaveStatus === "saved"
                      ? "Збережено"
                      : "Помилка збереження"
                }
              >
                <span className="autosave-indicator__layer autosave-indicator__layer--saving" aria-hidden>
                  <svg className="autosave-indicator__spinner" width="14" height="14" viewBox="0 0 24 24">
                    <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="2.5" opacity="0.22" />
                    <path
                      d="M12 3a9 9 0 0 1 9 9"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2.5"
                      strokeLinecap="round"
                    />
                  </svg>
                </span>
                <span className="autosave-indicator__layer autosave-indicator__layer--saved" aria-hidden>
                  <svg className="autosave-indicator__check" width="14" height="14" viewBox="0 0 24 24" fill="none">
                    <circle cx="12" cy="12" r="9" fill="currentColor" opacity="0.14" />
                    <path
                      d="M8 12.2l2.4 2.4L16 9.2"
                      stroke="currentColor"
                      strokeWidth="2.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </span>
                <span className="autosave-indicator__layer autosave-indicator__layer--error" aria-hidden>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <circle cx="12" cy="12" r="9" opacity="0.2" />
                    <path d="M15 9l-6 6M9 9l6 6" strokeLinecap="round" />
                  </svg>
                </span>
              </span>
            )}
            <span className={`status-pill ${isRunning ? (isPaused ? "paused" : "running") : "idle"}`}>
              <span className="status-dot" />
              {statusText}
            </span>
          </span>
        </div>
      </header>

      <div className="layout">
        <aside className="sidebar">
          <div className="sidebar-body">
          <section className="card">
            <div className="card-title">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 7h18M3 12h18M3 17h18"/></svg>
              Основні параметри
            </div>

            <FolderInput
              label="Папка декларацій"
              tooltip={SIDEBAR_TOOLTIPS.inputDir}
              value={inputDir}
              onChange={setInputDir}
              onBrowse={() => pickFolder(setInputDir)}
            />
            <FolderInput
              label="Папка оброблених"
              tooltip={SIDEBAR_TOOLTIPS.processedDir}
              value={processedDir}
              onChange={setProcessedDir}
              onBrowse={() => pickFolder(setProcessedDir)}
            />

            <div className="field-row field-row--queue">
              <div className="field-queue-split">
                <div
                  className={`field-queue-split-left${fileQueueMode === "pick" ? " field-queue-split-left--muted" : ""}`}
                >
                  <LabelWithTooltip
                    as="label"
                    className="field-label field-label--queue-count"
                    text="Файлів:"
                    tip={SIDEBAR_TOOLTIPS.maxFiles}
                  />
                  <input
                    className={`field-input field-input--short field-input--queue-count${fileQueueMode === "pick" ? " field-input--muted" : ""}`}
                    type="number"
                    value={maxFiles}
                    onChange={(e) => setMaxFiles(sanitizeInt(e.target.value, { fallback: 1, min: 0 }))}
                    disabled={fileQueueMode === "pick"}
                  />
                </div>
                <div className="field-queue-split-right">
                  <SortDropdown
                    open={sortDropdownOpen}
                    sortOrder={sortOrder}
                    sortModeActive={fileQueueMode === "sort"}
                    anchorRef={sortDropdownAnchorRef}
                    menuRef={sortDropdownMenuRef}
                    onToggleOpen={() => {
                      setFilePickerOpen(false);
                      setSortDropdownOpen((o) => !o);
                    }}
                    onPick={(order) => {
                      setSortOrder(order);
                      setFileQueueMode("sort");
                      setSelectedFiles([]);
                      setSortDropdownOpen(false);
                    }}
                  />
                  <TooltipWrap tip={SIDEBAR_TOOLTIPS.queueFolder}>
                    <button
                      type="button"
                      className={`queue-btn queue-btn--catalog${fileQueueMode === "pick" ? " queue-btn--active" : ""}`}
                      aria-pressed={fileQueueMode === "pick"}
                      onClick={() => {
                        setSortDropdownOpen(false);
                        setFilePickerDraft(new Set(selectedFiles));
                        setFilePickerOpen(true);
                      }}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                      </svg>
                      <span className="queue-btn__catalog-label">Каталог</span>
                      {fileQueueMode === "pick" && selectedFiles.length > 0 ? (
                        <span className="queue-btn__badge">{selectedFiles.length}</span>
                      ) : null}
                    </button>
                  </TooltipWrap>
                </div>
              </div>
            </div>

            <div
              className={`local-only-fields ${cloudMode ? "local-only-fields--collapsed" : "local-only-fields--expanded"}`}
            >
              <div className="local-only-fields-inner">
                <div className="field-row">
                  <LabelWithTooltip as="label" className="field-label" text="Модель" tip={SIDEBAR_TOOLTIPS.model} />
                  <div className="field-input-group">
                    <input
                      className="field-input"
                      list="model-list"
                      value={model}
                      onChange={(e) => setModel(e.target.value)}
                    />
                    <datalist id="model-list">
                      {models.map((m) => <option key={m} value={m} />)}
                    </datalist>
                    <TooltipWrap tip="Оновити список моделей з Ollama">
                      <button type="button" className="btn-browse" onClick={() => loadModels(host)}>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                          <path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/>
                          <path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/>
                        </svg>
                      </button>
                    </TooltipWrap>
                  </div>
                </div>
                {modelListError && !cloudMode ? (
                  <div className="cloud-error">{modelListError}</div>
                ) : null}

                <div className="field-row">
                  <LabelWithTooltip as="label" className="field-label" text="Хост Ollama" tip={SIDEBAR_TOOLTIPS.host} />
                  <input className="field-input" value={host} onChange={(e) => setHost(e.target.value)} />
                </div>
              </div>
            </div>
          </section>

          <section className="card">
            <div className="card-title">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
              Опції
            </div>
            {/* DEEP_RESEARCH: напівпрозорий перемикач — бекенд ігнорує move_processed */}
            <div className={deepResearchActive ? "move-processed-dr" : undefined}>
              <Toggle
                label="Переміщати оброблені JSON"
                tooltip={SIDEBAR_TOOLTIPS.moveProcessed}
                checked={moveProcessed}
                onChange={setMoveProcessed}
                disabled={deepResearchActive}
              />
              {deepResearchActive && (
                <p className="move-processed-dr-note">
                  У режимі досьє не застосовується — декларації лишаються в папці дослідження.
                </p>
              )}
            </div>
            <Toggle
              label="Зберігати дублікати декларацій в звіті"
              tooltip={SIDEBAR_TOOLTIPS.noDedupe}
              checked={noDedupe}
              onChange={setNoDedupe}
            />
          </section>

          <section className="card card--tools">
            <div className="card-title">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
              </svg>
              Інструменти
            </div>
            <div className="sidebar-tools">
              <div className="sidebar-tools-row">
                <div
                  className={`sidebar-tools-cell${deepResearchActive ? " sidebar-tools-cell--with-exit" : ""}`}
                >
                  <button
                    type="button"
                    className={`btn-tool btn-tool--dossier${deepResearchActive ? " btn-tool--dossier-active" : ""}`}
                    onClick={() => {
                      setDeepResearchError("");
                      setDeepResearchTab("download");
                      setDeepResearchSelectedFolder("");
                      setDeepResearchOpen(true);
                    }}
                    disabled={!ready || isRunning || deepResearchLoading}
                  >
                    Режим досьє
                  </button>
                  {deepResearchActive && (
                    <TooltipWrap tip="Вийти з режиму досьє" className="sidebar-tools-exit-anchor">
                      <button
                        type="button"
                        className="btn-tool-exit"
                        aria-label="Вийти з режиму досьє"
                        onClick={exitDeepResearchMode}
                        disabled={isRunning}
                      >
                        ×
                      </button>
                    </TooltipWrap>
                  )}
                </div>
                <div className="sidebar-tools-cell">
                  <button
                    type="button"
                    className="btn-tool btn-tool--parse"
                    onClick={() => {
                      setParseError("");
                      setParseDeclId("");
                      setParseTab("single");
                      setParseBulkDir(inputDir);
                      setParseModalOpen(true);
                    }}
                    disabled={!ready || isRunning || parseLoading}
                  >
                    Парсинг
                  </button>
                </div>
              </div>
            </div>
          </section>

          <section className="card">
            <button
              type="button"
              className="adv-toggle"
              id="advanced-settings-toggle"
              aria-expanded={advancedOpen}
              aria-controls="advanced-settings-panel"
              onClick={() => setAdvancedOpen(!advancedOpen)}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"
                className={advancedOpen ? "adv-toggle-chevron adv-toggle-chevron--open" : "adv-toggle-chevron"}>
                <polyline points="9 18 15 12 9 6"/>
              </svg>
              Розширені налаштування
            </button>

            <div
              id="advanced-settings-panel"
              ref={advPanelRef}
              className={advancedOpen ? "adv-content adv-content--open" : "adv-content"}
              role="region"
              aria-labelledby="advanced-settings-toggle"
            >
              <div className="adv-content-inner">
                <div className="compact-mode-field">
                  <Toggle
                    label={compactLegacyPayload ? "Детальніше" : "Економніше"}
                    tooltip={
                      compactLegacyPayload
                        ? SIDEBAR_TOOLTIPS.compactDetailed
                        : SIDEBAR_TOOLTIPS.compactEconomical
                    }
                    checked={compactLegacyPayload}
                    onChange={setCompactLegacyPayload}
                  />
                  <button
                    type="button"
                    className="welcome-help-btn compact-mode-help-trigger"
                    aria-label="Пояснення режимів компактизації"
                    onClick={() => setCompactModeHelpOpen(true)}
                  >
                    ?
                  </button>
                </div>

                <div className="adv-settings-launch">
                  <button
                    type="button"
                    className="btn-tool btn-tool--adv-requests"
                    onClick={() => {
                      setErrorActionTargetFile(null);
                      setRequestSettingsModalOpen(true);
                    }}
                  >
                    Налаштування запитів
                  </button>
                  <button
                    type="button"
                    className="btn-tool btn-tool--adv-files"
                    onClick={() => setOutputFilesModalOpen(true)}
                  >
                    Файли виводу
                  </button>
                </div>
              </div>
            </div>
          </section>

          {debugUiMode && (
            <section className="card">
              <button
                type="button"
                className="adv-toggle"
                id="debug-settings-toggle"
                aria-expanded={debugSettingsOpen}
                aria-controls="debug-settings-panel"
                onClick={() => setDebugSettingsOpen(!debugSettingsOpen)}
              >
                <svg
                  width="12"
                  height="12"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                  className={
                    debugSettingsOpen ? "adv-toggle-chevron adv-toggle-chevron--open" : "adv-toggle-chevron"
                  }
                >
                  <polyline points="9 18 15 12 9 6" />
                </svg>
                DEBUG налаштування
              </button>

              <div
                id="debug-settings-panel"
                className={debugSettingsOpen ? "adv-content adv-content--open" : "adv-content"}
                role="region"
                aria-labelledby="debug-settings-toggle"
              >
                <div className="adv-content-inner">
                  <Toggle
                    label="Створити табличні звіти"
                    tooltip={SIDEBAR_TOOLTIPS.makeReport}
                    checked={makeReport}
                    onChange={setMakeReport}
                  />

                  <div className="prompt-session-row">
                    <button
                      type="button"
                      className="btn-prompt-session"
                      onClick={openPromptEditor}
                      disabled={!ready || isRunning}
                    >
                      Редагувати промпт
                    </button>
                    {sessionPromptOverrides ? (
                      <span className="prompt-session-badge">активні підміни сесії</span>
                    ) : null}
                  </div>

                  <button
                    type="button"
                    className="btn-parse-one"
                    onClick={runExtraReportHtml}
                    disabled={!ready || isRunning || extraReportBusy || !outputJsonl.trim()}
                  >
                    {extraReportBusy ? "Формування…" : "Перегенерувати HTML + CSV"}
                  </button>

                  <button
                    type="button"
                    className="btn-danger btn-wipe-traces"
                    onClick={() => setWipeModalOpen(true)}
                    disabled={!ready || isRunning || wipeBusy}
                  >
                    Видалити сліди використання
                  </button>

                  <div className="adv-divider">WIP</div>
                  <button
                    type="button"
                    className="audit-toggle"
                    aria-expanded={wipSettingsOpen}
                    onClick={() => setWipSettingsOpen(!wipSettingsOpen)}
                  >
                    {wipSettingsOpen ? "Приховати WIP" : "WIP"}
                  </button>
                  {wipSettingsOpen ? (
                    <div className="audit-panel">
                      <Toggle
                        label="Показувати навантаження системи"
                        tooltip={SIDEBAR_TOOLTIPS.showSystemMetrics}
                        checked={showSystemMetrics}
                        onChange={setShowSystemMetrics}
                      />
                      <Toggle
                        label="Звук після завершення"
                        tooltip={SIDEBAR_TOOLTIPS.playCompletionSound}
                        checked={playCompletionSound}
                        onChange={setPlayCompletionSound}
                      />
                      <Toggle
                        label="THINK_EVENT Debug"
                        tooltip={SIDEBAR_TOOLTIPS.thinkEventDebug}
                        checked={thinkEventDebug}
                        onChange={setThinkEventDebug}
                      />
                    </div>
                  ) : null}

                  <div className="adv-divider">Режим аудиту (debug)</div>
                  <Toggle
                    label="Режим аудиту"
                    tooltip={SIDEBAR_TOOLTIPS.auditModeEnabled}
                    checked={auditModeEnabled}
                    onChange={setAuditModeEnabled}
                  />
                  <FilePathInput
                    label="Шлях збереження артефактів"
                    tooltip={SIDEBAR_TOOLTIPS.auditModeDir}
                    value={auditModeDir}
                    onChange={setAuditModeDir}
                    onBrowse={() => pickFolder(setAuditModeDir)}
                    disabled={!auditModeEnabled}
                  />
                  <p className="dossier-debug-hint">
                    Зберігає повні артефакти обробки по кожній декларації у кейс-папки. Стандартний
                    шлях: <code>audit</code> (відносно кореня проєкту).
                  </p>
                  <button
                    type="button"
                    className="audit-toggle"
                    onClick={() => setAuditSettingsOpen(!auditSettingsOpen)}
                    disabled={!auditModeEnabled}
                  >
                    {auditSettingsOpen ? "Приховати детальні налаштування" : "Детальні налаштування збору"}
                  </button>
                  {auditSettingsOpen && (
                    <div className="audit-panel">
                      <Toggle
                        label="Оригінальна декларація (raw)"
                        checked={auditCaptureRawDeclaration}
                        onChange={setAuditCaptureRawDeclaration}
                        compact
                      />
                      <Toggle
                        label="Компактна декларація"
                        checked={auditCaptureCompactDeclaration}
                        onChange={setAuditCaptureCompactDeclaration}
                        compact
                      />
                      <Toggle
                        label="Payload запиту до /api/chat"
                        checked={auditCaptureRequestPayload}
                        onChange={setAuditCaptureRequestPayload}
                        compact
                      />
                      <Toggle
                        label="Сира відповідь /api/chat"
                        checked={auditCaptureResponseRaw}
                        onChange={setAuditCaptureResponseRaw}
                        compact
                      />
                      <Toggle
                        label="Розпарсена відповідь моделі"
                        checked={auditCaptureResponseParsed}
                        onChange={setAuditCaptureResponseParsed}
                        compact
                      />
                      <Toggle
                        label="Нормалізований analysis"
                        checked={auditCaptureNormalizedAnalysis}
                        onChange={setAuditCaptureNormalizedAnalysis}
                        compact
                      />
                      <Toggle
                        label="Метадані спроб/помилок/таймінгів"
                        checked={auditCaptureAttemptMeta}
                        onChange={setAuditCaptureAttemptMeta}
                        compact
                      />
                    </div>
                  )}

                  <div className="adv-divider">Підсумок досьє (debug)</div>
                  <p className="dossier-debug-hint">
                    Без повного пайплайну: модель отримує HTML і дописує блок підсумку в файл з поля{" "}
                    <strong>Таблиця (HTML)</strong>. Модель, хост і «Макс. обсяг відповіді» — як у формі;
                    промпти досьє — з <em>Редагувати промпт</em>, якщо збережені.
                  </p>
                  <div className="field-row dossier-debug-actions">
                    <button
                      type="button"
                      className="btn-parse-one"
                      onClick={runDebugDossierHtmlSummary}
                      disabled={!ready || isRunning || dossierSummaryBusy || !tableHtml.trim()}
                    >
                      {dossierSummaryBusy ? "Йде запит до моделі…" : "Згенерувати підсумок досьє"}
                    </button>
                    <TooltipWrap tip="Обрати існуючий report_table.html">
                      <button
                        type="button"
                        className="btn-browse"
                        onClick={() => pickHtmlFileOpen(setTableHtml)}
                        disabled={!ready || isRunning || dossierSummaryBusy}
                      >
                        HTML…
                      </button>
                    </TooltipWrap>
                  </div>

                </div>
              </div>
            </section>
          )}

          <div className="actions">
            <button className="btn-primary" onClick={handleStart} disabled={isRunning || !ready}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              Запустити
            </button>
            <button className="btn-secondary" onClick={handlePause} disabled={!isRunning}>
              {isPaused
                ? <><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg> Продовжити</>
                : <><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="10" y1="15" x2="10" y2="9"/><line x1="15" y1="15" x2="15" y2="9"/></svg> Пауза</>
              }
            </button>
            <button className="btn-danger" onClick={handleStop} disabled={!isRunning}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="3" y="3" width="18" height="18" rx="2"/></svg>
              Стоп
            </button>
            <span className="tooltip-anchor report-tooltip-anchor" tabIndex={0}>
              <button
                type="button"
                className={`btn-report-open${reportBtnPulse === "pulse" ? " btn-report-open--pulse" : ""}${reportBtnPulse === "fade-out" ? " btn-report-open--fade-out" : ""}`}
                onClick={handleOpenReportTable}
                disabled={!ready}
                aria-label="Відкрити report_table.html"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                  <line x1="8" y1="13" x2="16" y2="13" />
                  <line x1="8" y1="17" x2="16" y2="17" />
                </svg>
              </button>
              <span className="tooltip-bubble" role="tooltip">Відкрити report_table.html</span>
            </span>
          </div>
          </div>
          <div className="sidebar-footer">
            {showAboutProgramDock && (
              <div
                className={`about-program-dock${aboutDockFadeIn ? " about-program-dock--visible" : ""}`}
              >
                <button
                  type="button"
                  className="about-program-link"
                  onClick={() => setAboutProgramOpen(true)}
                >
                  Детальніше про програму
                </button>
              </div>
            )}
            <footer className="status-bar">
              <div className="status-task">{taskText || "Очікує запуску"}</div>
            </footer>
          </div>
        </aside>

        <main
          className={`log-panel${showUsageDashboard ? " log-panel--dashboard" : ""}${
            showDossierLive ? " log-panel--dossier" : ""
          }`}
        >
          {showUsageDashboard ? (
            <div className="usage-dash-panel">
              <UsageDashboard
                stats={usageStats}
                loading={usageStatsLoading}
                error={usageStatsError}
              />
            </div>
          ) : showDossierLive ? (
            <div className="dossier-shell">
              <div className="dossier-top-bar">
                <div className="dossier-top-bar__left">
                  {dossierMainView === "dossier" ? (
                    <DossierProgressStrip {...dossierProgress} />
                  ) : (
                    <div className="card-title" style={{ marginBottom: 0 }}>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
                      Живий лог
                    </div>
                  )}
                </div>
                <div className="log-actions dossier-top-bar__actions">
                  <div className="log-view-toggle" role="group" aria-label="Вигляд панелі">
                    <button
                      type="button"
                      className={`log-view-toggle-btn${dossierMainView === "dossier" ? " active" : ""}`}
                      onClick={() => setDossierMainView("dossier")}
                    >
                      Досьє
                    </button>
                    <button
                      type="button"
                      className={`log-view-toggle-btn${dossierMainView === "log" ? " active" : ""}`}
                      onClick={() => setDossierMainView("log")}
                    >
                      Лог
                    </button>
                  </div>
                  {dossierMainView === "log" ? (
                    <>
                      <div className="log-view-toggle" role="group" aria-label="Вигляд логу">
                        <button
                          type="button"
                          className={`log-view-toggle-btn${logViewMode === "visual" ? " active" : ""}`}
                          onClick={() => setLogViewModePersist("visual")}
                        >
                          Картки
                        </button>
                        <button
                          type="button"
                          className={`log-view-toggle-btn${logViewMode === "text" ? " active" : ""}`}
                          onClick={() => setLogViewModePersist("text")}
                        >
                          Текст
                        </button>
                      </div>
                      {hasLogSession ? (
                        <>
                          {logViewMode === "text" ? (
                            <button type="button" className="btn-clear" onClick={handleCopyLog}>
                              Копіювати
                            </button>
                          ) : null}
                          <button
                            type="button"
                            className="btn-clear"
                            onClick={() => {
                              resetLogSession();
                              void refreshUsageStats();
                            }}
                          >
                            Очистити
                          </button>
                        </>
                      ) : null}
                    </>
                  ) : null}
                </div>
              </div>
              <div className="dossier-shell-body">
                {dossierMainView === "dossier" ? (
                  <div className="dossier-panel-wrap">
                    <DossierPanel
                      chartData={dossierChartData}
                      chartLoading={dossierChartLoading}
                      chartError={dossierChartError}
                      isRunning={isRunning}
                      progress={progress}
                      activeProcessing={activeProcessing}
                      pipelineMaxConcurrent={pipelineMaxConcurrent}
                      visualEntries={visualEntries}
                    />
                  </div>
                ) : logViewMode === "text" ? (
                  <div className="log-body log-body--dossier-log" ref={logRef}>
                    {logLines.length === 0
                      ? <div className="log-empty">Лог з&apos;явиться після запуску пайплайну...</div>
                      : logLines.map((line, i) => <LogLine key={i} line={line} />)}
                  </div>
                ) : (
                  <div className="log-body log-body--visual log-body--dossier-log">
                    <VisualLogPanel
                      entries={visualEntries}
                      pendingThink={pendingThink}
                      processingEntry={processingEntry}
                      activeProcessing={activeProcessing}
                      exitingProcessing={exitingProcessing}
                      isRunning={isRunning}
                      progress={progress}
                      runTotals={visualRunTotals}
                      modelLabel={visualModelLabel}
                      feedRef={visualLogRef}
                      pendingErrorCount={pendingErrorCount}
                      errorActionBusy={errorActionBusy}
                      onErrorRetry={(file) => handlePipelineErrorAction(file, "retry")}
                      onErrorIgnore={(file) => handlePipelineErrorAction(file, "ignore")}
                      onErrorRaiseLimits={handleErrorRaiseLimits}
                    />
                  </div>
                )}
              </div>
            </div>
          ) : (
            <>
              <div className="log-header">
                <div className="card-title" style={{ marginBottom: 0 }}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
                  Живий лог
                </div>
                <div className="log-actions">
                  <div className="log-view-toggle" role="group" aria-label="Вигляд логу">
                    <button
                      type="button"
                      className={`log-view-toggle-btn${logViewMode === "visual" ? " active" : ""}`}
                      onClick={() => setLogViewModePersist("visual")}
                    >
                      Картки
                    </button>
                    <button
                      type="button"
                      className={`log-view-toggle-btn${logViewMode === "text" ? " active" : ""}`}
                      onClick={() => setLogViewModePersist("text")}
                    >
                      Текст
                    </button>
                  </div>
                  {hasLogSession && (
                    <>
                      {logViewMode === "text" ? (
                        <button type="button" className="btn-clear" onClick={handleCopyLog}>
                          Копіювати
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className="btn-clear"
                        onClick={() => {
                          resetLogSession();
                          void refreshUsageStats();
                        }}
                      >
                        Очистити
                      </button>
                    </>
                  )}
                </div>
              </div>

              {logViewMode === "text" ? (
                <div className="log-body" ref={logRef}>
                  {logLines.length === 0
                    ? <div className="log-empty">Лог з&apos;явиться після запуску пайплайну...</div>
                    : logLines.map((line, i) => <LogLine key={i} line={line} />)}
                </div>
              ) : (
                <div className="log-body log-body--visual">
                  <VisualLogPanel
                    entries={visualEntries}
                    pendingThink={pendingThink}
                    processingEntry={processingEntry}
                    activeProcessing={activeProcessing}
                    exitingProcessing={exitingProcessing}
                    isRunning={isRunning}
                    progress={progress}
                    runTotals={visualRunTotals}
                    modelLabel={visualModelLabel}
                    feedRef={visualLogRef}
                    pendingErrorCount={pendingErrorCount}
                    errorActionBusy={errorActionBusy}
                    onErrorRetry={(file) => handlePipelineErrorAction(file, "retry")}
                    onErrorIgnore={(file) => handlePipelineErrorAction(file, "ignore")}
                    onErrorRaiseLimits={handleErrorRaiseLimits}
                  />
                </div>
              )}

              {logViewMode === "text" && (isRunning || progress.total > 0) && (
                <div className="progress-bar-wrap">
                  <div className="progress-bar-track">
                    <div className="progress-bar-fill" style={{ width: `${pct}%` }} />
                  </div>
                  <span className="progress-label">
                    {progress.total > 0
                      ? (!isRunning
                          ? `Готово: ${progress.cur} / ${progress.total} (${pct}%)`
                          : `${progress.cur} / ${progress.total} (${pct}%)`)
                      : "Обробка..."}
                  </span>
                </div>
              )}
            </>
          )}
        </main>
      </div>

      <AnimatedModalPresence when={showCloudModal}>
        <CloudSettingsModal
          value={cloudDraft}
          onChange={setCloudDraft}
          onCancel={() => setShowCloudModal(false)}
          ollamaModels={cloudModels}
          openrouterModels={openrouterModels}
          openrouterPricing={openrouterModelPricing}
          openrouterCreditsLoading={openrouterCreditsLoading}
          openrouterCreditsLabel={openrouterCreditsLabel}
          openrouterCreditsHint={openrouterCreditsHint}
          onRefreshOpenrouterCredits={refreshOpenrouterCredits}
          debugMode={debugUiMode}
          onReloadOllamaModels={() => {
            const o = cloudDraft.ollama || {};
            loadCloudModels(o.host, o.api_key);
          }}
          onReloadOpenrouterModels={() => {
            const r = cloudDraft.openrouter || {};
            loadOpenrouterModels(r.host, r.api_key);
          }}
          modelListError={modelListError}
          pipelineMaxConcurrent={pipelineMaxConcurrent}
          onPipelineMaxConcurrentChange={setPipelineMaxConcurrent}
          onOpenComparison={({ provider, host, api_key }) => {
            const seedProvider = provider === "openrouter" ? "openrouter" : "ollama";
            const currentModel =
              seedProvider === "openrouter"
                ? (cloudDraft.openrouter?.model || "").trim()
                : (cloudDraft.ollama?.model || "").trim();
            setCloudComparisonSeedModels((prev) => {
              const base = Array.isArray(prev) ? prev.slice(0, 4) : ["", "", "", ""];
              while (base.length < 4) base.push("");
              if (!String(base[0] || "").trim() && currentModel) {
                base[0] = currentModel;
              }
              return base;
            });
            if (seedProvider !== cloudProvider) {
              setCloudProvider(seedProvider);
            }
            if (seedProvider === "openrouter") {
              if (host) setOpenrouterHost(String(host));
              if (api_key) setOpenrouterApiKey(String(api_key));
            } else {
              if (host) setCloudHost(String(host));
              if (api_key) setCloudApiKey(String(api_key));
            }
            setShowCloudComparisonModal(true);
          }}
          onSave={() => {
            const nextProvider = cloudDraft.provider === "openrouter" ? "openrouter" : "ollama";
            const o = cloudDraft.ollama || {};
            const r = cloudDraft.openrouter || {};
// Persist both provider field sets (Ollama and OpenRouter) so switching tabs
// does not "wipe" the unselected provider's values.
            setCloudHost((o.host || "").trim() || "https://ollama.com");
            setCloudModel((o.model || "").trim());
            setCloudApiKey((o.api_key || "").trim());
            setOpenrouterHost((r.host || "").trim() || "https://openrouter.ai/api/v1");
            setOpenrouterModel((r.model || "").trim() || "meta-llama/llama-3.3-70b-instruct");
            setOpenrouterApiKey((r.api_key || "").trim());
            setCloudProvider(nextProvider);
            setCloudMode(true);
            setShowCloudModal(false);
          }}
        />
      </AnimatedModalPresence>
      <AnimatedModalPresence when={showCloudComparisonModal}>
        <CloudComparisonModal
          open={showCloudComparisonModal}
          provider={cloudProvider}
          host={cloudProvider === "openrouter" ? openrouterHost : cloudHost}
          tableHtml={tableHtml}
          initialCount={cloudComparisonCount}
          openrouterPricing={cloudProvider === "openrouter" ? openrouterModelPricing : null}
          models={
            cloudProvider === "openrouter"
              ? sortModelsAZ(Array.from(new Set([...(openrouterModels || []), ...OPENROUTER_FALLBACK_MODELS])))
              : sortModelsAZ(cloudModels || [])
          }
          defaultSelection={cloudComparisonSeedModels}
          onReloadModels={() => {
            if (cloudProvider === "openrouter") {
              loadOpenrouterModels(openrouterHost, openrouterApiKey);
            } else {
              loadCloudModels(cloudHost, cloudApiKey);
            }
          }}
          onCancel={() => setShowCloudComparisonModal(false)}
          onConfirm={({ count, compare_models }) => {
            const clean = Array.isArray(compare_models)
              ? compare_models.map((m) => String(m || "").trim()).filter(Boolean).slice(0, 4)
              : [];
            const next = clean.slice(0, 4);
            while (next.length < 4) next.push("");
            setCloudComparisonCount(Math.min(4, Math.max(2, Number(count) || clean.length || 2)));
            setCloudComparisonSeedModels(next);
            setCloudComparisonEnabled(clean.length >= 2);
            appendLog(
              clean.length >= 2
                ? `[COMPARE] Налаштовано моделі: ${clean.join(" | ")}. Запуск через кнопку «Запустити».\n`
                : "[COMPARE] Режим порівняння вимкнено.\n"
            );
          }}
        />
      </AnimatedModalPresence>
      <AnimatedModalPresence when={showCloudWarning}>
        <CloudWarningModal
          onCancel={() => setShowCloudWarning(false)}
          onConfirm={() => {
            setShowCloudWarning(false);
            setCloudWarningAcceptedSession(true);
            if (!hasSavedCloudPrefs) {
              setCloudDraft(buildCloudDraft());
              setShowCloudModal(true);
            } else {
              setCloudMode(true);
            }
          }}
        />
      </AnimatedModalPresence>
      <AnimatedModalPresence when={filePickerOpen}>
        <FilePickerModal
          loading={filePickerLoading}
          listError={filePickerListError}
          files={availableFiles}
          declFolderCount={pickerDeclCount}
          procFolderCount={pickerProcCount}
          draftSelected={filePickerDraft}
          openrouterCostHint={filePickerOpenrouterCostHint}
          onToggleFile={(name) => {
            setFilePickerDraft((prev) => {
              const next = new Set(prev);
              if (next.has(name)) next.delete(name);
              else next.add(name);
              return next;
            });
          }}
          onSelectAllFiltered={(filtered) => {
            const names = filtered.map((f) => f.name);
            setFilePickerDraft((prev) => {
              const allOn = names.length > 0 && names.every((n) => prev.has(n));
              const next = new Set(prev);
              if (allOn) names.forEach((n) => next.delete(n));
              else names.forEach((n) => next.add(n));
              return next;
            });
          }}
          onCancel={() => setFilePickerOpen(false)}
          onApply={() => {
            if (filePickerDraftEffective.size === 0 || filePickerLoading) return;
            const ordered = availableFiles
              .filter((f) => filePickerDraftEffective.has(f.name))
              .map((f) => f.name);
            setSelectedFiles(ordered);
            setFilePickerDraft(new Set(ordered));
            setFileQueueMode("pick");
            setFilePickerOpen(false);
          }}
          applyDisabled={filePickerDraftEffective.size === 0 || filePickerLoading}
          draftSelectedCount={filePickerDraftEffective.size}
          onOverlayMouseDown={() => setFilePickerOpen(false)}
          onOpenDeclarationsFolder={openDeclarationsFolder}
        />
      </AnimatedModalPresence>
      {/* DEEP_RESEARCH */}
      <AnimatedModalPresence when={deepResearchOpen}>
        <DeepResearchModal
          tab={deepResearchTab}
          onTab={(t) => {
            setDeepResearchTab(t);
            setDeepResearchError("");
          }}
          userDeclarantId={deepResearchUid}
          onChangeId={setDeepResearchUid}
          folders={deepResearchFolders}
          foldersLoading={deepResearchFoldersLoading}
          selectedFolder={deepResearchSelectedFolder}
          onSelectFolder={setDeepResearchSelectedFolder}
          onRefreshFolders={refreshDeepResearchFolders}
          loading={deepResearchLoading}
          loadingHint={deepResearchLoadingHint}
          downloadProgress={deepResearchDownloadProgress}
          error={deepResearchError}
          onCancel={() => !deepResearchLoading && setDeepResearchOpen(false)}
          onSubmitDownload={handleDeepResearchSubmit}
          onApplyExisting={handleDeepResearchApplyExisting}
        />
      </AnimatedModalPresence>
      <AnimatedModalPresence when={promptEditorOpen}>
        <PromptSessionModal
          tab={promptEditorTab}
          onTab={setPromptEditorTab}
          draft={promptDraft}
          onDraftField={(field, value) =>
            setPromptDraft((prev) => ({ ...prev, [field]: value }))
          }
          loadingBuiltin={promptBuiltinLoading}
          onClose={() => setPromptEditorOpen(false)}
          onApply={applyPromptSession}
          onResetBuiltin={resetPromptsToBuiltin}
        />
      </AnimatedModalPresence>
      <AnimatedModalPresence when={aboutProgramOpen}>
        <AboutProgramModal
          onClose={() => setAboutProgramOpen(false)}
          onOpenWelcome={() => setWelcomeModalOpen(true)}
          showHeaderTaglines={showHeaderTaglines}
          onShowHeaderTaglinesChange={handleShowHeaderTaglinesChange}
        />
      </AnimatedModalPresence>
      <AnimatedModalPresence when={welcomeModalOpen}>
        <WelcomeModal
          onDismiss={dismissWelcomeModal}
          onOpenBulkParsing={openBulkParseFromWelcome}
          bulkParseDisabled={!ready || isRunning || parseLoading}
        />
      </AnimatedModalPresence>
      <AnimatedModalPresence when={parseModalOpen}>
        <ParseDeclarationModal
          tab={parseTab}
          onTab={(t) => {
            setParseTab(t);
            setParseError("");
          }}
          declarationId={parseDeclId}
          onChangeId={setParseDeclId}
          bulkYear={parseBulkYear}
          bulkUseYear={parseBulkUseYear}
          onChangeBulkUseYear={setParseBulkUseYear}
          bulkQuery={parseBulkQuery}
          onChangeBulkQuery={setParseBulkQuery}
          bulkCount={parseBulkCount}
          bulkDeclarationType={parseBulkDeclarationType}
          bulkDocumentType={parseBulkDocumentType}
          bulkTargetDir={parseBulkDir}
          onChangeBulkYear={setParseBulkYear}
          onChangeBulkCount={setParseBulkCount}
          onChangeBulkDeclarationType={setParseBulkDeclarationType}
          onChangeBulkDocumentType={setParseBulkDocumentType}
          onChangeBulkTargetDir={setParseBulkDir}
          onBrowseBulkTarget={() => pickFolder(setParseBulkDir)}
          loading={parseLoading}
          loadingHint={parseLoadingHint}
          error={parseError}
          onCancel={() => !parseLoading && setParseModalOpen(false)}
          onSubmitSingle={handleParseSingleDeclaration}
          onSubmitBulk={handleParseBulkByYear}
        />
      </AnimatedModalPresence>
      <AnimatedModalPresence when={wipeModalOpen}>
        <WipeUsageTracesModal
          busy={wipeBusy}
          onClose={() => {
            if (!wipeBusy) setWipeModalOpen(false);
          }}
          onConfirm={() => {
            void runDebugWipeUsageTraces();
          }}
        />
      </AnimatedModalPresence>
      <AnimatedModalPresence when={compactModeHelpOpen}>
        <CompactModeHelpModal onClose={() => setCompactModeHelpOpen(false)} />
      </AnimatedModalPresence>
      <AnimatedModalPresence when={requestSettingsModalOpen}>
        <AdvancedRequestSettingsModal
          onDismiss={dismissRequestSettingsModal}
          onConfirm={confirmRequestSettingsModal}
          hasRetryTarget={Boolean(errorActionTargetFile)}
          timeout={timeout}
          setTimeout_={setTimeout_}
          retries={retries}
          setRetries={setRetries}
          retryDelay={retryDelay}
          setRetryDelay={setRetryDelay}
          maxChars={maxChars}
          setMaxChars={setMaxChars}
          numPredict={numPredict}
          setNumPredict={setNumPredict}
        />
      </AnimatedModalPresence>
      <AnimatedModalPresence when={outputFilesModalOpen}>
        <AdvancedOutputFilesModal
          onClose={() => setOutputFilesModalOpen(false)}
          outputJsonl={outputJsonl}
          setOutputJsonl={setOutputJsonl}
          errorsJsonl={errorsJsonl}
          setErrorsJsonl={setErrorsJsonl}
          summaryCsv={summaryCsv}
          setSummaryCsv={setSummaryCsv}
          findingsCsv={findingsCsv}
          setFindingsCsv={setFindingsCsv}
          tableHtml={tableHtml}
          setTableHtml={setTableHtml}
          onPickFile={pickFile}
        />
      </AnimatedModalPresence>
    </div>
  );
}
