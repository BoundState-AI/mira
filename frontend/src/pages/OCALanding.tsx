import { Link } from 'react-router-dom';

const STATS = [
  { value: '17', label: 'Ignition Mechanisms' },
  { value: '100%', label: 'Cited Verdicts' },
];

const PATHS = [
  {
    title: 'Workbench',
    subtitle: 'One material. One environment. Full verdict.',
    description:
      'Screen a single material against NASA-STD-6016C ignition mechanisms, pressure thresholds, and configuration rules. Every requirement cited to source, every mechanism traced to MNL-36.',
    href: '/oca/workbench',
    cta: 'Open Workbench',
  },
  {
    title: 'System Builder',
    subtitle: 'Build it. Connect it. Assess it.',
    description:
      'Lay out a multi-component oxygen system on a visual canvas. OCA propagates zone classifications, detects kindling chains, and rolls up a system-level disposition.',
    href: '/oca/system-builder',
    cta: 'Open System Builder',
  },
];

export default function OCALanding() {
  return (
    <div className="min-h-screen bg-[linear-gradient(180deg,#f7f4ee_0%,#fdfcf9_35%,#ffffff_100%)]">
      <div className="mx-auto flex max-w-6xl flex-col gap-12 px-6 py-10 lg:px-10">
        <section className="overflow-hidden rounded-[2rem] border border-stone-200 bg-[radial-gradient(circle_at_top_left,#fffaf0_0%,#f5f1e8_45%,#ebe5d8_100%)] p-8 shadow-[0_24px_80px_rgba(54,45,27,0.08)] lg:p-12">
          <div className="max-w-3xl">
            <div className="text-xs font-semibold uppercase tracking-[0.3em] text-stone-500">
              OCA by MIRA
            </div>
            <h1 className="mt-4 font-['DM_Sans'] text-4xl font-semibold tracking-tight text-stone-900 lg:text-6xl">
              Oxygen compatibility with cited, reviewable verdicts.
            </h1>
            <p className="mt-5 max-w-2xl text-base leading-7 text-stone-700 lg:text-lg">
              Move from material name to screening disposition with requirement traceability,
              mechanism-level evidence, and export artifacts your M&amp;P reviewer can actually use.
            </p>
          </div>

          <div className="mt-8 flex flex-wrap items-center gap-3 text-[11px] font-medium uppercase tracking-[0.24em] text-stone-500">
            <span>Every rule cited to source</span>
            <span className="text-stone-300">&middot;</span>
            <span>100% cited verdicts</span>
            <span className="text-stone-300">&middot;</span>
            <span>Screening aid &mdash; M&amp;P signoff required</span>
          </div>

          <div className="mt-8 grid gap-4 sm:grid-cols-2">
            {STATS.map((stat) => (
              <div key={stat.label} className="rounded-2xl border border-white/60 bg-white/70 px-5 py-4 backdrop-blur">
                <div className="text-3xl font-semibold text-stone-900">{stat.value}</div>
                <div className="mt-1 text-sm text-stone-600">{stat.label}</div>
              </div>
            ))}
          </div>
        </section>

        <section className="grid gap-5 lg:grid-cols-2">
          {PATHS.map((path) => (
            <article
              key={path.title}
              className="rounded-[1.75rem] border border-stone-200 bg-white p-7 shadow-[0_18px_50px_rgba(54,45,27,0.06)]"
            >
              <div className="text-xs font-semibold uppercase tracking-[0.24em] text-stone-500">
                {path.title}
              </div>
              <h2 className="mt-3 text-2xl font-semibold text-stone-900">{path.subtitle}</h2>
              <p className="mt-4 text-sm leading-7 text-stone-600">{path.description}</p>
              <Link
                to={path.href}
                className="mt-6 inline-flex items-center rounded-full border border-stone-900 px-4 py-2 text-sm font-medium text-stone-900 transition-colors hover:bg-stone-900 hover:text-white"
              >
                {path.cta}
              </Link>
            </article>
          ))}
        </section>

        <section className="rounded-[1.75rem] border border-slate-200 bg-slate-50 px-6 py-6 shadow-[0_12px_32px_rgba(15,23,42,0.05)]">
          <p className="text-[0.7rem] font-semibold uppercase tracking-[0.08em] text-slate-700">
            Data Provenance
          </p>
          <p className="mt-3 max-w-4xl text-sm leading-7 text-slate-600">
            Material properties in this tool are sourced from ASTM MNL36 (2nd Edition),
            NASA/TM-2007-213740, NASA-STD-6016C, and NASA-STD-6001B. All values include
            source document, table, and page citations. This data represents published
            test results from WSTF and ASTM G4 symposia &mdash; not specimen-specific MAPTIS
            records. For formal OCA submittals, integration with project-specific MAPTIS
            data and M&amp;P engineer review is required.
          </p>
        </section>
      </div>
    </div>
  );
}

