import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { PageHelp } from '@/components/PageHelp'
import helpContent from '@/config/helpContent'
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  HelpCircle,
  Flame,
  Droplet,
  Brain,
  Search,
  Loader2,
  Sparkles
} from 'lucide-react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Rating display configuration
const RATING_CONFIG: Record<string, {
  label: string
  icon: typeof CheckCircle2
  color: string
  bgColor: string
  borderColor: string
  description: string
}> = {
  'A': {
    label: 'Excellent',
    icon: CheckCircle2,
    color: 'text-green-600',
    bgColor: 'bg-green-50',
    borderColor: 'border-green-500',
    description: 'Approved, high heritage'
  },
  'B': {
    label: 'Good',
    icon: CheckCircle2,
    color: 'text-blue-600',
    bgColor: 'bg-blue-50',
    borderColor: 'border-blue-500',
    description: 'Approved, moderate heritage'
  },
  'C': {
    label: 'Fair',
    icon: AlertTriangle,
    color: 'text-yellow-600',
    bgColor: 'bg-yellow-50',
    borderColor: 'border-yellow-500',
    description: 'Approved, limited heritage'
  },
  'D': {
    label: 'Poor',
    icon: AlertTriangle,
    color: 'text-orange-600',
    bgColor: 'bg-orange-50',
    borderColor: 'border-orange-500',
    description: 'Conditionally approved'
  },
  'X': {
    label: 'Fail',
    icon: XCircle,
    color: 'text-red-600',
    bgColor: 'bg-red-50',
    borderColor: 'border-red-500',
    description: 'Not approved'
  },
  'U': {
    label: 'Unknown',
    icon: HelpCircle,
    color: 'text-gray-600',
    bgColor: 'bg-gray-50',
    borderColor: 'border-gray-500',
    description: 'Rating not available'
  }
}

interface Material {
  material_key: string
  material_name: string
  material_designation?: string
  o2_rating?: string
  h2_rating?: string
  flamm_rating?: string
  corr_rating?: string
  scc_rating?: string
  tvs_rating?: string
  tox_rating?: string
  fs_rating?: string
  score?: number
  snippet?: string
}

interface BOKResult {
  rank: number
  relevance_score: number
  text: string
  source: string
  section: string
  page?: number | null
  tags: string[]
}

interface HybridQueryResponse {
  status: string
  query: string
  timestamp: string
  answer?: string
  explanation?: string
  deterministic_decision?: string
  decision_source?: string
  decision_rationale?: string
  evidence_summary: {
    mua_precedents_found: number
    test_results_found: number
    requirements_evaluated: number
    semantic_results_found: number
    high_confidence_semantic: number
  }
  constraints?: Record<string, unknown>
  decisions?: Array<{
    decision: string
    confidence: string
    reasoning: string
    citations: string[]
  }>
  sql_evidence?: {
    mua_precedents: unknown[]
    test_results: unknown[]
  }
  semantic_evidence?: {
    total_results: number
    results: Array<{
      text: string
      source: string
      score: number
      metadata?: unknown
    }>
  }
  insufficient_data: boolean
  error?: string
}

