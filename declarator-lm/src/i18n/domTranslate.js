/** Best-effort DOM text translator for EN UI entry. */
import { enCatalog } from "./enCatalog";

const ATTRS = ["title", "aria-label", "placeholder", "alt"];

const CONTENT_TAGS = new Set([
  "P",
  "LI",
  "H1",
  "H2",
  "H3",
  "H4",
  "H5",
  "H6",
  "LABEL",
  "BUTTON",
  "OPTION",
  "SUMMARY",
  "LEGEND",
  "FIGCAPTION",
  "DT",
  "DD",
  "TH",
  "TD",
  "SPAN",
  "DIV",
  "STRONG",
  "EM",
  "B",
  "I",
  "SMALL",
  "CODE",
]);

/** Tags whose presence means we must not wipe the element (keep link structure). */
const PRESERVE_CHILD_TAGS = new Set([
  "A",
  "INPUT",
  "TEXTAREA",
  "SELECT",
  "BUTTON",
  "SVG",
  "IMG",
  "VIDEO",
  "IFRAME",
  "CANVAS",
]);

const catalogByNorm = new Map();
for (const [uk, en] of Object.entries(enCatalog)) {
  catalogByNorm.set(norm(uk), en);
}

function norm(s) {
  return String(s || "")
    .replace(/\u00a0/g, " ")
    .replace(/['’ʼ]/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}

function lookup(raw) {
  if (!raw) return null;
  if (Object.prototype.hasOwnProperty.call(enCatalog, raw)) {
    const v = enCatalog[raw];
    return v && v !== raw ? v : null;
  }
  const n = norm(raw);
  if (!n) return null;
  const v = catalogByNorm.get(n);
  return v && v !== n ? v : null;
}

function hasCyrillic(s) {
  return /[\u0400-\u04FF]/.test(s || "");
}

function translateTextNode(node) {
  const raw = node.textContent;
  if (!raw || !hasCyrillic(raw)) return;
  const trimmed = raw.trim();
  if (!trimmed) return;
  const en = lookup(trimmed);
  if (!en) return;
  const lead = raw.match(/^\s*/)[0];
  const trail = raw.match(/\s*$/)[0];
  node.textContent = `${lead}${en}${trail}`;
}

function translateAttrs(el) {
  for (const attr of ATTRS) {
    if (!el.hasAttribute?.(attr)) continue;
    const v = el.getAttribute(attr);
    const en = lookup(v);
    if (en) el.setAttribute(attr, en);
  }
}

function shouldPreserveStructure(el) {
  for (const child of el.querySelectorAll("*")) {
    if (PRESERVE_CHILD_TAGS.has(child.tagName)) return true;
  }
  return false;
}

/**
 * Translate text nodes even inside elements that keep structure (e.g. li + help button).
 * Also try element-level replace when safe.
 */
function translateElementContent(el) {
  if (!CONTENT_TAGS.has(el.tagName)) return;
  const preserve = shouldPreserveStructure(el);
  if (preserve) return;
  const raw = el.textContent;
  if (!raw || !hasCyrillic(raw)) return;
  const en = lookup(raw);
  if (!en) return;
  if (el.tagName === "DIV" || el.tagName === "SPAN") {
    const onlyPhrasing = [...el.children].every((c) =>
      ["STRONG", "EM", "B", "I", "SMALL", "CODE", "BR", "WBR"].includes(c.tagName)
    );
    if (el.children.length && !onlyPhrasing) return;
  }
  el.textContent = en;
}

function walk(node) {
  if (!node) return;
  if (node.nodeType === Node.TEXT_NODE) {
    translateTextNode(node);
    return;
  }
  if (node.nodeType === Node.ELEMENT_NODE) {
    const tag = node.tagName;
    if (tag === "SCRIPT" || tag === "STYLE") return;
    translateAttrs(node);
    // Children first so leaf text nodes get a chance; then element-level
    // catches multi-node paragraphs whose fragments weren't catalogued.
    const children = [...node.childNodes];
    for (const child of children) walk(child);
    translateElementContent(node);
  }
}

export function installDomTranslator(root = document.body) {
  if (!root) return () => {};
  walk(root);
  const obs = new MutationObserver((mutations) => {
    for (const m of mutations) {
      if (m.type === "characterData" && m.target) walk(m.target);
      if (m.type === "attributes" && m.target) translateAttrs(m.target);
      for (const n of m.addedNodes || []) walk(n);
    }
  });
  obs.observe(root, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
    attributeFilter: ATTRS,
  });
  return () => obs.disconnect();
}
