import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { I18nProvider } from "./i18n";
import { installDomTranslator } from "./i18n/domTranslate";
import "@fontsource/geist/300.css";
import "@fontsource/geist/400.css";
import "@fontsource/geist/500.css";
import "@fontsource/geist/600.css";
import "@fontsource/geist/700.css";
import "@fontsource/geist-mono/400.css";
import "@fontsource/geist-mono/500.css";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <I18nProvider locale="en">
      <App />
    </I18nProvider>
  </React.StrictMode>
);

// Translate exact Ukrainian text nodes / aria labels that were not wrapped with t().
installDomTranslator(document.body);
