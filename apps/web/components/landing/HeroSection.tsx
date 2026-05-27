'use client';

import React from 'react';
import Link from 'next/link';
import { Zap, ArrowRight, Bot, Mic, FileText } from 'lucide-react';

export default function HeroSection() {
  return (
    <section className="relative overflow-hidden bg-gradient-to-br from-[#1e1b4b] via-[#312e81] to-[#4338ca] text-white">
      {/* Animated bg dots */}
      <div className="absolute inset-0 opacity-10">
        <div className="absolute top-20 left-[10%] w-72 h-72 bg-purple-400 rounded-full blur-[120px] animate-float" />
        <div className="absolute bottom-10 right-[15%] w-96 h-96 bg-indigo-400 rounded-full blur-[140px] animate-float" style={{ animationDelay: '2s' }} />
        <div className="absolute top-1/2 left-1/2 w-64 h-64 bg-blue-400 rounded-full blur-[100px] animate-float" style={{ animationDelay: '4s' }} />
      </div>

      <div className="relative max-w-6xl mx-auto px-6 py-24 lg:py-32">
        <div className="text-center">
          {/* Badge */}
          <div className="inline-flex items-center gap-2 px-4 py-1.5 bg-white/10 backdrop-blur-sm border border-white/20 rounded-full text-sm mb-8 animate-fade-up">
            <Zap className="w-4 h-4 text-yellow-300" />
            <span>Always a step ahead &middot; 15 AI Agents &middot; 3-Phase Pipeline</span>
          </div>

          {/* Headline */}
          <h1 className="text-5xl lg:text-7xl font-extrabold tracking-tight mb-6 animate-fade-up" style={{ animationDelay: '0.1s' }}>
            Meet
            <span className="block bg-gradient-to-r from-indigo-300 via-purple-300 to-pink-300 bg-clip-text text-transparent animate-gradient">
              Donna
            </span>
          </h1>

          <p className="text-lg lg:text-xl text-indigo-200 max-w-2xl mx-auto mb-10 leading-relaxed animate-fade-up" style={{ animationDelay: '0.2s' }}>
            Your AI meeting partner who's always a step ahead. Donna does the homework
            before you walk in, surfaces exactly what you need while you talk, and has
            the summary ready before you ask. She already knew.
          </p>

          {/* CTA */}
          <div className="flex items-center justify-center gap-4 animate-fade-up" style={{ animationDelay: '0.3s' }}>
            <Link
              href="/dashboard"
              className="inline-flex items-center gap-2 px-8 py-4 bg-white text-[#312e81] font-semibold rounded-xl shadow-lg hover:shadow-xl transition-all duration-200 active:scale-[0.98] text-lg"
            >
              Meet Donna
              <ArrowRight className="w-5 h-5" />
            </Link>
          </div>

          {/* 3 mini cards */}
          <div className="grid grid-cols-3 gap-4 max-w-lg mx-auto mt-16 animate-fade-up" style={{ animationDelay: '0.5s' }}>
            {[
              { icon: Bot, label: 'Before', sub: '4 Research Agents' },
              { icon: Mic, label: 'During', sub: '6 Live Agents' },
              { icon: FileText, label: 'After', sub: '2 Summary Agents' },
            ].map((item) => (
              <div key={item.label} className="bg-white/10 backdrop-blur-sm border border-white/10 rounded-xl p-4 text-center hover:bg-white/15 transition-colors">
                <item.icon className="w-6 h-6 mx-auto mb-2 text-indigo-300" />
                <p className="font-semibold text-sm">{item.label}</p>
                <p className="text-xs text-indigo-300 mt-0.5">{item.sub}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Bottom curve */}
      <div className="absolute bottom-0 left-0 right-0">
        <svg viewBox="0 0 1440 60" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M0 60V20C360 0 720 0 1080 20C1260 30 1380 40 1440 48V60H0Z" fill="#f9fafb" />
        </svg>
      </div>
    </section>
  );
}
