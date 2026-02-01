import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

// English translations
import enCommon from './locales/en/common.json';
import enNavigation from './locales/en/navigation.json';
import enHelp from './locales/en/help.json';
import enKnowledgeTwins from './locales/en/pages/knowledgeTwins.json';
import enGasCompatibility from './locales/en/pages/gasCompatibility.json';
import enQuery from './locales/en/pages/query.json';
import enMpPlanGenerator from './locales/en/pages/mpPlanGenerator.json';
import enTestClasses from './locales/en/pages/testClasses.json';
import enMiulBuilder from './locales/en/pages/miulBuilder.json';
import enDtTreeEditor from './locales/en/pages/dtTreeEditor.json';
import enMuaGenerator from './locales/en/pages/muaGenerator.json';
import enComplianceAnalysis from './locales/en/pages/complianceAnalysis.json';

// Japanese translations
import jaCommon from './locales/ja/common.json';
import jaNavigation from './locales/ja/navigation.json';
import jaHelp from './locales/ja/help.json';
import jaKnowledgeTwins from './locales/ja/pages/knowledgeTwins.json';
import jaGasCompatibility from './locales/ja/pages/gasCompatibility.json';
import jaQuery from './locales/ja/pages/query.json';
import jaMpPlanGenerator from './locales/ja/pages/mpPlanGenerator.json';
import jaTestClasses from './locales/ja/pages/testClasses.json';
import jaMiulBuilder from './locales/ja/pages/miulBuilder.json';
import jaDtTreeEditor from './locales/ja/pages/dtTreeEditor.json';
import jaMuaGenerator from './locales/ja/pages/muaGenerator.json';
import jaComplianceAnalysis from './locales/ja/pages/complianceAnalysis.json';

// French translations
import frCommon from './locales/fr/common.json';
import frNavigation from './locales/fr/navigation.json';
import frHelp from './locales/fr/help.json';
import frKnowledgeTwins from './locales/fr/pages/knowledgeTwins.json';
import frGasCompatibility from './locales/fr/pages/gasCompatibility.json';
import frQuery from './locales/fr/pages/query.json';
import frMpPlanGenerator from './locales/fr/pages/mpPlanGenerator.json';
import frTestClasses from './locales/fr/pages/testClasses.json';
import frMiulBuilder from './locales/fr/pages/miulBuilder.json';
import frDtTreeEditor from './locales/fr/pages/dtTreeEditor.json';
import frMuaGenerator from './locales/fr/pages/muaGenerator.json';
import frComplianceAnalysis from './locales/fr/pages/complianceAnalysis.json';

export const supportedLanguages = [
  { code: 'en', name: 'English', nativeName: 'English' },
  { code: 'ja', name: 'Japanese', nativeName: '日本語' },
  { code: 'fr', name: 'French', nativeName: 'Français' },
] as const;

export type LanguageCode = typeof supportedLanguages[number]['code'];

const resources = {
  en: {
    common: enCommon,
    navigation: enNavigation,
    help: enHelp,
    knowledgeTwins: enKnowledgeTwins,
    gasCompatibility: enGasCompatibility,
    query: enQuery,
    mpPlanGenerator: enMpPlanGenerator,
    testClasses: enTestClasses,
    miulBuilder: enMiulBuilder,
    dtTreeEditor: enDtTreeEditor,
    muaGenerator: enMuaGenerator,
    complianceAnalysis: enComplianceAnalysis,
  },
  ja: {
    common: jaCommon,
    navigation: jaNavigation,
    help: jaHelp,
    knowledgeTwins: jaKnowledgeTwins,
    gasCompatibility: jaGasCompatibility,
    query: jaQuery,
    mpPlanGenerator: jaMpPlanGenerator,
    testClasses: jaTestClasses,
    miulBuilder: jaMiulBuilder,
    dtTreeEditor: jaDtTreeEditor,
    muaGenerator: jaMuaGenerator,
    complianceAnalysis: jaComplianceAnalysis,
  },
  fr: {
    common: frCommon,
    navigation: frNavigation,
    help: frHelp,
    knowledgeTwins: frKnowledgeTwins,
    gasCompatibility: frGasCompatibility,
    query: frQuery,
    mpPlanGenerator: frMpPlanGenerator,
    testClasses: frTestClasses,
    miulBuilder: frMiulBuilder,
    dtTreeEditor: frDtTreeEditor,
    muaGenerator: frMuaGenerator,
    complianceAnalysis: frComplianceAnalysis,
  },
};

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    fallbackLng: 'en',
    defaultNS: 'common',
    ns: [
      'common',
      'navigation',
      'help',
      'knowledgeTwins',
      'gasCompatibility',
      'query',
      'mpPlanGenerator',
      'testClasses',
      'miulBuilder',
      'dtTreeEditor',
      'muaGenerator',
      'complianceAnalysis',
    ],

    detection: {
      order: ['localStorage', 'navigator'],
      caches: ['localStorage'],
      lookupLocalStorage: 'mira-language',
    },

    interpolation: {
      escapeValue: false, // React already escapes
    },
  });

export default i18n;
