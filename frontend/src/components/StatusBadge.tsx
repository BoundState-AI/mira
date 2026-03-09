import { cn } from '@/lib/utils';

type Status = 'OK' | 'CAUTION' | 'PROHIBITED' | 'UNKNOWN' | string;

interface StatusBadgeProps {
  status: Status;
  className?: string;
}

const statusStyles: Record<string, string> = {
  OK: 'status-ok',
  APPROVED: 'status-ok',
  PASS: 'status-ok',
  COMPATIBLE: 'status-ok',
  CAUTION: 'status-caution',
  'PENDING REVIEW': 'status-caution',
  CONDITIONAL: 'status-caution',
  CLARIFY: 'status-caution',
  PROHIBITED: 'status-prohibited',
  INCOMPATIBLE: 'status-prohibited',
  REFUSE: 'status-prohibited',
  UNKNOWN: 'status-unknown',
};

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const normalizedStatus = status.toUpperCase();
  const styleClass = statusStyles[normalizedStatus] || 'status-unknown';
  
  return (
    <span
      className={cn(
        'inline-flex items-center px-3 py-1 rounded-sm text-xs font-medium tracking-wide uppercase',
        styleClass,
        className
      )}
    >
      {status}
    </span>
  );
}
