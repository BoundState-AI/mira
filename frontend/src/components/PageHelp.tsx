/**
 * Page Help Component
 * Displays help information for each MIRA tab/page
 */

import { HelpCircle, BookOpen, Lightbulb, Target, CheckCircle2 } from "lucide-react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

export interface PageHelpContent {
  title: string;
  description: string;
  whatItDoes: string[];
  howToUse: string[];
  useCases: string[];
  tips?: string[];
  relatedPages?: { name: string; path: string }[];
  apiEndpoint?: string;
}

interface PageHelpProps {
  content: PageHelpContent;
  className?: string;
}

export function PageHelp({ content, className = "" }: PageHelpProps) {
  const { t } = useTranslation("help");

  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className={`h-8 w-8 rounded-full ${className}`}
          title={t("common.whatItDoes", { defaultValue: "Help" })}
        >
          <HelpCircle className="h-5 w-5 text-muted-foreground hover:text-primary transition-colors" />
        </Button>
      </DialogTrigger>

      <DialogContent className="max-w-3xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-2xl flex items-center gap-2">
            <BookOpen className="h-6 w-6 text-primary" />
            {content.title}
          </DialogTitle>
          <DialogDescription className="text-base">
            {content.description}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-6 mt-4">
          {/* What It Does Section */}
          <div>
            <h3 className="text-lg font-semibold flex items-center gap-2 mb-3">
              <Target className="h-5 w-5 text-blue-500" />
              {t("common.whatItDoes", { defaultValue: "What This Page Does" })}
            </h3>
            <ul className="space-y-2">
              {content.whatItDoes.map((item, index) => (
                <li key={index} className="flex items-start gap-2">
                  <CheckCircle2 className="h-4 w-4 text-green-500 mt-0.5 flex-shrink-0" />
                  <span className="text-sm text-muted-foreground">{item}</span>
                </li>
              ))}
            </ul>
          </div>

          <Separator />

          {/* How To Use Section */}
          <div>
            <h3 className="text-lg font-semibold flex items-center gap-2 mb-3">
              <Lightbulb className="h-5 w-5 text-yellow-500" />
              {t("common.howToUse", { defaultValue: "How To Use" })}
            </h3>
            <ol className="space-y-2 list-decimal list-inside">
              {content.howToUse.map((step, index) => (
                <li key={index} className="text-sm text-muted-foreground pl-2">
                  {step}
                </li>
              ))}
            </ol>
          </div>

          <Separator />

          {/* Use Cases Section */}
          <div>
            <h3 className="text-lg font-semibold mb-3">
              {t("common.useCases", { defaultValue: "Example Use Cases" })}
            </h3>
            <div className="space-y-3">
              {content.useCases.map((useCase, index) => (
                <div key={index} className="bg-muted/50 p-3 rounded-lg">
                  <p className="text-sm italic text-muted-foreground">"{useCase}"</p>
                </div>
              ))}
            </div>
          </div>

          {/* Tips Section (Optional) */}
          {content.tips && content.tips.length > 0 && (
            <>
              <Separator />
              <div>
                <h3 className="text-lg font-semibold mb-3">
                  {t("common.tips", { defaultValue: "Pro Tips" })}
                </h3>
                <ul className="space-y-2">
                  {content.tips.map((tip, index) => (
                    <li key={index} className="text-sm text-muted-foreground flex items-start gap-2">
                      <span className="text-primary font-bold">•</span>
                      {tip}
                    </li>
                  ))}
                </ul>
              </div>
            </>
          )}

          {/* API Endpoint (Optional) */}
          {content.apiEndpoint && (
            <>
              <Separator />
              <div>
                <h3 className="text-lg font-semibold mb-2">
                  {t("common.apiEndpoint", { defaultValue: "API Endpoint" })}
                </h3>
                <code className="block bg-muted p-2 rounded text-sm font-mono">
                  {content.apiEndpoint}
                </code>
              </div>
            </>
          )}

          {/* Related Pages (Optional) */}
          {content.relatedPages && content.relatedPages.length > 0 && (
            <>
              <Separator />
              <div>
                <h3 className="text-lg font-semibold mb-3">
                  {t("common.relatedPages", { defaultValue: "Related Pages" })}
                </h3>
                <div className="flex flex-wrap gap-2">
                  {content.relatedPages.map((page, index) => (
                    <Badge key={index} variant="outline" className="cursor-pointer hover:bg-primary/10">
                      <Link to={page.path}>{page.name}</Link>
                    </Badge>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Compact version for tight spaces
 */
export function PageHelpCompact({ content }: PageHelpProps) {
  const { t } = useTranslation("help");

  return (
    <Dialog>
      <DialogTrigger asChild>
        <button
          className="text-muted-foreground hover:text-primary transition-colors"
          title={t("common.whatItDoes", { defaultValue: "What does this page do?" })}
        >
          <HelpCircle className="h-4 w-4" />
        </button>
      </DialogTrigger>

      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{content.title}</DialogTitle>
          <DialogDescription>{content.description}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <h4 className="font-semibold mb-2">
              {t("common.whatItDoes", { defaultValue: "What it does:" })}
            </h4>
            <ul className="text-sm space-y-1">
              {content.whatItDoes.slice(0, 3).map((item, i) => (
                <li key={i}>• {item}</li>
              ))}
            </ul>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
