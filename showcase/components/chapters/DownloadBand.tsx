"use client";

import CopyButton from "@/components/CopyButton";
import SectionLabel from "@/components/ui/SectionLabel";
import {
  DOWNLOAD_AGENT_MODEL_LEAD,
  DOWNLOAD_BODY,
  DOWNLOAD_COPY_SETUP,
  DOWNLOAD_CTA_GITHUB,
  DOWNLOAD_ENV_LEAD,
  DOWNLOAD_H1_LINES,
  DOWNLOAD_LABEL,
} from "@/lib/content";
import {
  API_V1_BASE,
  GITHUB_URL,
  INSTALL_COMMAND,
  INSTALL_SNIPPET,
  MODEL_ID,
} from "@/lib/product-facts";
import { track } from "@/lib/analytics";

export default function DownloadBand() {
  return (
    <section
      id="download"
      data-chapter
      className="field-cream border-t border-black/5 bg-cream"
      aria-labelledby="download-title"
    >
      <div className="section-pad mx-auto max-w-3xl text-center">
        <div data-reveal>
          <SectionLabel tone="on-light">{DOWNLOAD_LABEL}</SectionLabel>
        </div>
        <h2
          id="download-title"
          data-reveal
          className="display-title mt-4 text-ink"
        >
          {DOWNLOAD_H1_LINES[0]}
          <br />
          <span className="text-signal">{DOWNLOAD_H1_LINES[1]}</span>
        </h2>
        <p data-reveal className="mx-auto mt-6 max-w-lg text-ink/75">
          {DOWNLOAD_BODY}
        </p>

        <div
          data-reveal
          className="mt-10 flex flex-wrap items-center justify-center gap-3"
        >
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="cta-primary"
            data-cta="github-download"
            data-github-url={GITHUB_URL}
            onClick={() => track("cta_github", { where: "download" })}
          >
            {DOWNLOAD_CTA_GITHUB}
          </a>
          <CopyButton
            text={INSTALL_COMMAND}
            label={`Copy ${INSTALL_COMMAND}`}
            event="copy_install_cmd"
            variant="on-light"
          />
          <CopyButton
            text={INSTALL_SNIPPET}
            label={DOWNLOAD_COPY_SETUP}
            event="copy_install"
            variant="on-light"
          />
        </div>

        <pre
          data-reveal
          data-install-snippet={INSTALL_SNIPPET}
          className="mono mx-auto mt-10 max-w-xl overflow-x-auto rounded-sm border border-black/10 bg-ink p-4 text-left text-[11px] text-paper/85"
        >
          {INSTALL_SNIPPET}
        </pre>

        <p data-reveal className="mt-6 text-xs text-ink/55">
          {DOWNLOAD_AGENT_MODEL_LEAD}{" "}
          <span className="mono text-ink">{MODEL_ID}</span>
          {" · "}
          {DOWNLOAD_ENV_LEAD}{" "}
          <span className="mono">OPENAI_BASE_URL={API_V1_BASE}</span>
        </p>
      </div>
    </section>
  );
}
