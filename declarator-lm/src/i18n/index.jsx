/** React context providing the current UI locale and the t() translation helper. */
import { createContext, useContext, useMemo } from "react";
import { enCatalog } from "./enCatalog";

const I18nContext = createContext({
  locale: "uk",
  t: (key) => key,
});

function format(template, vars) {
  if (!vars || typeof template !== "string") return template;
  return template.replace(/\{(\w+)\}/g, (_, name) =>
    vars[name] != null ? String(vars[name]) : `{${name}}`
  );
}

export function createT(locale) {
  const catalog = locale === "en" ? enCatalog : null;
  return (key, vars) => {
    const base = catalog && Object.prototype.hasOwnProperty.call(catalog, key)
      ? catalog[key]
      : key;
    return format(base, vars);
  };
}

export function I18nProvider({ locale = "uk", children }) {
  const value = useMemo(() => {
    const t = createT(locale);
    return { locale, t };
  }, [locale]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  return useContext(I18nContext);
}

export function useT() {
  return useI18n().t;
}
