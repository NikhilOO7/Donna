import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#eef2ff',
          100: '#e0e7ff',
          200: '#c7d2fe',
          300: '#a5b4fc',
          400: '#818cf8',
          500: '#6366f1',
          600: '#4f46e5',
          700: '#4338ca',
          800: '#3730a3',
          900: '#312e81',
          950: '#1e1b4b',
        },
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'slide-in': 'slide-in-right 0.3s ease-out',
        'fade-up': 'fade-up 0.4s ease-out',
        'glow': 'glow-pulse 2s ease-in-out infinite',
        // The live-meeting orb. Deliberately slow: a fast pulse reads as
        // urgency, and this sits beside a real conversation for an hour.
        'orb-breathe': 'orb-breathe 6s ease-in-out infinite',
        'orb-halo': 'orb-halo 10s ease-in-out infinite',
        'toast-in': 'toast-in 0.35s cubic-bezier(0.16, 1, 0.3, 1)',
      },
      keyframes: {
        'orb-breathe': {
          '0%, 100%': { transform: 'scale(1)' },
          '50%': { transform: 'scale(1.035)' },
        },
        'orb-halo': {
          '0%, 100%': { opacity: '0.35', transform: 'scale(0.96)' },
          '50%': { opacity: '0.7', transform: 'scale(1.06)' },
        },
        'toast-in': {
          '0%': { opacity: '0', transform: 'translateY(10px) scale(0.98)' },
          '100%': { opacity: '1', transform: 'translateY(0) scale(1)' },
        },
      },
      boxShadow: {
        'glow-primary': '0 0 15px -3px rgba(99, 102, 241, 0.3)',
        'glow-green': '0 0 15px -3px rgba(34, 197, 94, 0.3)',
        'glow-red': '0 0 15px -3px rgba(239, 68, 68, 0.3)',
        'card': '0 1px 3px 0 rgba(0, 0, 0, 0.04), 0 1px 2px -1px rgba(0, 0, 0, 0.04)',
        'card-hover': '0 4px 12px -2px rgba(0, 0, 0, 0.08), 0 2px 6px -2px rgba(0, 0, 0, 0.04)',
        'elevated': '0 8px 24px -4px rgba(0, 0, 0, 0.1), 0 4px 8px -4px rgba(0, 0, 0, 0.06)',
      },
      backdropBlur: {
        xs: '2px',
      },
    },
  },
  plugins: [],
};

export default config;
