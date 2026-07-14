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

export default function TerminalDemo() {
  return (
    <div className="glass mx-auto w-full max-w-2xl overflow-hidden rounded-2xl shadow-[0_24px_80px_rgba(0,0,0,0.5)]">
      <div className="flex items-center gap-2 border-b border-white/10 px-4 py-3">
        <span className="h-2.5 w-2.5 rounded-full bg-[#ff5f57]" aria-hidden />
        <span className="h-2.5 w-2.5 rounded-full bg-[#febc2e]" aria-hidden />
        <span className="h-2.5 w-2.5 rounded-full bg-[#28c840]" aria-hidden />
        <span className="ml-2 mono text-xs text-[var(--fog-dim)]">setup.sh</span>
        <div className="ml-auto">
          <CopyButton
            text={INSTALL_SNIPPET}
            label="Copy install"
            event="copy_install"
          />
        </div>
      </div>
      <pre
        className="mono overflow-x-auto p-5 text-[11px] leading-relaxed text-[var(--fog)] md:text-xs"
        data-install-snippet={INSTALL_SNIPPET}
      >
        <code>
          <span className="text-[var(--fog-dim)]">$ </span>
          {INSTALL_COMMAND}
          {"\n"}
          <span className="text-[var(--fog-dim)]">$ </span>
          routism
          {"\n"}
          <span className="text-[var(--filament)]">
            # Dashboard {DASHBOARD_URL} · API {API_V1_BASE}
          </span>
          {"\n\n"}
          <span className="text-[var(--fog-dim)]"># Agent env</span>
          {"\n"}
          {AGENT_ENV_SNIPPET}
          {"\n"}
          <span className="text-[var(--pulse)]"># ready — model {MODEL_ID}</span>
        </code>
      </pre>
      <div className="flex flex-wrap gap-2 border-t border-white/10 px-4 py-3">
        <CopyButton
          text={INSTALL_COMMAND}
          label="Copy ./install.sh"
          event="copy_install_cmd"
        />
        <CopyButton
          text={AGENT_ENV_SNIPPET}
          label="Copy agent env"
          event="copy_agent_env"
        />
      </div>
    </div>
  );
}
