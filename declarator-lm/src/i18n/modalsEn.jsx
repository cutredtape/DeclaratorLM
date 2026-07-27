/** English copies of rich-text modals (EN entry only). */

export function CloudHelpBodyEn() {
  return (
    <>
      <h3 className="cloud-help-subtitle">What is this anyway?</h3>
      <p>
        The app has two modes. <strong>Local</strong> — the model runs on your computer
        (needs a capable PC). <strong>Cloud</strong> — the model runs on a remote server;
        your computer just sends requests. Handy if your PC is weak or you do not want to
        install anything locally.
      </p>

      <h3 className="cloud-help-subtitle">Step-by-step: get a free API key</h3>
      <ol className="cloud-help-steps">
        <li>
          Go to{" "}
          <a href="https://ollama.com" target="_blank" rel="noopener noreferrer">
            ollama.com
          </a>{" "}
          and sign up (Sign Up). Google sign-in is enough, or use email and password.
        </li>
        <li>
          After signing in, open Settings (profile settings, usually top-right).
        </li>
        <li>
          Find Keys/API Keys and click &quot;Create new key&quot;. Copy it — a long string like
          sk-abc123.... Store it safely; you will not see the full key again.
        </li>
        <li>Return to DeclaratorLM and click Cloud in the top bar.</li>
        <li>
          In the window that opens, fill in three fields:
          <ul className="cloud-help-fields">
            <li>
              <strong>Cloud host</strong> — leave as is: https://ollama.com
            </li>
            <li>
              <strong>Cloud model</strong> — pick or keep a model (e.g. kimi-k2.5)
            </li>
            <li>
              <strong>API key</strong> — paste the key you copied in step 3
            </li>
          </ul>
        </li>
      </ol>
      <p>Click &quot;Save and enable Cloud&quot;. Done!</p>

      <h3 className="cloud-help-subtitle">Does this cost money?</h3>
      <p>
        Ollama provides a free request allowance. For a moderate number of declarations that
        is usually enough.
      </p>

      <h3 className="cloud-help-subtitle">Alternative: OpenRouter</h3>
      <p>
        The <strong>OpenRouter</strong> tab is a separate path, independent of Ollama.
        OpenRouter exposes hundreds of models (Llama, Claude, Gemini, GPT, Qwen, etc.) via
        one API key — switch with the segmented control at the top of this window; each tab
        keeps its own settings.
      </p>
      <ol className="cloud-help-steps">
        <li>
          Go to{" "}
          <a href="https://openrouter.ai" target="_blank" rel="noopener noreferrer">
            openrouter.ai
          </a>{" "}
          and sign up.
        </li>
        <li>
          In{" "}
          <a href="https://openrouter.ai/settings/keys" target="_blank" rel="noopener noreferrer">
            Settings → Keys
          </a>{" "}
          click &quot;Create Key&quot; and copy the key (starts with <code>sk-or-v1-</code>).
        </li>
        <li>
          In this window&apos;s <strong>OpenRouter</strong> tab, fill in three fields:
          <ul className="cloud-help-fields">
            <li>
              <strong>OpenRouter host</strong> — leave as is: https://openrouter.ai/api/v1
            </li>
            <li>
              <strong>OpenRouter model</strong> — pick a model (e.g.
              meta-llama/llama-3.3-70b-instruct)
            </li>
            <li>
              <strong>OpenRouter API key</strong> — paste the <code>sk-or-v1-...</code> key
            </li>
          </ul>
        </li>
      </ol>
    </>
  );
}

export function AboutProgramBodyEn({ version }) {
  return (
    <>
      <p className="about-program-lead">
        <strong>DeclaratorLM</strong> is a tool for automated analysis of electronic
        declarations.
      </p>
      <p>
        The app loads <code className="deep-research-code">JSON</code> declarations,
        compresses them into a readable format, and uses <strong>artificial intelligence</strong>{" "}
        to find <strong>risks, anomalies, and suspicious links</strong>.
      </p>
      <p>
        Results come as structured reports (
        <code className="deep-research-code">JSON</code>
        {", "}
        <code className="deep-research-code">CSV</code>
        {", "}
        <code className="deep-research-code">HTML</code>
        ) that are easy to browse and analyze.
      </p>
      <p>
        Supports <strong>local models</strong> or{" "}
        <code className="deep-research-code">API</code>, plus <strong>“dossier”</strong> mode —
        for analyzing several declarations of the same person.
      </p>
      <p>
        Built for <strong>researchers, journalists, analysts</strong> and anyone working with{" "}
        <strong>anti-corruption data</strong> or <strong>open registers</strong>.
      </p>
      <p>
        Made for people who want to spend <strong>less time</strong> reading declarations and{" "}
        <strong>more on understanding</strong>.
      </p>
      <div className="about-program-section">
        <p className="about-program-tagline">
          Declarations have been digital since 2016. Analysis only just caught up.
        </p>
        <p className="about-program-credits">
          Built by Oleksandr Matviienko.
          <br />
          Contact:{" "}
          <a href="mailto:ctrlredtape@gmail.com">ctrlredtape@gmail.com</a>
        </p>
      </div>
      <p className="about-program-meta">
        Status: <span className="about-program-status">[in development]</span>
        {" · "}
        Version:{" "}
        <code className="deep-research-code about-program-version">{version}</code>
      </p>
    </>
  );
}

