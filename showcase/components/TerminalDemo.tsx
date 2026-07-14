"use client";

import {
  AGENT_ENV_SNIPPET,
  API_V1_BASE,
  DASHBOARD_URL,
  INSTALL_COMMAND,
  INSTALL_SNIPPET,
  MODEL_ID,
} from "@/lib/product-facts";
import CopyButton from "./CopyButton";

/**
 * Craft terminal — cream/black editorial chrome (no glass cyan).
 */
export default function TerminalDemo() {
  return (
    <div className="mx-auto w-full max-w-2xl overflow-hidden rounded-sm border border-white/10 bg-charcoal-soft shadow-[0_24px_80px_rgba(0,0,0,0.45)]">
      <div className="flex items-center gap-2 border-b border-white/10 bg-cream px-4 py-3">
        <span className="h-2.5 w-2.5 rounded-full bg-ink/25" aria-hidden />
        <span className="h-2.5 w-2.5 rounded-full bg-ink/25" aria-hidden />
        <span className="h-2.5 w-2.5 rounded-full bg-ink/25" aria-hidden />
        <span className="mono ml-2 text-xs text-ink/55">setup.sh</span>
        <div className="ml-auto">
          <CopyButton
            text={INSTALL_SNIPPET}
            label="Copy install"
            event="copy_install"
            variant="on-light"
          />
        </div>
      </div>
      <pre
        className="mono overflow-x-auto bg-void p-5 text-[11px] leading-relaxed text-fog md:text-xs"
        data-install-snippet={INSTALL_SNIPPET}
      >
        <code>
          <span className="text-fog-dim">$ </span>
          <span className="text-paper">{INSTALL_COMMAND}</span>
          {"\n"}
          <span className="text-fog-dim">$ </span>
          <span className="text-paper">routism</span>
          {"\n"}
          <span className="text-accent-lime">
            # Dashboard {DASHBOARD_URL} · API {API_V1_BASE}
          </span>
          {"\n\n"}
          <span className="text-fog-dim"># Agent env</span>
          {"\n"}
          <span className="text-paper/85">{AGENT_ENV_SNIPPET}</span>
          {"\n"}
          <span className="text-signal-hot"># ready — model {MODEL_ID}</span>
        </code>
      </pre>
      <div className="flex flex-wrap gap-2 border-t border-white/10 bg-void px-4 py-3">
        <CopyButton
          text={INSTALL_COMMAND}
          label={`Copy ${INSTALL_COMMAND}`}
          event="copy_install_cmd"
          variant="on-dark"
        />
        <CopyButton
          text={AGENT_ENV_SNIPPET}
          label="Copy agent env"
          event="copy_agent_env"
          variant="on-dark"
        />
      </div>
    </div>
  );
}
