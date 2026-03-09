import { Lock } from 'lucide-react';

export type GalvanicSnapPoint = {
  id: string;
  label: string;
  mode: 'current' | 'surface_shift' | 'rate_modifier' | 'circuit_break';
  effective_delta_mv: number;
  effective_potential_mv: number;
  severity: 'COMPATIBLE' | 'CAUTION' | 'INCOMPATIBLE';
  prescription: string;
  surface_label?: string;
};

interface GalvanicNumberLineProps {
  leftLabel: string;
  rightLabel: string;
  leftPotentialMv: number;
  rightPotentialMv: number;
  snapPoints: GalvanicSnapPoint[];
  selectedIndex: number;
  onSelectIndex: (index: number) => void;
}

const AXIS_MIN = -1600;
const AXIS_MAX = 300;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function positionForPotential(potentialMv: number): number {
  return ((clamp(potentialMv, AXIS_MIN, AXIS_MAX) - AXIS_MIN) / (AXIS_MAX - AXIS_MIN)) * 100;
}

function severityColor(severity: string): string {
  if (severity === 'COMPATIBLE') return '#16a34a';
  if (severity === 'CAUTION') return '#f59e0b';
  return '#ef4444';
}

export function GalvanicNumberLine({
  leftLabel,
  rightLabel,
  leftPotentialMv,
  rightPotentialMv,
  snapPoints,
  selectedIndex,
  onSelectIndex,
}: GalvanicNumberLineProps) {
  const selected = snapPoints[selectedIndex] ?? snapPoints[0];
  const leftX = positionForPotential(leftPotentialMv);
  const rightX = positionForPotential(rightPotentialMv);
  const targetX = positionForPotential(selected.effective_potential_mv);
  const gapColor = selected.mode === 'circuit_break' ? '#94a3b8' : severityColor(selected.severity);

  return (
    <div className="rounded-2xl border bg-slate-950 p-5 text-slate-50">
      <div className="flex items-center justify-between text-xs uppercase tracking-[0.18em] text-slate-400">
        <span>Effective Electrochemical Potential (mV vs SCE)</span>
        <span>{selected.label}</span>
      </div>

      <div className="mt-4 flex justify-between text-xs text-slate-400">
        <span>Active / anodic</span>
        <span>Noble / cathodic</span>
      </div>

      <div className="relative mt-4 h-44">
        <svg className="h-full w-full overflow-visible" viewBox="0 0 1000 176" preserveAspectRatio="none">
          <defs>
            <linearGradient id="galvanic-risk-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#16a34a" />
              <stop offset="50%" stopColor="#f59e0b" />
              <stop offset="100%" stopColor="#ef4444" />
            </linearGradient>
          </defs>

          <line x1="32" y1="96" x2="968" y2="96" stroke="#334155" strokeWidth="10" strokeLinecap="round" />
          <line
            x1={32 + ((Math.min(leftX, targetX) / 100) * 936)}
            y1="96"
            x2={32 + ((Math.max(leftX, targetX) / 100) * 936)}
            y2="96"
            stroke={selected.mode === 'circuit_break' ? '#94a3b8' : 'url(#galvanic-risk-gradient)'}
            strokeWidth="14"
            strokeLinecap="round"
            opacity={selected.mode === 'rate_modifier' ? 0.75 : 1}
          />
          {selected.mode === 'circuit_break' && (
            <line
              x1={32 + ((Math.min(leftX, rightX) / 100) * 936)}
              y1="96"
              x2={32 + ((Math.max(leftX, rightX) / 100) * 936)}
              y2="96"
              stroke="#cbd5e1"
              strokeDasharray="10 8"
              strokeWidth="4"
              strokeLinecap="round"
            />
          )}
        </svg>

        <div
          className="absolute -translate-x-1/2 rounded-xl border border-sky-200 bg-sky-50 px-3 py-2 text-sky-950 shadow-sm transition-all duration-300"
          style={{ left: `${leftX}%`, top: '0px' }}
        >
          <div className="text-[11px] uppercase tracking-wide opacity-70">Left box</div>
          <div className="text-sm font-semibold">{leftLabel}</div>
          <div className="text-xs">{Math.round(leftPotentialMv)} mV</div>
        </div>

        <div
          className="absolute -translate-x-1/2 rounded-xl border border-slate-600 bg-slate-900/70 px-3 py-2 text-slate-200 shadow-sm transition-all duration-300"
          style={{ left: `${rightX}%`, top: '112px' }}
        >
          <div className="text-[11px] uppercase tracking-wide opacity-70">Intrinsic</div>
          <div className="text-sm font-semibold">{rightLabel}</div>
          <div className="text-xs">{Math.round(rightPotentialMv)} mV</div>
        </div>

        <div
          className={`absolute -translate-x-1/2 rounded-xl border px-3 py-2 shadow-lg transition-all duration-300 ${
            selected.mode === 'circuit_break'
              ? 'border-slate-300 bg-slate-100 text-slate-950'
              : selected.severity === 'COMPATIBLE'
                ? 'border-emerald-200 bg-emerald-50 text-emerald-950'
                : selected.severity === 'CAUTION'
                  ? 'border-amber-200 bg-amber-50 text-amber-950'
                  : 'border-rose-200 bg-rose-50 text-rose-950'
          }`}
          style={{ left: `${selected.mode === 'circuit_break' ? rightX : targetX}%`, top: '48px' }}
        >
          <div className="flex items-center justify-center gap-1 text-[11px] uppercase tracking-wide opacity-70">
            {selected.mode === 'circuit_break' && <Lock className="h-3 w-3" />}
            <span>Target box</span>
          </div>
          <div className="text-sm font-semibold">{selected.label}</div>
          <div className="text-xs">
            {selected.mode === 'surface_shift'
              ? `${Math.round(selected.effective_potential_mv)} mV`
              : `${Math.round(selected.effective_delta_mv)} mV effective`}
          </div>
        </div>
      </div>

      <div className="mt-2 flex justify-between text-xs text-slate-400">
        <span>-1600 mV</span>
        <span>-800 mV</span>
        <span>0 mV</span>
        <span>+300 mV</span>
      </div>

      <div className="mt-6">
        <input
          type="range"
          min={0}
          max={Math.max(0, snapPoints.length - 1)}
          step={1}
          value={selectedIndex}
          onChange={(event) => onSelectIndex(Number(event.target.value))}
          className="w-full cursor-ew-resize accent-slate-200"
        />
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {snapPoints.map((point, index) => (
          <button
            key={point.id}
            type="button"
            onClick={() => onSelectIndex(index)}
            className={`rounded-full border px-3 py-1 text-xs transition-colors ${
              index === selectedIndex
                ? 'border-slate-100 bg-slate-100 text-slate-950'
                : 'border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800'
            }`}
          >
            {point.label}
          </button>
        ))}
      </div>

      <div className="mt-4 rounded-xl border border-slate-700 bg-slate-900/70 p-4 text-sm text-slate-300">
        <div className="font-medium text-slate-100">{selected.prescription}</div>
        {selected.surface_label && (
          <div className="mt-2 text-xs text-slate-400">Effective surface state: {selected.surface_label}</div>
        )}
        {selected.mode === 'circuit_break' && (
          <div className="mt-2 flex items-center gap-2 text-xs text-slate-300">
            <Lock className="h-3.5 w-3.5" />
            Electrical circuit broken. Boxes stay at true potentials; galvanic reaction cannot close.
          </div>
        )}
      </div>

      <div className="mt-3 flex justify-between text-xs text-slate-400">
        <span style={{ color: '#16a34a' }}>Green &lt;250 mV</span>
        <span style={{ color: '#f59e0b' }}>Yellow 250-500 mV</span>
        <span style={{ color: '#ef4444' }}>Red &gt;500 mV</span>
      </div>
    </div>
  );
}
