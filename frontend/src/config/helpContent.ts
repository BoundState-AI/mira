/**
 * Localized Help Content
 * Runtime i18n-backed help content for all major pages.
 */

import i18n from "@/i18n";
import type { PageHelpContent } from "@/components/PageHelp";

const KNOWN_HELP_SECTIONS = new Set([
  "query",
  "knowledgeTwins",
  "testClasses",
  "miulBuilder",
  "muaGenerator",
  "gasCompatibility",
  "complianceAnalysis",
  "dtTreeEditor",
  "mpPlan",
]);

const HELP_METADATA: Record<
  string,
  {
    relatedPages?: { navKey: string; defaultName: string; path: string }[];
    apiEndpoint?: string;
  }
> = {
  query: {
    relatedPages: [
      { navKey: "knowledgeTwins", defaultName: "Knowledge Twins", path: "/" },
      { navKey: "testClasses", defaultName: "Test Classes", path: "/test-classes" },
    ],
    apiEndpoint: "POST /mira/query",
  },
  knowledgeTwins: {
    relatedPages: [
      { navKey: "query", defaultName: "MIRA Query", path: "/query" },
      { navKey: "testClasses", defaultName: "Test Classes", path: "/test-classes" },
    ],
    apiEndpoint: "POST /api/v1/o2/search-bok, POST /api/v1/h2/search-bok",
  },
  testClasses: {
    relatedPages: [
      { navKey: "query", defaultName: "MIRA Query", path: "/query" },
      { navKey: "knowledgeTwins", defaultName: "Knowledge Twins", path: "/" },
    ],
    apiEndpoint: "GET /api/test-classes/counts",
  },
  miulBuilder: {
    relatedPages: [
      { navKey: "muaGenerator", defaultName: "MUA Wizard", path: "/mua-v7" },
      { navKey: "mpPlan", defaultName: "M&P Plan", path: "/mp-plan" },
    ],
    apiEndpoint: "POST /api/miul/v4/extract, POST /api/miul/v4/build",
  },
  muaGenerator: {
    relatedPages: [
      { navKey: "miulBuilder", defaultName: "MIUL Builder", path: "/miul" },
      { navKey: "mpPlan", defaultName: "M&P Plan", path: "/mp-plan" },
    ],
    apiEndpoint: "POST /api/mua/v7/*",
  },
  gasCompatibility: {
    relatedPages: [
      { navKey: "query", defaultName: "MIRA Query", path: "/query" },
      { navKey: "knowledgeTwins", defaultName: "Knowledge Twins", path: "/" },
    ],
    apiEndpoint: "POST /mira/o2/compatibility, POST /mira/h2/compatibility",
  },
  complianceAnalysis: {
    relatedPages: [
      { navKey: "muaGenerator", defaultName: "MUA Wizard", path: "/mua-v7" },
      { navKey: "mpPlan", defaultName: "M&P Plan", path: "/mp-plan" },
    ],
    apiEndpoint: "POST /compliance/analyze",
  },
  dtTreeEditor: {
    relatedPages: [{ navKey: "miulBuilder", defaultName: "MIUL Builder", path: "/miul" }],
    apiEndpoint: "POST /api/dt-tree/extract",
  },
  mpPlan: {
    relatedPages: [
      { navKey: "miulBuilder", defaultName: "MIUL Builder", path: "/miul" },
      { navKey: "muaGenerator", defaultName: "MUA Wizard", path: "/mua-v7" },
    ],
    apiEndpoint: "POST /api/mp-plan/*",
  },
};

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

export function getHelpContent(section: string): PageHelpContent {
  const key = KNOWN_HELP_SECTIONS.has(section) ? section : "query";
  const metadata = HELP_METADATA[key] ?? {};

  const title = i18n.t(`${key}.title`, { ns: "help", defaultValue: i18n.t("query.title", { ns: "help" }) });
  const description = i18n.t(`${key}.description`, {
    ns: "help",
    defaultValue: i18n.t("query.description", { ns: "help" }),
  });
  const whatItDoes = asStringArray(i18n.t(`${key}.whatItDoes`, { ns: "help", returnObjects: true }));
  const howToUse = asStringArray(i18n.t(`${key}.howToUse`, { ns: "help", returnObjects: true }));
  const useCases = asStringArray(i18n.t(`${key}.useCases`, { ns: "help", returnObjects: true }));
  const tips = asStringArray(i18n.t(`${key}.tips`, { ns: "help", returnObjects: true }));

  return {
    title,
    description,
    whatItDoes,
    howToUse,
    useCases,
    tips,
    relatedPages: metadata.relatedPages?.map((page) => ({
      name: i18n.t(page.navKey, { ns: "navigation", defaultValue: page.defaultName }),
      path: page.path,
    })),
    apiEndpoint: metadata.apiEndpoint,
  };
}

/**
 * Backward-compatible object-style access used by pages:
 *   helpContent.query, helpContent.miulBuilder, etc.
 */
const helpContent = new Proxy({} as Record<string, PageHelpContent>, {
  get(_target, prop) {
    return getHelpContent(String(prop));
  },
});

export default helpContent;
