import React from 'react';
import Link from 'next/link';
import { ArrowRight } from 'lucide-react';
import HeroSection from '@/components/landing/HeroSection';
import PhaseFlow from '@/components/landing/PhaseFlow';
import AgentFlowchart from '@/components/landing/AgentFlowchart';
import TechStack from '@/components/landing/TechStack';
import Features from '@/components/landing/Features';

export default function LandingPage() {
  return (
    <main className="min-h-screen">
      {/* Hero */}
      <HeroSection />

      {/* How it works — 3 phases */}
      <PhaseFlow />

      {/* Agent architecture flowcharts */}
      <AgentFlowchart />

      {/* Tech stack */}
      <TechStack />

      {/* Production features */}
      <Features />

      {/* Footer CTA */}
      <section className="py-20 bg-gradient-to-br from-[#1e1b4b] via-[#312e81] to-[#4338ca] text-white text-center">
        <div className="max-w-2xl mx-auto px-6">
          <h2 className="text-3xl lg:text-4xl font-bold mb-4">
            Ready to see it in action?
          </h2>
          <p className="text-indigo-200 text-lg mb-8">
            Create a meeting, run the research pipeline, start a live session, and generate an AI summary — all in one workflow.
          </p>
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-2 px-8 py-4 bg-white text-[#312e81] font-semibold rounded-xl shadow-lg hover:shadow-xl transition-all duration-200 active:scale-[0.98] text-lg"
          >
            Open Dashboard
            <ArrowRight className="w-5 h-5" />
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-gray-900 text-gray-400 py-8 text-center text-sm">
        <p>Meeting Assistant v2.0 &middot; 15 AI Agents &middot; 3-Phase Pipeline</p>
        <p className="mt-1 text-gray-600">Built with FastAPI, Next.js, OpenAI, LiveKit, Qdrant, PostgreSQL</p>
      </footer>
    </main>
  );
}
