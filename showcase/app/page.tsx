import Nav from "@/components/Nav";
import SkipLink from "@/components/SkipLink";
import FooterRed from "@/components/FooterRed";
import SmoothScroll from "@/components/SmoothScroll";
import HeroWorld from "@/components/chapters/HeroWorld";
import StoryHook from "@/components/chapters/StoryHook";
import ArchitecturePlate from "@/components/chapters/ArchitecturePlate";
import TypeSplitMorph from "@/components/chapters/TypeSplitMorph";
import InstallDemo from "@/components/chapters/InstallDemo";
import ProofCards from "@/components/chapters/ProofCards";
import WeightsList from "@/components/chapters/WeightsList";
import EcosystemOrbit from "@/components/chapters/EcosystemOrbit";
import VariantsMarquee from "@/components/chapters/VariantsMarquee";
import DownloadBand from "@/components/chapters/DownloadBand";
import { AGENT_ENV_SNIPPET } from "@/lib/product-facts";

/**
 * Editorial chapter composition (static MVP).
 * Order: world → hook → split → (type) → demo → proof → (weights) →
 * (ecosystem) → (marquee) → download. Section ids locked for tests/nav.
 */
export default function HomePage() {
  return (
    <SmoothScroll>
      <SkipLink />
      <Nav />

      <main id="main">
        <HeroWorld />
        <StoryHook />
        <ArchitecturePlate />
        <TypeSplitMorph />
        <InstallDemo />
        <ProofCards />
        <WeightsList />
        <EcosystemOrbit />
        <VariantsMarquee />
        <DownloadBand />
      </main>

      <FooterRed />
      {/* keep agent env fact available for scrapers / tests consumers */}
      <span className="sr-only">{AGENT_ENV_SNIPPET}</span>
    </SmoothScroll>
  );
}