export function CloudWarningBodyEn() {
  return (
    <>
      <p>
        In this mode DeclaratorLM uses external AI services (Ollama Cloud or OpenRouter) to
        analyze declarations.
      </p>
      <p>Public NAZK declarations are usually safe to process in Cloud Mode.</p>
      <p>For private or sensitive documents, Local Mode is recommended.</p>
    </>
  );
}

export function DeepResearchDownloadHintEn() {
  return (
    <p className="deep-research-hint">
      Enter <strong>user_declarant_id</strong> from the open NAZK API. Available declarations
      for that person will be downloaded into the <code className="deep-research-code">deep_research/</code>{" "}
      catalog under a last-name folder.
    </p>
  );
}

export function DeepResearchExistingHintEn() {
  return (
    <p className="deep-research-hint">
      Pick a subdirectory in <code className="deep-research-code">deep_research/</code> that
      already has <code className="deep-research-code">decl_*.json</code> files. The pipeline will
      use them as the queue without calling the API.
    </p>
  );
}

export function CompactModeHelpBodyEn() {
  return (
    <>
      <p className="about-program-lead">
        A NAZK registry declaration is a large, noisy JSON: dozens of technical fields, service
        codes, duplicates, and empty sections. Sending it to the model as-is is expensive, slow,
        and often worse in quality.
      </p>

      <h3 className="compact-mode-help-h3">What is compact mode</h3>
      <p>
        Before analysis the app runs the declaration through <strong>compaction</strong> — it turns
        raw JSON into a tight, ordered structure readable by both humans and the model. At this
        stage the app:
      </p>
      <ul className="welcome-help-list">
        <li>
          keeps only meaningful sections: profile, income, real estate, vehicles, cash, corporate
          rights, family, liabilities, significant changes;
        </li>
        <li>
          computes totals (total income, cash, vehicle/property value) into{" "}
          <code className="deep-research-code">quick_totals</code>;
        </li>
        <li>
          decodes codes: declaration type and period, property owners, family members, banks;
        </li>
        <li>drops empty steps, technical noise, and privacy placeholders.</li>
      </ul>
      <p>
        The result is compact JSON sent to the model as input for risk finding. The switch in
        advanced settings controls <strong>how much raw data</strong> to add to that compact
        structure.
      </p>

      <h3 className="compact-mode-help-h3">
        <span className="compact-mode-help-dot compact-mode-help-dot--green" aria-hidden /> Leaner
        <span className="compact-mode-help-tag">default</span>
      </h3>
      <p>
        Sends only the <strong>compact structure</strong> + banks. Rare non-standard steps are
        added briefly (no full raw copy).
      </p>
      <ul className="welcome-help-list">
        <li>Smallest request → fastest and cheapest in tokens.</li>
        <li>Enough for typical annual declarations.</li>
        <li>Best for batch-processing dozens of files in a row.</li>
      </ul>

      <h3 className="compact-mode-help-h3">
        <span className="compact-mode-help-dot compact-mode-help-dot--blue" aria-hidden /> More detail
      </h3>
      <p>
        A <strong>full raw copy</strong> of every filled declaration step is added to the compact
        structure — as in the original registry JSON.
      </p>
      <ul className="welcome-help-list">
        <li>The model sees all fields and original wording; nothing is “lost” in compression.</li>
        <li>Useful for complex years, change notices, and rare steps where details matter.</li>
        <li>The request is several times larger → analysis is slower and more expensive.</li>
      </ul>

      <p className="compact-mode-help-tip">
        <strong>Tip.</strong> Start with <strong>Leaner</strong>. If the report is empty, shallow,
        or the model “missed” an asset — turn on <strong>More detail</strong> and re-run that
        declaration.
      </p>
    </>
  );
}