export default function KnowledgeTwins() {
  const { t } = useTranslation('knowledgeTwins')
  const [mode, setMode] = useState<'browse' | 'ask'>('browse')
  const [activeFluid, setActiveFluid] = useState<'oxygen' | 'hydrogen'>('oxygen')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [materials, setMaterials] = useState<Material[]>([])
  const [bokResults, setBokResults] = useState<BOKResult[]>([])
  const [hybridResponse, setHybridResponse] = useState<HybridQueryResponse | null>(null)
  const [llmProvider, setLlmProvider] = useState<'ollama' | 'haiku'>('ollama')
  const [error, setError] = useState<string | null>(null)

  const handleSearch = async () => {
    if (!query.trim()) return

    setLoading(true)
    setError(null)
    setMaterials([])
    setBokResults([])

    try {
      // Call BOTH endpoints in parallel
      const [bokResponse, materialResponse] = await Promise.all([
        // BOK standards search
        fetch(`${API_URL}/api/v1/${activeFluid === 'oxygen' ? 'o2' : 'h2'}/search-bok`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            query,
            k: 10
          })
        }),
        // Material search
        fetch(`${API_URL}/api/search`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            query,
            top_k: 50
          })
        })
      ])

      if (!bokResponse.ok || !materialResponse.ok) {
        throw new Error(t('errors.searchError', { defaultValue: 'Search failed' }))
      }

      const bokData = await bokResponse.json()
      const materialData = await materialResponse.json()

      console.log('BOK Response:', bokData)
      console.log('Material Response:', materialData)

      setBokResults(bokData.results || [])
      setMaterials(materialData.results || [])

    } catch (err) {
      setError(err instanceof Error ? err.message : t('errors.searchError', { defaultValue: 'Search failed' }))
      console.error('Search error:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleAsk = async () => {
    if (!query.trim()) return

    setLoading(true)
    setError(null)
    setHybridResponse(null)
    setMaterials([])
    setBokResults([])

    try {
      const response = await fetch(
        `${API_URL}/api/query/hybrid`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            query: query,
            enable_semantic: true,
            llm_provider: llmProvider
          })
        }
      )

      if (!response.ok) {
        throw new Error(t('errors.questionError', { defaultValue: 'Question failed' }))
      }

      const data = await response.json()
      console.log('Hybrid Query Response:', data)
      setHybridResponse(data)

    } catch (err) {
      setError(err instanceof Error ? err.message : t('errors.questionError', { defaultValue: 'Question failed' }))
      console.error('Ask error:', err)
    } finally {
      setLoading(false)
    }
  }

  // Group materials by rating
  const groupedMaterials = materials.reduce((acc, material) => {
    const ratingField = activeFluid === 'oxygen' ? 'o2_rating' : 'h2_rating'
    const rawRating = material[ratingField as keyof Material] as string | undefined
    const rating = (rawRating === 'No data' || !rawRating) ? 'U' : rawRating

    if (!acc[rating]) {
      acc[rating] = []
    }
    acc[rating].push(material)

    return acc
  }, {} as Record<string, Material[]>)

  // Sort ratings: A -> B -> C -> D -> X -> U
  const ratingOrder = ['A', 'B', 'C', 'D', 'X', 'U']
  const sortedRatings = ratingOrder.filter(rating => groupedMaterials[rating])

  const getRatingBadge = (rating: string, size: 'sm' | 'lg' = 'sm') => {
    const config = RATING_CONFIG[rating] || RATING_CONFIG['U']
    const Icon = config.icon

    if (size === 'lg') {
      return (
        <div className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg ${config.bgColor} border-2 ${config.borderColor}`}>
          <Icon className={`h-5 w-5 ${config.color}`} />
            <div>
              <div className={`text-2xl font-bold ${config.color}`}>{rating}</div>
              <div className={`text-xs ${config.color} opacity-75`}>
                {t(`ratings.${rating}.label`, { defaultValue: config.label })}
              </div>
            </div>
          </div>
        )
    }

    return (
      <Badge variant="outline" className={`${config.bgColor} ${config.borderColor} ${config.color} border-2`}>
        <Icon className="h-3 w-3 mr-1" />
        {rating}
      </Badge>
    )
  }

  return (
    <div className="min-h-full p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <Brain className="h-6 w-6 text-primary" />
            <h1 className="text-2xl font-serif font-bold flex items-center gap-3">
              {t('title', { defaultValue: 'Knowledge Twins' })}
              <PageHelp content={helpContent.knowledgeTwins} />
            </h1>
          </div>
          <p className="text-sm text-muted-foreground">
            {t('description', {
              defaultValue: 'Evidence-based O2/H2 material compatibility using NASA Body of Knowledge',
            })}
          </p>
        </div>
      </div>

      <div className="space-y-6">

        {/* Fluid Type Selector */}
        <Tabs value={activeFluid} onValueChange={(v) => setActiveFluid(v as 'oxygen' | 'hydrogen')}>
          <TabsList className="grid w-full max-w-md grid-cols-2">
            <TabsTrigger value="oxygen">
              <Droplet className="h-4 w-4 mr-2" />
              {t('fluidTypes.oxygen', { defaultValue: 'Oxygen (O2)' })}
            </TabsTrigger>
            <TabsTrigger value="hydrogen">
              <Flame className="h-4 w-4 mr-2" />
              {t('fluidTypes.hydrogen', { defaultValue: 'Hydrogen (H2)' })}
            </TabsTrigger>
          </TabsList>
        </Tabs>

        {/* Mode Toggle */}
        <div className="flex gap-2 items-center">
          <Button
            variant={mode === 'browse' ? 'default' : 'outline'}
            onClick={() => setMode('browse')}
            size="sm"
          >
            {t('modes.browse', { defaultValue: 'Browse Materials' })}
          </Button>
          <Button
            variant={mode === 'ask' ? 'default' : 'outline'}
            onClick={() => setMode('ask')}
            size="sm"
          >
            {t('modes.ask', { defaultValue: 'Ask Question' })}
          </Button>

          {/* LLM Provider Toggle (only in Ask mode) */}
          {mode === 'ask' && (
            <div className="ml-4 flex items-center gap-2 text-sm">
              <span className="text-muted-foreground">
                {t('llm.label', { defaultValue: 'LLM:' })}
              </span>
              <Button
                variant={llmProvider === 'ollama' ? 'default' : 'outline'}
                onClick={() => setLlmProvider('ollama')}
                size="sm"
              >
                {t('llm.ollama', { defaultValue: 'Local (Ollama)' })}
              </Button>
              <Button
                variant={llmProvider === 'haiku' ? 'default' : 'outline'}
                onClick={() => setLlmProvider('haiku')}
                size="sm"
              >
                {t('llm.haiku', { defaultValue: 'Claude Haiku' })}
              </Button>
            </div>
          )}
        </div>

        {/* Search Bar */}
        <Card>
          <CardContent className="pt-6">
            <div className="flex gap-4">
              <Input
                placeholder={
                  mode === 'ask'
                    ? t('search.placeholderAsk', {
                        fluid: activeFluid,
                        defaultValue:
                          `Ask a question about ${activeFluid} compatibility (e.g., "Can I use aluminum in ${activeFluid} service?")`,
                      })
                    : t('search.placeholderBrowse', {
                        fluid: activeFluid,
                        defaultValue:
                          `Search ${activeFluid} compatibility (e.g., "materials compatible with ${activeFluid} at 20psi")`,
                      })
                }
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && (mode === 'browse' ? handleSearch() : handleAsk())}
              />
              <Button
                onClick={mode === 'browse' ? handleSearch : handleAsk}
                disabled={loading || !query.trim()}
              >
                {loading ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    {mode === 'ask'
                      ? t('search.thinking', { defaultValue: 'Thinking...' })
                      : t('search.searching', { defaultValue: 'Searching...' })}
                  </>
                ) : (
                  <>
                    <Search className="h-4 w-4 mr-2" />
                    {mode === 'ask'
                      ? t('search.buttonAsk', { defaultValue: 'Ask' })
                      : t('search.buttonSearch', { defaultValue: 'Search' })}
                  </>
                )}
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Error Message */}
        {error && (
          <Card className="border-2 border-red-500">
            <CardContent className="pt-6">
                <div className="flex items-center gap-3 text-red-600">
                  <XCircle className="h-6 w-6" />
                  <div>
                    <div className="font-bold">
                      {mode === 'ask'
                        ? t('errors.questionError', { defaultValue: 'Question Error' })
                        : t('errors.searchError', { defaultValue: 'Search Error' })}
                    </div>
                    <div className="text-sm">{error}</div>
                  </div>
                </div>
            </CardContent>
          </Card>
        )}

        {/* Ask Mode - Hybrid Query Results */}
        {mode === 'ask' && !loading && hybridResponse && (
          <div className="space-y-6">
            {/* Deterministic Decision Card - MOST IMPORTANT */}
            {hybridResponse.deterministic_decision && (
              <Card className={`border-2 ${
                hybridResponse.deterministic_decision === 'YES' ? 'border-green-500 bg-green-50' :
                hybridResponse.deterministic_decision === 'NO' ? 'border-red-500 bg-red-50' :
                'border-yellow-500 bg-yellow-50'
              }`}>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    {hybridResponse.deterministic_decision === 'YES' ? (
                      <CheckCircle2 className="h-5 w-5 text-green-600" />
                    ) : hybridResponse.deterministic_decision === 'NO' ? (
                      <XCircle className="h-5 w-5 text-red-600" />
                    ) : (
                      <AlertTriangle className="h-5 w-5 text-yellow-600" />
                    )}
                    {t('hybridResults.decision', { defaultValue: 'Decision' })}: {hybridResponse.deterministic_decision}
                    <Badge variant="outline" className="ml-2">{hybridResponse.decision_source}</Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-sm">{hybridResponse.decision_rationale}</p>
                </CardContent>
              </Card>
            )}

            {/* LLM Explanation */}
            {(hybridResponse.answer || hybridResponse.explanation) && (
              <Card className="border-2 border-blue-500 bg-blue-50">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Sparkles className="h-5 w-5 text-blue-600" />
                    {t('hybridResults.miraAnalysis', { defaultValue: 'MIRA Analysis' })}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="prose prose-sm max-w-none whitespace-pre-wrap font-mono text-sm bg-white p-4 rounded border border-blue-200">
                    {hybridResponse.answer || hybridResponse.explanation}
                  </div>
                  {hybridResponse.constraints && (
                    <div className="mt-4 pt-4 border-t border-blue-200">
                      <p className="text-xs text-muted-foreground font-semibold mb-2">
                        {t('hybridResults.extractedConstraints', { defaultValue: 'Extracted Constraints:' })}
                      </p>
                      <pre className="text-xs bg-white p-3 rounded border border-blue-200 overflow-x-auto">
                        {JSON.stringify(hybridResponse.constraints, null, 2)}
                      </pre>
                    </div>
                  )}
                </CardContent>
              </Card>
            )}

            {/* Evidence Summary Card */}
            <Card className="border-2 border-blue-500">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <HelpCircle className="h-5 w-5 text-blue-600" />
                  {t('hybridResults.evidenceSummary', { defaultValue: 'Evidence Summary' })}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                  <div className="text-center">
                    <div className="text-2xl font-bold text-blue-600">
                      {hybridResponse.evidence_summary.mua_precedents_found}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {t('hybridResults.muaPrecedents', { defaultValue: 'MUA Precedents' })}
                    </div>
                  </div>
                  <div className="text-center">
                    <div className="text-2xl font-bold text-green-600">
                      {hybridResponse.evidence_summary.test_results_found}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {t('hybridResults.testResults', { defaultValue: 'Test Results' })}
                    </div>
                  </div>
                  <div className="text-center">
                    <div className="text-2xl font-bold text-purple-600">
                      {hybridResponse.evidence_summary.requirements_evaluated}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {t('hybridResults.requirements', { defaultValue: 'Requirements' })}
                    </div>
                  </div>
                  <div className="text-center">
                    <div className="text-2xl font-bold text-orange-600">
                      {hybridResponse.evidence_summary.semantic_results_found}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {t('hybridResults.semanticResults', { defaultValue: 'Semantic Results' })}
                    </div>
                  </div>
                  <div className="text-center">
                    <div className="text-2xl font-bold text-indigo-600">
                      {hybridResponse.evidence_summary.high_confidence_semantic}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {t('hybridResults.highConfidence', { defaultValue: 'High Confidence' })}
                    </div>
                  </div>
                </div>
                {hybridResponse.insufficient_data && (
                  <div className="mt-4 p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
                    <div className="flex items-center gap-2 text-yellow-800">
                      <AlertTriangle className="h-4 w-4" />
                      <span className="text-sm font-semibold">
                        {t('hybridResults.insufficientData', { defaultValue: 'Insufficient Data' })}
                      </span>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Decisions */}
            {hybridResponse.decisions && hybridResponse.decisions.length > 0 && (
              <Card className="border-2 border-green-500">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <CheckCircle2 className="h-5 w-5 text-green-600" />
                    {t('hybridResults.materialDecisions', { defaultValue: 'Material Compatibility Decisions' })}
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {hybridResponse.decisions.map((decision, idx) => (
                    <Card key={idx} className="border-l-4 border-l-green-500">
                      <CardContent className="pt-4">
                        <div className="flex items-start justify-between mb-2">
                          <h4 className="font-bold text-lg">{decision.decision}</h4>
                          <Badge variant="outline">{decision.confidence}</Badge>
                        </div>
                        <p className="text-sm text-gray-700 mb-3">{decision.reasoning}</p>
                        {decision.citations && decision.citations.length > 0 && (
                          <div className="text-xs text-muted-foreground">
                            <span className="font-semibold">
                              {t('hybridResults.citations', { defaultValue: 'Citations:' })}{" "}
                            </span>
                            {decision.citations.join(', ')}
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  ))}
                </CardContent>
              </Card>
            )}

            {/* Semantic Evidence */}
            {hybridResponse.semantic_evidence?.results && hybridResponse.semantic_evidence.results.length > 0 && (
              <Card className="border-2 border-orange-500">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <span>{t('hybridResults.semanticSearchResults', { defaultValue: 'Semantic Search Results' })}</span>
                    <Badge variant="secondary">{hybridResponse.semantic_evidence.total_results}</Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  {hybridResponse.semantic_evidence.results.slice(0, 10).map((result, idx) => (
                    <Card key={idx} className="border-l-4 border-l-orange-500">
                      <CardContent className="pt-4">
                        <div className="flex justify-between items-start mb-2">
                          <Badge variant="outline" className="font-mono text-xs">
                            {result.source}
                          </Badge>
                          <Badge variant="secondary">
                            {(result.score * 100).toFixed(0)}% {t('hybridResults.match', { defaultValue: 'match' })}
                          </Badge>
                        </div>
                        <p className="text-sm text-gray-700 leading-relaxed">{result.text}</p>
                      </CardContent>
                    </Card>
                  ))}
                </CardContent>
              </Card>
            )}
          </div>
        )}

        {/* Browse Mode - Results */}
        {mode === 'browse' && !loading && (materials.length > 0 || bokResults.length > 0) && (
          <div className="space-y-8">

            {/* SECTION 1: RECOMMENDED MATERIALS */}
            {materials.length > 0 && (
              <div className="space-y-4">
                <div>
                  <h2 className="text-xl font-bold mb-1">
                    {t('results.recommendedMaterials', { defaultValue: 'Recommended Materials' })}
                  </h2>
                  <p className="text-sm text-muted-foreground">
                    {t('results.materialsDescription', {
                      fluid: activeFluid,
                      defaultValue: `Materials with ${activeFluid} compatibility ratings from MAPTIS database`,
                    })}
                  </p>
                </div>

                {sortedRatings.map((rating) => {
                  const config = RATING_CONFIG[rating]
                  const materialsInRating = groupedMaterials[rating]
                  const Icon = config.icon

                  return (
                    <Card key={rating} className={`border-2 ${config.borderColor}`}>
                      <CardHeader className={config.bgColor}>
                        <CardTitle className="flex items-center gap-3">
                          <Icon className={`h-5 w-5 ${config.color}`} />
                          <div>
                            <div className="text-lg font-bold">
                              {t(`ratings.${rating}.label`, {
                                defaultValue: config.label,
                              })}{" "}
                              (Rating {rating})
                            </div>
                            <div className={`text-xs font-normal ${config.color} opacity-75`}>
                              {t(`ratings.${rating}.description`, {
                                defaultValue: config.description,
                              })}{" "}
                              - {materialsInRating.length}{" "}
                              {materialsInRating.length === 1
                                ? t('labels.material', { defaultValue: 'material' })
                                : t('labels.materials', { defaultValue: 'materials' })}
                            </div>
                          </div>
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="pt-6">
                        <div className="grid gap-4">
                          {materialsInRating.map((material, idx) => (
                            <Card key={idx} className="border hover:border-primary/50 transition-colors">
                              <CardContent className="pt-6">
                                <div className="flex items-start justify-between gap-4">
                                  <div className="flex-1">
                                    <h3 className="text-base font-bold mb-2">
                                      {material.material_designation || material.material_name || material.material_key}
                                    </h3>

                                    {/* Rating Grid */}
                                    <div className="grid grid-cols-4 gap-3 mb-3">
                                      {material.flamm_rating && material.flamm_rating !== 'No data' && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">
                                            {t('ratingLabels.FLAMM', { defaultValue: 'FLAMM' })}
                                          </div>
                                          {getRatingBadge(material.flamm_rating)}
                                        </div>
                                      )}
                                      {material.corr_rating && material.corr_rating !== 'No data' && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">
                                            {t('ratingLabels.CORR', { defaultValue: 'CORR' })}
                                          </div>
                                          {getRatingBadge(material.corr_rating)}
                                        </div>
                                      )}
                                      {material.scc_rating && material.scc_rating !== 'No data' && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">
                                            {t('ratingLabels.SCC', { defaultValue: 'SCC' })}
                                          </div>
                                          {getRatingBadge(material.scc_rating)}
                                        </div>
                                      )}
                                      {material.tvs_rating && material.tvs_rating !== 'No data' && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">
                                            {t('ratingLabels.TVS', { defaultValue: 'TVS' })}
                                          </div>
                                          {getRatingBadge(material.tvs_rating)}
                                        </div>
                                      )}
                                    </div>

                                    {material.snippet && (
                                      <p className="text-sm text-muted-foreground line-clamp-2">
                                        {material.snippet}
                                      </p>
                                    )}
                                  </div>

                                  <div className="flex-shrink-0">
                                    {getRatingBadge(rating, 'lg')}
                                  </div>
                                </div>
                              </CardContent>
                            </Card>
                          ))}
                        </div>
                      </CardContent>
                    </Card>
                  )
                })}
              </div>
            )}

            {/* SECTION 2: STANDARDS GUIDANCE */}
            {bokResults.length > 0 && (
              <div className="space-y-4">
                <div>
                  <h2 className="text-xl font-bold mb-1">
                    {t('results.standardsGuidance', { defaultValue: 'Standards Guidance' })}
                  </h2>
                  <p className="text-sm text-muted-foreground">
                    {t('results.standardsDescription', {
                      fluid: activeFluid.toUpperCase(),
                      defaultValue: `Supporting documentation from NASA ${activeFluid.toUpperCase()} Body of Knowledge`,
                    })}
                  </p>
                </div>

                <div className="grid gap-4">
                  {bokResults.map((result, idx) => (
                    <Card key={idx} className="border hover:border-primary/50 transition-colors">
                      <CardHeader>
                        <CardTitle className="flex items-start justify-between">
                          <div className="flex-1">
                            <div className="text-base font-bold mb-1">
                              {result.source} {result.section && `${result.section}`}
                            </div>
                            <div className="text-xs font-normal text-muted-foreground">
                              {result.tags.join(' - ')}
                              {result.page && ` - Page ${result.page}`}
                            </div>
                          </div>
                          <Badge variant="outline" className="ml-4">
                            {t('score', { defaultValue: 'Score' })}: {(result.relevance_score * 100).toFixed(0)}%
                          </Badge>
                        </CardTitle>
                      </CardHeader>
                      <CardContent>
                        <p className="text-sm text-muted-foreground">
                          {result.text || t('results.noContent', { defaultValue: 'No content available' })}
                        </p>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              </div>
            )}

          </div>
        )}

        {/* Empty State */}
        {!loading && materials.length === 0 && bokResults.length === 0 && !hybridResponse && query && (
          <Card>
            <CardContent className="pt-8 pb-8 text-center">
              <Search className="h-12 w-12 mx-auto mb-3 text-muted-foreground opacity-50" />
              <h3 className="text-lg font-bold mb-1">
                {t('results.noResults', { defaultValue: 'No results found' })}
              </h3>
              <p className="text-sm text-muted-foreground">
                {t('results.noResultsHint', {
                  defaultValue: 'Try adjusting your search query or switching fluids',
                })}
              </p>
            </CardContent>
          </Card>
        )}

      </div>
    </div>
  )
}
