'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import {
  ArrowRight, Sparkles, ShieldCheck, BookOpen, MessageSquare,
  FileText, Search, Pin, GitBranch, Mail, Lock, Server, Eye,
  ChevronDown, CheckCircle2, Radio, Lightbulb, Mic,
} from 'lucide-react';

/* ---------------------------------- Nav ---------------------------------- */

function Navbar() {
  return (
    <nav className="sticky top-0 z-50 bg-white/80 backdrop-blur-md border-b border-gray-100">
      <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-600 to-violet-600 flex items-center justify-center shadow-sm">
            <Sparkles className="w-4 h-4 text-white" />
          </div>
          <span className="font-bold text-gray-900 text-lg tracking-tight">Donna</span>
        </Link>
        <div className="hidden md:flex items-center gap-8 text-sm text-gray-600">
          <a href="#product" className="hover:text-gray-900 transition-colors">Product</a>
          <a href="#how-it-works" className="hover:text-gray-900 transition-colors">How it works</a>
          <a href="#security" className="hover:text-gray-900 transition-colors">Security</a>
          <a href="#faq" className="hover:text-gray-900 transition-colors">FAQ</a>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/login"
            className="px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors"
          >
            Sign in
          </Link>
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-1.5 px-4 py-2 bg-gray-900 hover:bg-gray-800 text-white text-sm font-medium rounded-lg transition-colors"
          >
            Open Dashboard
            <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      </div>
    </nav>
  );
}

/* ------------------------- Product mock (hero shot) ------------------------ */

