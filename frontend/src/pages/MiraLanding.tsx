import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  Bot,
  ClipboardList,
  FileStack,
  LayoutGrid,
  Search,
  ScrollText,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Wind,
} from 'lucide-react';
import { BoundStateLogo } from '@/components/BoundStateLogo';

type CounterProps = {
  end: number;
  duration?: number;
  delay?: number;
};

function Counter({ end, duration = 1800, delay = 0 }: CounterProps) {
  const [count, setCount] = useState(0);

  useEffect(() => {
    let frame = 0;
    let started = false;
    let timeoutId: number | undefined;

    const tick = () => {
      frame += 16;
      const next = Math.min(end, Math.round((frame / duration) * end));
      setCount(next);
      if (next < end) {
        window.setTimeout(tick, 16);
      }
    };

    timeoutId = window.setTimeout(() => {
      started = true;
      tick();
    }, delay);

    return () => {
      if (!started && timeoutId) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [delay, duration, end]);

  return <span>{count}</span>;
}

const PRIMARY_PATHS = [
  {
    id: 'assess',
    eyebrow: 'Assess',
    title: 'Interrogate material compatibility before it becomes a failure mode.',
    description:
      'Run hydrogen, galvanic, fracture, and knowledge-backed checks from one decision surface instead of stitching together disconnected tools.',
    features: ['Hydrogen compatibility twins', 'Galvanic pairing review', 'Fracture control support'],
    href: '/query',
    accent: '#0b6fb8',
    icon: Wind,
  },
  {
    id: 'govern',
    eyebrow: 'Govern',
    title: 'Turn engineering decisions into governed program artifacts.',
    description:
      'Move directly from material questions into M&P plans, MUA drafting, and MIUL extraction without losing context or authority basis.',
    features: ['M&P plan workflow', 'MUA writer', 'MIUL production builder'],
    href: '/mp-plan',
    accent: '#0d8c78',
    icon: ClipboardList,
  },
  {
    id: 'investigate',
    eyebrow: 'Investigate',
    title: 'Model oxygen compatibility risk as systems, not isolated parts.',
    description:
      'Use the OCA workbench and system builder to capture configuration, pathing, evidence, and disposition in a single traceable workflow.',
    features: ['OCA workbench', 'System topology builder', 'Path-specific evidence review'],
    href: '/oca/workbench',
    accent: '#b86a16',
    icon: Shield,
  },
];

const QUICK_LINKS = [
  { title: 'MIRA Chat', href: '/chat', icon: Bot, blurb: 'Module-aware chat across the workspace.' },
  { title: 'Oracle Standards', href: '/oracle', icon: ScrollText, blurb: 'Clause-grounded standards chat with Oracle packs.' },
  { title: 'Gas Compatibility', href: '/gas-compatibility', icon: Wind, blurb: 'Hydrogen and oxygen screening.' },
  { title: 'Galvanic', href: '/galvanic-compatibility', icon: ShieldAlert, blurb: 'Pairing risk and mitigation.' },
  { title: 'Fracture Control', href: '/fracture-control', icon: ShieldCheck, blurb: 'FCR-backed decisions.' },
  { title: 'OCA System Builder', href: '/oca/system-builder', icon: LayoutGrid, blurb: 'Topology-first oxygen analysis.' },
  { title: 'MUA Writer', href: '/mua-v10', icon: Sparkles, blurb: 'Draft approval artifacts faster.' },
  { title: 'MIUL Builder', href: '/miul', icon: FileStack, blurb: 'Production extraction workflow.' },
  { title: 'Knowledge Twins', href: '/knowledge-twins', icon: Search, blurb: 'Browse evidence-backed material guidance.' },
];

const TRUST_LINES = [
  'Authority-backed guidance packs',
  'Workflow-aware document generation',
  'Shared chat and decision context',
];

export default function MiraLanding() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setVisible(true), 80);
    return () => window.clearTimeout(timer);
  }, []);

  return (
    <div className="mira-landing min-h-screen overflow-hidden bg-[#f5f4ef] text-slate-950">
      <style>{`
        .mira-landing {
          --mira-ink: #101827;
          --mira-muted: #5a6472;
          --mira-line: #d7d5cd;
          --mira-blue: #0b6fb8;
          --mira-teal: #0d8c78;
          --mira-amber: #b86a16;
          background-image:
            radial-gradient(circle at top left, rgba(11, 111, 184, 0.10), transparent 28rem),
            radial-gradient(circle at 85% 15%, rgba(13, 140, 120, 0.10), transparent 22rem),
            linear-gradient(180deg, #fbfaf6 0%, #f5f4ef 48%, #efede5 100%);
          font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
        }

        .mira-fade-up {
          opacity: 0;
          transform: translateY(24px);
          transition: opacity 0.8s ease, transform 0.8s ease;
        }

        .mira-fade-up.visible {
          opacity: 1;
          transform: translateY(0);
        }

        .mira-hero-title {
          font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
          letter-spacing: -0.03em;
        }

        .mira-path-card {
          position: relative;
          overflow: hidden;
          border: 1px solid rgba(16, 24, 39, 0.08);
          background: rgba(255, 255, 255, 0.82);
          backdrop-filter: blur(16px);
          transition: transform 0.35s ease, box-shadow 0.35s ease, border-color 0.35s ease;
        }

        .mira-path-card::before {
          content: "";
          position: absolute;
          inset: 0 auto auto 0;
          width: 100%;
          height: 3px;
          transform: scaleX(0);
          transform-origin: left;
          transition: transform 0.35s ease;
        }

        .mira-path-card:hover {
          transform: translateY(-4px);
          box-shadow: 0 20px 50px rgba(15, 23, 42, 0.10);
          border-color: transparent;
        }

        .mira-path-card:hover::before {
          transform: scaleX(1);
        }

        .mira-chip {
          border: 1px solid rgba(16, 24, 39, 0.08);
          background: rgba(255, 255, 255, 0.72);
          transition: border-color 0.25s ease, transform 0.25s ease, background 0.25s ease;
        }

        .mira-chip:hover {
          transform: translateY(-2px);
          border-color: rgba(11, 111, 184, 0.28);
          background: rgba(255, 255, 255, 0.96);
        }

        @media (max-width: 768px) {
          .mira-hero-title {
            font-size: 3rem !important;
          }
        }
      `}</style>

      <nav className={`mx-auto flex w-full max-w-7xl items-center justify-between px-6 py-6 md:px-10 ${visible ? 'mira-fade-up visible' : 'mira-fade-up'}`}>
        <div className="flex items-center gap-3">
          <BoundStateLogo variant="full" theme="light" size="md" />
          <div className="border-l border-slate-300 pl-3 text-[11px] uppercase tracking-[0.22em] text-slate-500">
            MIRA Workspace
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Link
            to="/chat"
            className="hidden rounded-full border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-500 hover:text-slate-950 md:inline-flex"
          >
            Open Chat
          </Link>
          <Link
            to="/query"
            className="inline-flex items-center gap-2 rounded-full bg-slate-950 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800"
          >
            Open Workspace
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </nav>

      <section className="mx-auto max-w-7xl px-6 pb-10 pt-10 md:px-10 md:pb-14 md:pt-14">
        <div className="grid gap-12 lg:grid-cols-[1.15fr_0.85fr] lg:items-end">
          <div className={`${visible ? 'mira-fade-up visible' : 'mira-fade-up'}`} style={{ transitionDelay: '0.1s' }}>
            <div className="mb-5 inline-flex rounded-full border border-sky-200 bg-sky-50/70 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-sky-800">
              Materials intelligence for flight-critical decisions
            </div>
            <h1 className="mira-hero-title max-w-4xl text-5xl font-normal leading-[0.96] text-[var(--mira-ink)] md:text-7xl">
              Decide what goes into flight.
              <span className="block font-light italic text-slate-600">Before it becomes a program risk.</span>
            </h1>
            <p className="mt-6 max-w-2xl text-lg leading-8 text-[var(--mira-muted)] md:text-xl">
              MIRA combines compatibility analysis, oxygen compatibility investigation, workflow-authoring tools,
              guidance packs, and shared chat context into one engineering decision surface.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                to="/mp-plan"
                className="inline-flex items-center gap-2 rounded-full bg-[var(--mira-blue)] px-5 py-3 text-sm font-semibold text-white shadow-[0_14px_30px_rgba(11,111,184,0.18)] transition hover:translate-x-1"
              >
                Start an M&P Workflow
                <ArrowRight className="h-4 w-4" />
              </Link>
              <Link
                to="/oca/workbench"
                className="inline-flex items-center gap-2 rounded-full border border-slate-300 bg-white/70 px-5 py-3 text-sm font-semibold text-slate-900 transition hover:border-slate-500"
              >
                Open OCA
              </Link>
            </div>
          </div>

          <div
            className={`${visible ? 'mira-fade-up visible' : 'mira-fade-up'} rounded-[2rem] border border-white/60 bg-white/70 p-6 shadow-[0_24px_60px_rgba(15,23,42,0.08)] backdrop-blur-xl`}
            style={{ transitionDelay: '0.2s' }}
          >
            <div className="grid gap-4 sm:grid-cols-3">
              {[
                { end: 14, label: 'Active modules', delay: 0 },
                { end: 5, label: 'Guided workflows', delay: 120 },
                { end: 3, label: 'Decision lanes', delay: 240 },
              ].map((stat, index) => (
                <div key={stat.label} className={`py-3 ${index < 2 ? 'sm:border-r sm:border-[var(--mira-line)]' : ''}`}>
                  <div className="text-center">
                    <div className="text-4xl font-semibold tracking-tight text-slate-950">
                      <Counter end={stat.end} delay={stat.delay} />
                    </div>
                    <div className="mt-2 text-[11px] uppercase tracking-[0.18em] text-slate-500">{stat.label}</div>
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-6 rounded-2xl border border-slate-200 bg-slate-950 px-5 py-5 text-white">
              <div className="text-[11px] uppercase tracking-[0.18em] text-slate-400">Shared spine</div>
              <div className="mt-2 text-lg leading-7 text-slate-100">
                MIRA Chat, guidance packs, and workflow context stay available as you move between decision modules.
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-6 pb-6 md:px-10">
        <div className="mx-auto mb-8 h-px w-24 bg-[var(--mira-line)]" />
        <div className="mb-6 text-center text-[11px] uppercase tracking-[0.22em] text-slate-500">Choose a lane</div>
        <div className="grid gap-6 lg:grid-cols-3">
          {PRIMARY_PATHS.map((path, index) => {
            const Icon = path.icon;
            return (
              <Link
                key={path.id}
                to={path.href}
                className={`${visible ? 'mira-fade-up visible' : 'mira-fade-up'} mira-path-card rounded-[1.75rem] p-7 no-underline`}
                style={{ transitionDelay: `${0.3 + index * 0.08}s` }}
              >
                <div className="mb-5 inline-flex rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em]" style={{ color: path.accent, backgroundColor: `${path.accent}14` }}>
                  {path.eyebrow}
                </div>
                <div
                  className="mb-5 inline-flex h-11 w-11 items-center justify-center rounded-2xl text-white shadow-sm"
                  style={{ backgroundColor: path.accent }}
                >
                  <Icon className="h-5 w-5" />
                </div>
                <h2 className="mira-hero-title text-[2rem] leading-[1.02] text-slate-950">{path.title}</h2>
                <p className="mt-4 text-[15px] leading-7 text-slate-600">{path.description}</p>
                <div className="mt-6 space-y-3">
                  {path.features.map((feature) => (
                    <div key={feature} className="flex items-start gap-3 text-sm leading-6 text-slate-600">
                      <div className="mt-2 h-1.5 w-1.5 rounded-full" style={{ backgroundColor: path.accent }} />
                      <span>{feature}</span>
                    </div>
                  ))}
                </div>
                <div className="mt-8 inline-flex items-center gap-2 text-sm font-semibold" style={{ color: path.accent }}>
                  Enter this lane
                  <ArrowRight className="h-4 w-4" />
                </div>
                <div style={{ backgroundColor: path.accent }} className="absolute inset-x-0 top-0 h-[3px] origin-left scale-x-0 transition-transform duration-300 ease-out [transform-origin:left] group-hover:scale-x-100" />
              </Link>
            );
          })}
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-6 py-12 md:px-10 md:py-16">
        <div className={`${visible ? 'mira-fade-up visible' : 'mira-fade-up'} flex items-end justify-between gap-6`} style={{ transitionDelay: '0.55s' }}>
          <div>
            <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Or go straight to a workspace</div>
            <h3 className="mira-hero-title mt-3 text-4xl font-normal text-slate-950 md:text-5xl">
              Pick the exact surface you need.
            </h3>
          </div>
          <Link to="/chat" className="hidden text-sm font-semibold text-[var(--mira-blue)] md:inline-flex md:items-center md:gap-2">
            Use chat as the front door
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>

        <div className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {QUICK_LINKS.map((item, index) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.title}
                to={item.href}
                className={`${visible ? 'mira-fade-up visible' : 'mira-fade-up'} mira-chip rounded-[1.5rem] p-5 no-underline`}
                style={{ transitionDelay: `${0.62 + index * 0.05}s` }}
              >
                <div className="flex items-center justify-between">
                  <div className="inline-flex h-10 w-10 items-center justify-center rounded-2xl bg-slate-950 text-white">
                    <Icon className="h-4 w-4" />
                  </div>
                  <ArrowRight className="h-4 w-4 text-slate-400" />
                </div>
                <div className="mt-5 text-lg font-semibold text-slate-950">{item.title}</div>
                <p className="mt-2 text-sm leading-6 text-slate-600">{item.blurb}</p>
              </Link>
            );
          })}
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-6 pb-12 md:px-10 md:pb-16">
        <div className="border-t border-[var(--mira-line)] pt-6">
          <div className="flex flex-wrap items-center justify-center gap-3 text-center text-[11px] uppercase tracking-[0.18em] text-slate-500 md:gap-6">
            {TRUST_LINES.map((line, index) => (
              <div key={line} className="flex items-center gap-3">
                {index > 0 ? <span className="text-slate-300">•</span> : null}
                <span>{line}</span>
              </div>
            ))}
          </div>
          <div className="mt-5 text-center text-sm text-slate-500">
            BoundState MIRA
            <span className="mx-2 text-slate-300">/</span>
            engineering decision support for compatibility, governance, and system risk.
          </div>
        </div>
      </section>
    </div>
  );
}
