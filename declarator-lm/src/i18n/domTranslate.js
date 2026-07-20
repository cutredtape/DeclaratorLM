/** Best-effort DOM text translator for EN UI entry (exact catalog matches). */
import { enCatalog } from "./enCatalog";

const ATTRS = ["title", "aria-label", "placeholder", "alt"];

function translateTextNode(node) {
  const raw = node.textContent;
  if (!raw) return;
  const trimmed = raw.trim();
  if (!trimmed) return;
  const en = enCatalog[trimmed];
  if (!en || en === trimmed) return;
  const lead = raw.match(/^\s*/)[0];
  const trail = raw.match(/\s*$/)[0];
  node.textContent = `${lead}${en}${trail}`;
}

function translateElement(el) {
  for (const attr of ATTRS) {
    if (!el.hasAttribute?.(attr)) continue;
    const v = el.getAttribute(attr);
    if (v && enCatalog[v]) el.setAttribute(attr, enCatalog[v]);
  }
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
    translateElement(node);
    const children = [...node.childNodes];
    for (const child of children) walk(child);
  }
}

export function installDomTranslator(root = document.body) {
  if (!root) return () => {};
  walk(root);
  const obs = new MutationObserver((mutations) => {
    for (const m of mutations) {
      if (m.type === "characterData" && m.target) walk(m.target);
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
