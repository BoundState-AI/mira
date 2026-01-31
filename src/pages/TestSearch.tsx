import { useState } from 'react';
import { PageHeader } from '@/components/PageHeader';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent } from '@/components/ui/card';
import { Loader2, Search, FileText } from 'lucide-react';
import { searchTestData, type SearchHit } from '@/lib/api';

export default function TestSearch() {
  const [query, setQuery] = useState('');
  const [materialFilter, setMaterialFilter] = useState('');
  const [testClass, setTestClass] = useState('');
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<SearchHit[]>([]);
  const [searched, setSearched] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query) return;

    setLoading(true);
    setSearched(true);

    try {
      const response = await searchTestData({
        query,
        material_key: materialFilter || undefined,
        test_class: testClass || undefined,
      });
      setResults(response.hits);
    } catch (error) {
      console.error('Search failed:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Test Data Search"
        description="Search corrosion, flammability, and material test records"
      />

      <form onSubmit={handleSubmit} className="space-y-6">
        <div className="space-y-2">
          <Label htmlFor="query">Search Query</Label>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              id="query"
              placeholder="Search test data..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="pl-10"
            />
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="material-filter">Material Filter (optional)</Label>
            <Input
              id="material-filter"
              placeholder="e.g., SS316"
              value={materialFilter}
              onChange={(e) => setMaterialFilter(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="test-class">Test Class (optional)</Label>
            <Input
              id="test-class"
              placeholder="e.g., corrosion, flammability"
              value={testClass}
              onChange={(e) => setTestClass(e.target.value)}
            />
          </div>
        </div>

        <Button type="submit" disabled={loading || !query}>
          {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          Search
        </Button>
      </form>

      {/* Results */}
      {searched && (
        <div className="mt-8 space-y-4 animate-fade-in">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">
              Results ({results.length})
            </h3>
          </div>

          {results.length === 0 ? (
            <Card>
              <CardContent className="py-8 text-center text-muted-foreground">
                No results found for "{query}"
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
              {results.map((hit, idx) => (
                <Card
                  key={hit.id}
                  className="cursor-pointer hover:border-primary/50 transition-colors animate-slide-in"
                  style={{ animationDelay: `${idx * 50}ms` }}
                >
                  <CardContent className="py-4">
                    <div className="flex items-start gap-3">
                      <FileText className="h-5 w-5 text-primary mt-0.5 flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <h4 className="font-medium text-foreground truncate">{hit.title}</h4>
                          <span className="text-xs text-muted-foreground font-mono">
                            {(hit.score * 100).toFixed(0)}%
                          </span>
                        </div>
                        <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                          {hit.snippet}
                        </p>
                        <span className="text-xs text-muted-foreground/70 font-mono mt-2 block">
                          {hit.id}
                        </span>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
