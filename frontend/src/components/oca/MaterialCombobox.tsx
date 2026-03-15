import { useEffect, useRef, useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { ocaSuggestMaterials, type OCAMaterialSuggestion } from '@/lib/oca-api';

const FAMILY_LABELS: Record<string, string> = {
  nickel_alloy: 'Nickel Alloy',
  copper: 'Copper',
  austenitic_steel: 'Austenitic SS',
  aluminum: 'Aluminum',
  titanium: 'Titanium',
  magnesium: 'Magnesium',
  fluoropolymer: 'Fluoropolymer',
  perfluoroelastomer: 'Fluoroelastomer',
  polymer_organic: 'Polymer',
  elastomer: 'Elastomer',
  carbon_steel: 'Steel',
  composite: 'Composite',
  unknown: 'Unknown',
};

const RATING_COLORS: Record<string, string> = {
  A: 'bg-emerald-100 text-emerald-800',
  B: 'bg-sky-100 text-sky-800',
  C: 'bg-amber-100 text-amber-800',
  D: 'bg-rose-100 text-rose-800',
  X: 'bg-rose-200 text-rose-900',
  U: 'bg-slate-100 text-slate-600',
};

interface MaterialComboboxProps {
  value: string;
  onChange: (value: string) => void;
  id?: string;
  placeholder?: string;
}

export function MaterialCombobox({
  value,
  onChange,
  id = 'material-name',
  placeholder = 'Start typing a material name...',
}: MaterialComboboxProps) {
  const [open, setOpen] = useState(false);
  const [suggestions, setSuggestions] = useState<OCAMaterialSuggestion[]>([]);
  const [highlighted, setHighlighted] = useState(-1);
  const containerRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      const results = await ocaSuggestMaterials(value, 12);
      setSuggestions(results);
      setHighlighted(-1);
    }, 150);

    return () => clearTimeout(debounceRef.current);
  }, [value]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  function handleKeyDown(event: React.KeyboardEvent) {
    if (!open || suggestions.length === 0) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setHighlighted((current) => Math.min(current + 1, suggestions.length - 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setHighlighted((current) => Math.max(current - 1, 0));
    } else if (event.key === 'Enter' && highlighted >= 0) {
      event.preventDefault();
      selectMaterial(suggestions[highlighted]);
    } else if (event.key === 'Escape') {
      setOpen(false);
    }
  }

  function selectMaterial(suggestion: OCAMaterialSuggestion) {
    onChange(suggestion.material_name);
    setOpen(false);
  }

  return (
    <div ref={containerRef} className="relative">
      <Input
        id={id}
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        autoComplete="off"
      />
      {open && suggestions.length > 0 ? (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 max-h-72 overflow-auto rounded-lg border border-slate-200 bg-white shadow-lg">
          <div className="px-3 py-1.5 text-[11px] font-medium uppercase tracking-wider text-slate-400">
            Reference materials ({suggestions.length})
          </div>
          {suggestions.map((suggestion, index) => (
            <button
              key={suggestion.material_name}
              type="button"
              className={`flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm transition-colors ${
                index === highlighted ? 'bg-slate-100' : 'hover:bg-slate-50'
              }`}
              onMouseEnter={() => setHighlighted(index)}
              onMouseDown={(event) => {
                event.preventDefault();
                selectMaterial(suggestion);
              }}
            >
              <div className="min-w-0">
                <div className="font-medium text-slate-900">{suggestion.material_name}</div>
                <div className="truncate text-xs text-slate-500">
                  {FAMILY_LABELS[suggestion.family] ?? suggestion.family}
                </div>
              </div>
              <Badge
                className={`shrink-0 text-[10px] ${
                  RATING_COLORS[suggestion.flammability_rating] ?? RATING_COLORS.U
                }`}
              >
                {suggestion.flammability_rating}
              </Badge>
            </button>
          ))}
          <div className="border-t border-slate-100 px-3 py-1.5 text-[10px] text-slate-400">
            Not listed? Type the full name — the engine will infer the family.
          </div>
        </div>
      ) : null}
    </div>
  );
}

