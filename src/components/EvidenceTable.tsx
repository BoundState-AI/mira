import type { Evidence } from '@/lib/api';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

interface EvidenceTableProps {
  evidence: Evidence[];
}

export function EvidenceTable({ evidence }: EvidenceTableProps) {
  if (evidence.length === 0) return null;

  return (
    <div className="rounded-md border border-border overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/50">
            <TableHead className="font-medium">Source</TableHead>
            <TableHead className="font-medium">Section</TableHead>
            <TableHead className="font-medium">Summary</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {evidence.map((item, idx) => (
            <TableRow key={idx} className="animate-fade-in" style={{ animationDelay: `${idx * 50}ms` }}>
              <TableCell className="font-mono text-sm">{item.source_id}</TableCell>
              <TableCell className="text-muted-foreground">{item.section}</TableCell>
              <TableCell>{item.summary}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
