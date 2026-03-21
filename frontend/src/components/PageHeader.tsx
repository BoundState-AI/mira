import type { ReactNode } from "react";

import { PageHelp, PageHelpContent } from "@/components/PageHelp";

interface PageHeaderProps {
  title: string;
  description?: string;
  helpContent?: PageHelpContent;
  actions?: ReactNode;
}

export function PageHeader({ title, description, helpContent, actions }: PageHeaderProps) {
  return (
    <div className="mb-8 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div>
        <h1 className="flex items-center gap-3 text-2xl font-bold tracking-tight text-foreground">
          {title}
          {helpContent && <PageHelp content={helpContent} />}
        </h1>
        {description && (
          <p className="mt-1 text-muted-foreground">{description}</p>
        )}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}
