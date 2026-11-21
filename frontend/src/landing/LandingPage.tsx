/**
 * LandingPage.tsx — the BuildWise AI marketing page.
 * Composition: Navbar → Hero → FeatureStrip → StandardsSection → CtaBand →
 * Footer. The order is the nav's order, top to bottom, so the scroll-spy can
 * derive the current section from document position alone. Owns the landing
 * route's chrome: unlocks body scroll (the app shell needs overflow-hidden),
 * boots Lenis smooth scrolling, and manages the document title.
 *
 * THE ONE THING DRAWN BELOW THE HERO'S COPY LIVES INSIDE THE HERO (`HeroModel.tsx`),
 * not between it and the capabilities: the composition is still nav → hero →
 * capabilities → standards → closing band, and the model is the hero's own second
 * beat rather than a section of its own.
 *
 * THERE IS NO PRODUCT-PREVIEW SECTION BETWEEN THE HERO AND THE CAPABILITIES.
 * Six attempts lived there — a hand-built mock-up of the app, screenshots of it, the
 * engine's own drawing sheets, a clean sheet re-drawn from the engine's geometry, a
 * figures panel, and a scroll-scrubbed build-up of that geometry — and every one was
 * removed. They were parked for a while under `frontend/quarantine/`, which has since
 * been deleted too, so nothing of them is left in the tree: no section id (`#platform`
 * is gone, and the hero's "See the platform" button now lands on `#capabilities`), no
 * components, no public assets, no CSS. The capture that fed them is unchanged and
 * still reproducible — see `backend/scripts/capture_landing_generation.py`.
 */
import React, { useEffect } from 'react';
import { MotionConfig } from 'framer-motion';
import { Navbar } from './Navbar';
import { Hero } from './Hero';
import { AboutSection } from './AboutSection';
import { Backdrop } from './Backdrop';
import { FeatureStrip } from './FeatureStrip';
import { StandardsSection } from './StandardsSection';
import { CtaBand, Footer } from './CtaBand';
import { ScrollRail } from './ScrollRail';
import { initLenis } from './scroll';

const LANDING_TITLE = 'BuildWise — AI-Powered Construction Planning & Blueprint Generation Platform';

export const LandingPage: React.FC = () => {
  useEffect(() => {
    document.title = LANDING_TITLE;
    document.body.classList.add('bw-landing-open');
    document.documentElement.classList.add('bw-landing-open');
    const destroyLenis = initLenis();

    return () => {
      destroyLenis();
      document.body.classList.remove('bw-landing-open');
      document.documentElement.classList.remove('bw-landing-open');
      window.scrollTo(0, 0);
    };
  }, []);

  return (
    <MotionConfig reducedMotion="user">
      <div className="bw-landing relative min-h-screen font-sans text-bw-ink antialiased">
        <Backdrop />
        <ScrollRail />
        <Navbar />
        <main className="relative z-10">
          <Hero />
          <AboutSection />
          <FeatureStrip />
          <StandardsSection />
          <CtaBand />
        </main>
        <div className="relative z-10">
          <Footer />
        </div>
      </div>
    </MotionConfig>
  );
};
