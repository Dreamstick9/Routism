import TerminalDemo from "@/components/TerminalDemo";
import SectionLabel from "@/components/ui/SectionLabel";
import { DEMO_H2, DEMO_INSTALL_FOLLOW, DEMO_LABEL } from "@/lib/content";
import {
  API_V1_BASE,
  DASHBOARD_URL,
  INSTALL_COMMAND,
  NO_ACCOUNTS_CLAIM,
} from "@/lib/product-facts";

export default function InstallDemo() {
  return (
    <section
      id="demo"
      data-chapter
      className="border-t border-white/5 bg-void"
      aria-labelledby="demo-title"
    >
      <div className="section-pad mx-auto max-w-3xl text-center">
        <div data-reveal>
          <SectionLabel>{DEMO_LABEL}</SectionLabel>
        </div>
        <h2
          id="demo-title"
          data-reveal
          className="display-title mt-4 !text-4xl text-paper md:!text-5xl"
        >
          {DEMO_H2}
        </h2>
        <p data-reveal className="mx-auto mt-4 max-w-xl text-fog">
          {NO_ACCOUNTS_CLAIM} Run{" "}
          <code className="mono text-paper">{INSTALL_COMMAND}</code>{" "}
          {DEMO_INSTALL_FOLLOW}
        </p>

        <div data-reveal className="mt-12">
          <TerminalDemo />
        </div>

        <p
          data-reveal
          className="mx-auto mt-8 max-w-xl text-center text-sm text-fog-dim"
        >
          Dashboard{" "}
          <a
            className="text-paper underline-offset-2 hover:underline"
            href={DASHBOARD_URL}
          >
            {DASHBOARD_URL}
          </a>{" "}
          · API <span className="mono text-paper">{API_V1_BASE}</span>
        </p>
      </div>
    </section>
  );
}