function ProductMock() {
  return (
    <div className="relative">
      {/* Glow */}
      <div className="absolute -inset-6 bg-gradient-to-r from-indigo-200/60 via-violet-200/60 to-sky-200/60 rounded-3xl blur-2xl opacity-70" />

      <div className="relative bg-white rounded-2xl border border-gray-200 shadow-elevated overflow-hidden">
        {/* Window chrome */}
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100 bg-gray-50/60">
          <span className="w-2.5 h-2.5 rounded-full bg-red-300" />
          <span className="w-2.5 h-2.5 rounded-full bg-amber-300" />
          <span className="w-2.5 h-2.5 rounded-full bg-emerald-300" />
          <div className="ml-3 flex items-center gap-2 text-[11px] text-gray-500">
            <Radio className="w-3 h-3 text-indigo-500" />
            Donna Meeting Assistant · Live Mode
          </div>
          <span className="ml-auto flex items-center gap-1 text-[10px] font-medium text-emerald-600">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
            Donna Active
          </span>
        </div>

        <div className="p-4 space-y-3 bg-gradient-to-b from-white to-gray-50/50">
          {/* Transcript line */}
          <div className="px-3 py-2 rounded-lg bg-gray-50 border border-gray-100 text-[12px]">
            <span className="font-semibold text-indigo-600">Sarah:</span>{' '}
            <span className="text-gray-600">The market grew about 15% last year, so we should move the launch up.</span>
          </div>

          {/* Fact-check insight card */}
          <div className="bg-gradient-to-br from-emerald-50 to-green-50 border border-emerald-200/60 rounded-xl p-3.5">
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-lg bg-gradient-to-br from-emerald-400 to-green-500 flex items-center justify-center">
                  <ShieldCheck className="w-3.5 h-3.5 text-white" />
                </div>
                <span className="text-[9px] font-bold uppercase tracking-wider text-gray-400">Fact Check</span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="w-9 h-1 rounded-full bg-gray-200 overflow-hidden">
                  <div className="h-full w-[87%] bg-emerald-400 rounded-full" />
                </div>
                <span className="text-[10px] font-semibold text-gray-500">87%</span>
              </div>
            </div>
            <blockquote className="border-l-2 border-emerald-300 pl-2 mb-1.5">
              <p className="text-[11px] text-gray-500 italic">&ldquo;The market grew about 15% last year&rdquo;</p>
            </blockquote>
            <p className="text-[12px] font-semibold text-gray-900">I&apos;d double-check that — Partially true</p>
            <p className="text-[11px] text-gray-600 mt-0.5">
              Industry reports put growth at 12.3%, not 15%. The premium segment did grow 15.8%.
            </p>
            <div className="flex items-center gap-2 mt-2">
              <span className="px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 text-[9px] font-semibold">Partially true</span>
              <span className="text-[10px] text-blue-600 underline">reuters.com</span>
            </div>
          </div>

          {/* Assistant bubble */}
          <div className="flex items-start gap-2">
            <div className="w-6 h-6 rounded-lg bg-gradient-to-br from-violet-500 to-indigo-500 flex items-center justify-center flex-shrink-0">
              <Sparkles className="w-3 h-3 text-white" />
            </div>
            <div className="bg-violet-50 border border-violet-100 rounded-xl rounded-tl-sm px-3 py-2 text-[11px] text-gray-600">
              Logged. Want me to pull what we decided about launch timing in the March meeting?
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------------------------------- Hero ---------------------------------- */

function Hero() {
  return (
    <section className="relative overflow-hidden">
      <div className="absolute inset-0 bg-gradient-to-b from-indigo-50/70 via-white to-white" />
      <div className="relative max-w-6xl mx-auto px-6 pt-20 pb-24 lg:pt-28 lg:pb-28 grid lg:grid-cols-2 gap-14 items-center">
        <div>
          <div className="inline-flex items-center gap-2 px-3 py-1 bg-white border border-indigo-100 rounded-full text-xs font-medium text-indigo-600 shadow-sm mb-6">
            <Sparkles className="w-3.5 h-3.5" />
            Your AI meeting partner
          </div>
          <h1 className="text-4xl lg:text-6xl font-extrabold tracking-tight text-gray-900 leading-[1.05] mb-6">
            Meetings that end in
            <span className="bg-gradient-to-r from-indigo-600 via-violet-600 to-purple-600 bg-clip-text text-transparent"> decisions</span>,
            not follow-ups.
          </h1>
          <p className="text-lg text-gray-600 leading-relaxed mb-8 max-w-xl">
            Donna researches before you walk in, fact-checks claims as they&apos;re
            spoken, captures every decision with the exact words that triggered
            it — and has the summary ready before anyone asks.
          </p>
          <div className="flex items-center gap-4 flex-wrap">
            <Link
              href="/dashboard"
              className="inline-flex items-center gap-2 px-6 py-3.5 bg-indigo-600 hover:bg-indigo-700 text-white font-semibold rounded-xl shadow-md hover:shadow-lg transition-all duration-200 active:scale-[0.98]"
            >
              Start your first meeting
              <ArrowRight className="w-4 h-4" />
            </Link>
            <a
              href="#how-it-works"
              className="inline-flex items-center gap-2 px-6 py-3.5 bg-white text-gray-700 font-medium rounded-xl border border-gray-200 hover:border-gray-300 hover:bg-gray-50 transition-all duration-200"
            >
              See how it works
            </a>
          </div>
          <p className="mt-6 text-sm text-gray-400 italic">&ldquo;She already knew.&rdquo;</p>
        </div>
        <ProductMock />
      </div>
    </section>
  );
}

/* ------------------------------ Value pillars ------------------------------ */

const PILLARS = [
  {
    icon: BookOpen,
    title: 'Walks in prepared',
    body: 'Give Donna the meeting topic and she runs the research: multiple web sources, credibility-tiered, synthesized into a brief your whole team can skim in two minutes.',
  },
  {
    icon: MessageSquare,
    title: 'Speaks up at the right moment',
    body: "During the conversation she listens for what matters — a claim worth checking, a decision forming, a document you forgot you had — and surfaces it as a card, not an interruption.",
  },
  {
    icon: Eye,
    title: 'Every insight shows its work',
    body: 'Nothing arrives as a black box. Each card names its source — the document and page, the article and publisher, or the exact words a colleague said.',
  },
];

function ValuePillars() {
  return (
    <section id="product" className="py-20 bg-white">
      <div className="max-w-6xl mx-auto px-6">
        <div className="text-center mb-14">
          <h2 className="text-3xl lg:text-4xl font-bold text-gray-900 mb-3">
            Built for the meetings where alignment matters most
          </h2>
          <p className="text-gray-500 max-w-2xl mx-auto">
            Cross-functional decisions fail on missing context and fuzzy memory.
            Donna fixes both.
          </p>
        </div>
        <div className="grid md:grid-cols-3 gap-6">
          {PILLARS.map((p) => (
            <div
              key={p.title}
              className="p-7 rounded-2xl border border-gray-100 bg-gradient-to-b from-gray-50/80 to-white hover:shadow-card-hover hover:-translate-y-0.5 transition-all duration-300"
            >
              <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center mb-5 shadow-sm">
                <p.icon className="w-5 h-5 text-white" />
              </div>
              <h3 className="font-semibold text-gray-900 text-lg mb-2">{p.title}</h3>
              <p className="text-gray-600 text-[15px] leading-relaxed">{p.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ------------------------------- Product tour ------------------------------ */

const PHASES = [
  {
    label: 'Before',
    title: 'The homework is done before you sit down',
    body: 'Create the meeting, attach your documents, and Donna researches the topic across the open web — validating sources, scoring credibility, and writing the executive brief. Your files become a searchable knowledge base with tables, charts, and figures included.',
    points: ['Multi-source web research with credibility tiers', 'Documents parsed page-by-page — tables and images too', 'One brief the whole room reads in two minutes'],
    icon: Search,
    visual: (
      <div className="bg-white rounded-xl border border-gray-200 shadow-card p-4 space-y-2.5">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-bold uppercase tracking-wider text-gray-400">Research Brief</span>
          <span className="px-2 py-0.5 bg-emerald-100 text-emerald-700 rounded text-[10px] font-semibold">Ready</span>
        </div>
        <p className="text-[13px] font-semibold text-gray-900">Q2 Vendor Selection — Competitive Landscape</p>
        {['Tier 1 · Compliance posture comparison', 'Tier 1 · Pricing benchmarks 2026', 'Tier 2 · Support SLA analysis'].map((s) => (
          <div key={s} className="flex items-center gap-2 px-3 py-2 bg-gray-50 rounded-lg text-[12px] text-gray-600">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 flex-shrink-0" />
            {s}
          </div>
        ))}
      </div>
    ),
  },
  {
    label: 'During',
    title: 'Live intelligence, zero interruptions',
    body: "As the conversation flows, Donna cross-checks claims against the web, pulls the right page from your documents, spots decisions forming, and connects what's being said to what your organization already knows — each as a quiet card you can pin, dismiss, or act on.",
    points: ['Fact-checks with the source linked', 'Decision prompts with the verbatim quote attached', 'Ask Donna anything mid-meeting — answers cite your documents'],
    icon: Lightbulb,
    visual: (
      <div className="space-y-2.5">
        <div className="bg-gradient-to-br from-violet-50 to-purple-50 border border-violet-200/60 rounded-xl p-3.5">
          <div className="flex items-center gap-2 mb-1">
            <MessageSquare className="w-3.5 h-3.5 text-violet-500" />
            <span className="text-[10px] font-bold uppercase tracking-wider text-gray-400">Decision</span>
          </div>
          <p className="text-[13px] font-semibold text-gray-900">Sounds like a decision — want me to log it?</p>
          <p className="text-[12px] text-gray-600 mt-0.5">&ldquo;Let&apos;s go with Beacon Cloud for Q2.&rdquo;</p>
          <div className="mt-2 flex gap-2">
            <span className="px-2.5 py-1 bg-violet-600 text-white rounded-lg text-[11px] font-medium">Log Decision</span>
            <span className="px-2.5 py-1 bg-white text-violet-600 border border-violet-200 rounded-lg text-[11px] font-medium">Ask Donna</span>
          </div>
        </div>
        <div className="bg-gradient-to-br from-blue-50 to-sky-50 border border-blue-200/60 rounded-xl p-3.5">
          <div className="flex items-center gap-2 mb-1">
            <BookOpen className="w-3.5 h-3.5 text-blue-500" />
            <span className="text-[10px] font-bold uppercase tracking-wider text-gray-400">Context</span>
          </div>
          <p className="text-[13px] font-semibold text-gray-900">I pulled the numbers from your docs</p>
          <p className="text-[11px] text-gray-500 mt-1 flex items-center gap-1">
            <FileText className="w-3 h-3" /> Source: Vendor_Comparison.pdf · p. 12
          </p>
        </div>
      </div>
    ),
  },
  {
    label: 'After',
    title: 'The summary writes itself — with receipts',
    body: 'The moment the meeting ends, Donna weaves the transcript, decisions, action items, and every insight she surfaced into a structured summary. Each decision keeps the exact conversation that triggered it, and the whole thing lands in attendee inboxes.',
    points: ['Decisions with owners, deadlines, and verbatim quotes', 'Action items extracted automatically', 'Emailed to every attendee — nothing to write up'],
    icon: Mail,
    visual: (
      <div className="bg-white rounded-xl border border-gray-200 shadow-card p-4 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-bold uppercase tracking-wider text-gray-400">Meeting Summary</span>
          <span className="flex items-center gap-1 text-[10px] text-emerald-600 font-medium">
            <Mail className="w-3 h-3" /> Sent to 5 attendees
          </span>
        </div>
        <div className="p-3 bg-emerald-50 border border-emerald-100 rounded-lg">
          <p className="text-[13px] font-medium text-gray-900">Go with Beacon Cloud — Q2 rollout</p>
          <div className="mt-1.5 pl-2 border-l-2 border-emerald-300">
            <p className="text-[11px] text-gray-500 italic">Alice: &ldquo;Let&apos;s go with Vendor B — Beacon Cloud.&rdquo;</p>
          </div>
        </div>
        <div className="p-3 bg-sky-50 border border-sky-100 rounded-lg text-[12px] text-gray-700">
          Draft the contract — <span className="font-medium">Charlie</span> · end of Q2
        </div>
      </div>
    ),
  },
];

function ProductTour() {
  return (
    <section id="how-it-works" className="py-20 bg-gradient-to-b from-gray-50/80 to-white">
      <div className="max-w-6xl mx-auto px-6">
        <div className="text-center mb-16">
          <h2 className="text-3xl lg:text-4xl font-bold text-gray-900 mb-3">
            One partner across the whole meeting
          </h2>
          <p className="text-gray-500 max-w-2xl mx-auto">
            Before, during, and after — the context flows through so nothing gets lost between phases.
          </p>
        </div>
        <div className="space-y-20">
          {PHASES.map((phase, i) => (
            <div
              key={phase.label}
              className={`grid lg:grid-cols-2 gap-10 lg:gap-16 items-center ${i % 2 === 1 ? 'lg:[direction:rtl]' : ''}`}
            >
              <div className="lg:[direction:ltr]">
                <div className="inline-flex items-center gap-2 px-3 py-1 bg-indigo-50 border border-indigo-100 rounded-full text-xs font-semibold text-indigo-600 mb-4">
                  <phase.icon className="w-3.5 h-3.5" />
                  {phase.label} the meeting
                </div>
                <h3 className="text-2xl lg:text-3xl font-bold text-gray-900 mb-4">{phase.title}</h3>
                <p className="text-gray-600 leading-relaxed mb-5">{phase.body}</p>
                <ul className="space-y-2.5">
                  {phase.points.map((pt) => (
                    <li key={pt} className="flex items-start gap-2.5 text-[15px] text-gray-700">
                      <CheckCircle2 className="w-[18px] h-[18px] text-indigo-500 flex-shrink-0 mt-0.5" />
                      {pt}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="lg:[direction:ltr]">{phase.visual}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ------------------------------- Feature grid ------------------------------ */

const FEATURES = [
  { icon: ShieldCheck, title: 'Live fact-checking', body: 'Numeric and attributed claims are verified against the web in seconds, with the contradicting source linked.' },
  { icon: MessageSquare, title: 'Decisions with receipts', body: 'Every logged decision keeps the verbatim conversation that triggered it — who said what, word for word.' },
  { icon: GitBranch, title: 'Organizational memory', body: 'People, companies, and decisions connect into a knowledge graph that resurfaces when they matter again.' },
  { icon: Pin, title: 'Pin, arrange, export', body: 'Pin the insights worth keeping, cluster them on an infinite canvas, and export the digest in one click.' },
  { icon: Mic, title: 'Voice-native', body: 'Connect your mic and Donna transcribes live, attributing every line to its speaker automatically.' },
  { icon: FileText, title: 'Documents that answer back', body: 'PDFs, decks, and reports — including their tables and charts — become sources Donna cites by page.' },
];

function FeatureGrid() {
  return (
    <section className="py-20 bg-white">
      <div className="max-w-6xl mx-auto px-6">
        <div className="text-center mb-14">
          <h2 className="text-3xl lg:text-4xl font-bold text-gray-900 mb-3">
            Everything a great chief of staff would do
          </h2>
          <p className="text-gray-500 max-w-2xl mx-auto">If she had perfect recall and read every document twice.</p>
        </div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {FEATURES.map((f) => (
            <div key={f.title} className="p-6 rounded-2xl border border-gray-100 hover:border-indigo-100 hover:bg-indigo-50/30 transition-all duration-300">
              <f.icon className="w-6 h-6 text-indigo-500 mb-4" />
              <h3 className="font-semibold text-gray-900 mb-1.5">{f.title}</h3>
              <p className="text-gray-600 text-sm leading-relaxed">{f.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* --------------------------------- Security -------------------------------- */

const TRUST = [
  { icon: Lock, title: 'Your workspace is yours alone', body: 'Documents, meetings, and insights are isolated per workspace — retrieval, search, and the knowledge graph never cross tenant boundaries.' },
  { icon: Eye, title: 'Traceable by design', body: 'Every answer names its sources. If Donna can’t trace a claim, she doesn’t make it.' },
  { icon: Server, title: 'Deploy it your way', body: 'Run Donna in your own infrastructure — the entire stack ships as containers you control, so sensitive meetings never leave your network.' },
];

function Security() {
  return (
    <section id="security" className="py-20 bg-gray-900 text-white">
      <div className="max-w-6xl mx-auto px-6">
        <div className="text-center mb-14">
          <h2 className="text-3xl lg:text-4xl font-bold mb-3">Serious about what you say in the room</h2>
          <p className="text-gray-400 max-w-2xl mx-auto">Meetings are where your most sensitive thinking happens. Donna treats them that way.</p>
        </div>
        <div className="grid md:grid-cols-3 gap-6">
          {TRUST.map((t) => (
            <div key={t.title} className="p-7 rounded-2xl bg-white/5 border border-white/10">
              <t.icon className="w-6 h-6 text-indigo-300 mb-4" />
              <h3 className="font-semibold text-white mb-2">{t.title}</h3>
              <p className="text-gray-400 text-sm leading-relaxed">{t.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ----------------------------------- FAQ ----------------------------------- */

const FAQS = [
  {
    q: 'Does Donna interrupt the meeting?',
    a: 'No. Insights arrive as quiet cards in a side feed — you glance, pin, dismiss, or act. Donna never takes the floor unless you ask her a question.',
  },
  {
    q: 'Where do her answers come from?',
    a: 'Three places, always attributed: your uploaded documents (cited by file and page), pre-meeting web research (credibility-tiered sources), and the meeting itself (verbatim quotes). Nothing is asserted without a source.',
  },
  {
    q: 'What happens to a decision after it’s logged?',
    a: 'It’s stored with its owner, deadline, status, and the exact conversation that triggered it. It appears in the post-meeting summary, the follow-up email, and resurfaces in future meetings when the topic comes back.',
  },
  {
    q: 'Do I need to type everything?',
    a: 'No — connect your microphone and Donna transcribes live with speaker attribution. Typing is a fallback for rooms where recording isn’t appropriate.',
  },
  {
    q: 'Can we run it on our own infrastructure?',
    a: 'Yes. The full stack ships as containers — API, workers, databases, and frontend — so you can deploy inside your own network and keep every transcript in-house.',
  },
];

function FAQ() {
  const [open, setOpen] = useState<number | null>(0);
  return (
    <section id="faq" className="py-20 bg-white">
      <div className="max-w-3xl mx-auto px-6">
        <h2 className="text-3xl lg:text-4xl font-bold text-gray-900 text-center mb-12">
          Questions, answered
        </h2>
        <div className="space-y-3">
          {FAQS.map((f, i) => (
            <div key={f.q} className="border border-gray-200 rounded-xl overflow-hidden">
              <button
                onClick={() => setOpen(open === i ? null : i)}
                className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-gray-50 transition-colors"
              >
                <span className="font-medium text-gray-900 text-[15px]">{f.q}</span>
                <ChevronDown
                  className={`w-4 h-4 text-gray-400 flex-shrink-0 transition-transform duration-200 ${open === i ? 'rotate-180' : ''}`}
                />
              </button>
              {open === i && (
                <div className="px-5 pb-4 text-gray-600 text-sm leading-relaxed animate-fade-up">
                  {f.a}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ------------------------------- CTA + Footer ------------------------------ */

function FinalCTA() {
  return (
    <section className="py-24 bg-gradient-to-br from-[#1e1b4b] via-[#312e81] to-[#4338ca] text-white text-center">
      <div className="max-w-2xl mx-auto px-6">
        <h2 className="text-3xl lg:text-5xl font-bold mb-4">Let Donna handle it.</h2>
        <p className="text-indigo-200 text-lg mb-9 leading-relaxed">
          She researches before the meeting, surfaces the right intel while you
          talk, and has the summary ready before you ask. You just show up.
        </p>
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-2 px-8 py-4 bg-white text-[#312e81] font-semibold rounded-xl shadow-lg hover:shadow-xl transition-all duration-200 active:scale-[0.98] text-lg"
        >
          Meet Donna
          <ArrowRight className="w-5 h-5" />
        </Link>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="bg-gray-950 text-gray-400 py-14">
      <div className="max-w-6xl mx-auto px-6">
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-10 mb-10">
          <div className="lg:col-span-2">
            <div className="flex items-center gap-2.5 mb-3">
              <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-indigo-600 to-violet-600 flex items-center justify-center">
                <Sparkles className="w-3.5 h-3.5 text-white" />
              </div>
              <span className="font-bold text-white">Donna</span>
            </div>
            <p className="text-sm text-gray-500 max-w-sm leading-relaxed">
              The AI meeting partner for teams whose decisions matter. Prepared
              before you walk in, sharp while you talk, thorough after you leave.
            </p>
          </div>
          <div>
            <h4 className="text-white text-sm font-semibold mb-3">Product</h4>
            <ul className="space-y-2 text-sm">
              <li><Link href="/dashboard" className="hover:text-white transition-colors">Dashboard</Link></li>
              <li><a href="#how-it-works" className="hover:text-white transition-colors">How it works</a></li>
              <li><a href="#security" className="hover:text-white transition-colors">Security</a></li>
            </ul>
          </div>
          <div>
            <h4 className="text-white text-sm font-semibold mb-3">Support</h4>
            <ul className="space-y-2 text-sm">
              <li><a href="#faq" className="hover:text-white transition-colors">FAQ</a></li>
              <li><a href="#product" className="hover:text-white transition-colors">Features</a></li>
            </ul>
          </div>
        </div>
        <div className="pt-6 border-t border-gray-800 flex items-center justify-between flex-wrap gap-3 text-xs text-gray-600">
          <span>© {new Date().getFullYear()} Donna. All rights reserved.</span>
          <span className="italic">&ldquo;She already knew.&rdquo;</span>
        </div>
      </div>
    </footer>
  );
}

/* ---------------------------------- Page ----------------------------------- */

export default function LandingPage() {
  return (
    <main className="min-h-screen bg-white">
      <Navbar />
      <Hero />
      <ValuePillars />
      <ProductTour />
      <FeatureGrid />
      <Security />
      <FAQ />
      <FinalCTA />
      <Footer />
    </main>
  );
}
