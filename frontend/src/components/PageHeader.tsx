import { PageHelp, PageHelpContent } from "@/components/PageHelp";

interface PageHeaderProps {
  title: string;
  description?: string;
  helpContent?: PageHelpContent;
}

export function PageHeader({ title, description, helpContent }: PageHeaderProps) {
  return (
    <div className="mb-8">
      <h1 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-3">
        {title}
        {helpContent && <PageHelp content={helpContent} />}
      </h1>
      {description && (
        <p className="mt-1 text-muted-foreground">{description}</p>
      )}
    </div>
  );
}
