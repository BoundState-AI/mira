import { useTranslation } from 'react-i18next';
import { Globe } from 'lucide-react';
import { supportedLanguages, type LanguageCode } from '@/i18n';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Button } from '@/components/ui/button';

export function LanguageSelector() {
  const { i18n } = useTranslation();
  const activeLanguageCode = (i18n.resolvedLanguage || i18n.language || 'en').split('-')[0];

  const currentLanguage = supportedLanguages.find(
    (lang) => lang.code === activeLanguageCode
  ) || supportedLanguages[0];

  const handleLanguageChange = (code: LanguageCode) => {
    i18n.changeLanguage(code);
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6 text-sidebar-foreground/50 hover:text-sidebar-foreground"
        >
          <Globe className="h-3 w-3" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[120px]">
        {supportedLanguages.map((lang) => (
          <DropdownMenuItem
            key={lang.code}
            onClick={() => handleLanguageChange(lang.code)}
            className={
              currentLanguage.code === lang.code
                ? 'bg-accent font-medium'
                : ''
            }
          >
            {lang.nativeName}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
