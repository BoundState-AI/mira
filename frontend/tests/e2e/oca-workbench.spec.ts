import { expect, test, type Page, type Route } from '@playwright/test';

type WorkbenchRequirement = {
  requirement_id: string;
  title: string;
  citation: string;
  tier: string;
  triggered: boolean;
  status: string;
  reasoning: string;
  downstream_actions: string[];
  evidence_links: string[];
};

type WorkbenchBlockedState = {
  code: string;
  detail: string;
  resolution_hint: string;
  severity?: string;
};

type WorkbenchMockOptions = {
  authorityError?: string;
  createCaseError?: string;
  exportError?: string;
  requirements?: WorkbenchRequirement[];
  createBlockedStates?: WorkbenchBlockedState[];
  precheckBlockedStates?: WorkbenchBlockedState[];
  evidence?: Array<Record<string, unknown>>;
  mechanisms?: Array<Record<string, unknown>>;
  decision?: Partial<Record<string, unknown>>;
};

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

function buildDefaultRequirements(): WorkbenchRequirement[] {
  return [
    {
      requirement_id: 'MPR_51',
      title: 'Screen worst-case service envelope',
      citation: 'NASA-STD-6001B',
      tier: 'tier_a',
      triggered: true,
      status: 'satisfied',
      reasoning: 'Service envelope was fully defined.',
      downstream_actions: [],
      evidence_links: [],
    },
    {
      requirement_id: 'MPR_52',
      title: 'Escalate flammable material behavior',
      citation: 'NASA-STD-6016C',
      tier: 'tier_a',
      triggered: true,
      status: 'action_required',
      reasoning: 'Polymeric seat material requires formal rationale.',
      downstream_actions: ['Generate MUA seed'],
      evidence_links: [],
    },
    {
      requirement_id: 'MPR_53',
      title: 'Acceptance test above 265 psia',
      citation: 'NASA-STD-6001B',
      tier: 'tier_a',
      triggered: false,
      status: 'not_triggered',
      reasoning: 'Component flagged as exempt in this mock scenario.',
      downstream_actions: [],
      evidence_links: [],
    },
    {
      requirement_id: 'MPR_67',
      title: 'Titanium prohibition',
      citation: 'NASA-STD-6016C',
      tier: 'tier_a',
      triggered: false,
      status: 'not_triggered',
      reasoning: 'No titanium alloys were present.',
      downstream_actions: [],
      evidence_links: [],
    },
  ];
}

function buildDefaultEvidence() {
  return [
    {
      evidence_id: 'ev-1',
      material_name: 'PTFE',
      source_id: 'src-ptfe',
      title: 'PTFE GOX ignition threshold',
      citation: 'NASA TM mock-1',
      tier: 'tier_b',
      summary: 'Direct GOX evidence for PTFE seats at comparable pressure.',
      test_method: 'ASTM G74',
      specimen_description: 'Seat coupon',
      test_conditions: 'GOX / ambient',
      result: 'No ignition below threshold',
      applicability: {
        exact_material_match: true,
        spec_match: true,
        form_match: true,
        geometry_match: true,
        pressure_match: true,
        o2_fraction_match: true,
        phase_match: true,
        temperature_match: true,
        coating_match: true,
        method_relevance: true,
        aggregate_score: 0.96,
        applicability_class: 'DIRECT',
      },
      gaps: [],
    },
  ];
}

function buildDefaultMechanisms() {
  return [
    {
      mechanism_name: 'particle_impact',
      credible_status: 'CREDIBLE',
      rating: 3,
      source_ref: 'TM-PI',
      required_elements: ['particles', 'velocity'],
      observed_elements: ['particles', 'velocity'],
      missing_elements: [],
      linked_evidence_ids: ['ev-1'],
      gaps_identified: [],
      mechanism_trace: {
        mechanism_name: 'particle_impact',
        source_ref: 'TM-PI',
        required_elements: ['particles', 'velocity'],
        observed_elements: ['particles', 'velocity'],
        missing_elements: [],
        rating_formula_version: 'mock-1',
        rating_result: 3,
        reviewer_comments: [],
      },
    },
    {
      mechanism_name: 'rapid_pressurization',
      credible_status: 'INDETERMINATE',
      rating: 2,
      source_ref: 'TM-RP',
      required_elements: ['dead_volume'],
      observed_elements: ['dead_volume'],
      missing_elements: [],
      linked_evidence_ids: [],
      gaps_identified: ['Need valve-open time confirmation.'],
      mechanism_trace: {
        mechanism_name: 'rapid_pressurization',
        source_ref: 'TM-RP',
        required_elements: ['dead_volume'],
        observed_elements: ['dead_volume'],
        missing_elements: [],
        rating_formula_version: 'mock-1',
        rating_result: 2,
        reviewer_comments: [],
      },
    },
  ];
}

async function fulfillError(route: Route, status: number, detail: string) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify({ detail }),
  });
}

async function mockOcaWorkbenchApi(page: Page, options: WorkbenchMockOptions = {}) {
  const requirements = options.requirements ?? buildDefaultRequirements();
  const precheckBlockedStates = options.precheckBlockedStates ?? [];
  const createBlockedStates = options.createBlockedStates ?? precheckBlockedStates;
  const evidence = options.evidence ?? buildDefaultEvidence();
  const mechanisms = options.mechanisms ?? buildDefaultMechanisms();
  const defaultDecision = {
    case_id: 'oca-001',
    final_disposition: 'requires_mua',
    triggered_requirements: requirements,
    blocked_states: precheckBlockedStates,
    unresolved_gaps: ['Need valve-open time confirmation.'],
    kindling_chain_present: true,
    reaction_effect: 'C',
    history_of_use: 'screening_only',
    mua_seed: { materials: ['PTFE', '316L'] },
    acceptance_test_required: false,
    reviewer_required: true,
    overall_confidence: 'medium',
    authority_level: 'tier_a',
    governing_prohibition: null,
    summary_rationale: 'Tier A requirements passed, but polymer seat evidence still routes the case to MUA.',
    actions: [
      {
        action_id: 'generate_mua_seed',
        label: 'Generate MUA seed',
        rationale: 'Formal rationale is required before closure.',
      },
    ],
  };

  await page.route(/\/api\/oca(?:\/.*)?$/, async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;

    if (path.endsWith('/api/oca/authority')) {
      if (options.authorityError) {
        await fulfillError(route, 500, options.authorityError);
        return;
      }
      await fulfillJson(route, {
        spec_id: 'BS-SPEC-OCA-001-REV1',
        approved_on: '2026-03-09',
        sources: [
          {
            source_id: 'src-1',
            title: 'NASA-STD-6001B',
            edition: 'Rev B',
            change_number: null,
            publication_date: '2016-01-01',
            checksum: 'abc123',
            ingest_date: '2026-03-09',
          },
          {
            source_id: 'src-2',
            title: 'NASA-STD-6016C',
            edition: 'Rev C',
            change_number: null,
            publication_date: '2018-01-01',
            checksum: 'def456',
            ingest_date: '2026-03-09',
          },
        ],
      });
      return;
    }

    if (path.endsWith('/api/oca/cases')) {
      if (options.createCaseError) {
        await fulfillError(route, 500, options.createCaseError);
        return;
      }
      await fulfillJson(route, {
        case_id: 'oca-001',
        revision: 1,
        normalized_input: {
          service_context: {
            oxidizer_type: 'gox',
            o2_fraction: 1.0,
            total_pressure_min_psia: 14.7,
            total_pressure_max_psia: 500.0,
            phase: 'gas',
          },
          materials: [{ material_name: '316L', canonical_name: '316L', family: 'stainless' }],
          components: [{ component_id: 'cmp-1', component_class: 'valve', geometry_class: 'bulk', design_function: 'pressure control' }],
          ignition_context: {},
        },
        blocked_states: createBlockedStates,
        precheck_warnings: [],
      });
      return;
    }

    if (path.endsWith('/precheck')) {
      await fulfillJson(route, {
        case_id: 'oca-001',
        revision: 1,
        blocked_states: precheckBlockedStates,
        triggered_requirements: requirements,
        precheck_warnings: [],
      });
      return;
    }

    if (path.endsWith('/evidence')) {
      await fulfillJson(route, {
        case_id: 'oca-001',
        revision: 1,
        evidence,
        gaps: Array.from(new Set(evidence.flatMap((item) => ((item.gaps as string[] | undefined) ?? [])))),
      });
      return;
    }

    if (path.endsWith('/mechanisms')) {
      await fulfillJson(route, {
        case_id: 'oca-001',
        revision: 1,
        mechanisms,
      });
      return;
    }

    if (path.endsWith('/decision')) {
      await fulfillJson(route, {
        case_id: 'oca-001',
        revision: 1,
        decision: {
          ...defaultDecision,
          ...options.decision,
          triggered_requirements: requirements,
          blocked_states: options.decision?.blocked_states ?? precheckBlockedStates,
        },
      });
      return;
    }

    if (path.endsWith('/requirements')) {
      await fulfillJson(route, {
        case_id: 'oca-001',
        revision: 1,
        requirements,
      });
      return;
    }

    if (path.endsWith('/lineage')) {
      await fulfillJson(route, {
        case_id: 'oca-001',
        revision: 1,
        revisions: [{ revision: 1, created_at: '2026-03-10T12:00:00Z', note: 'Initial mock case' }],
        decision_lineage: [
          {
            stage: 'precheck',
            rule_id: 'MPR_52',
            tier: 'tier_a',
            outcome: 'action_required',
            detail: 'Polymeric seat requires formal routing.',
            recorded_at: '2026-03-10T12:00:00Z',
          },
          {
            stage: 'decision',
            rule_id: 'final_disposition',
            tier: 'tier_a',
            outcome: 'requires_mua',
            detail: 'Escalate to MUA after screening.',
            recorded_at: '2026-03-10T12:00:01Z',
          },
        ],
      });
      return;
    }

    if (path.endsWith('/export')) {
      if (options.exportError) {
        await fulfillError(route, 500, options.exportError);
        return;
      }
      await fulfillJson(route, {
        case_id: 'oca-001',
        revision: 1,
        artifacts: [
          {
            artifact_type: 'decision_summary',
            filename: 'oca-001-summary.txt',
            content_type: 'text/plain',
            generated_text: 'Decision summary',
          },
          {
            artifact_type: 'lineage',
            filename: 'oca-001-lineage.json',
            content_type: 'application/json',
            generated_text: '{"lineage": true}',
          },
        ],
      });
      return;
    }

    await route.abort();
  });
}

test('oca workbench runs a full mocked case and downloads an artifact', async ({ page }) => {
  await mockOcaWorkbenchApi(page);

  await page.goto('/oca');

  await expect(page.getByRole('heading', { name: 'OCA Workbench' })).toBeVisible();
  await expect(page.getByText('Assessment Input')).toBeVisible();
  await expect(page.getByText('Adiabatic Compression Check')).toBeVisible();

  await page.getByLabel('Material Name').fill('PTFE');
  await page.getByRole('button', { name: 'Run OCA Case' }).click();

  await expect(page.getByText('Case Summary')).toBeVisible();
  await expect(page.getByText('Requires MUA')).toBeVisible();
  await expect(page.getByText('Requirement Backbone')).toBeVisible();
  await expect(page.getByText('Evidence Applicability')).toBeVisible();
  await expect(page.getByText('Ignition Mechanisms')).toBeVisible();
  await expect(page.getByText('Decision Lineage')).toBeVisible();
  await expect(page.getByText('Authority Pack')).toBeVisible();
  await expect(page.getByText('Generate MUA seed').first()).toBeVisible();
  await expect(page.getByText('PTFE GOX ignition threshold')).toBeVisible();

  await page.getByRole('button', { name: 'Generate Export Pack' }).click();
  await expect(page.getByText('oca-001-summary.txt')).toBeVisible();

  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download' }).first().click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('oca-001-summary.txt');
});

test('oca workbench surfaces blocked-state routing and insufficient evidence', async ({ page }) => {
  await mockOcaWorkbenchApi(page, {
    precheckBlockedStates: [
      {
        code: 'SERVICE_ENVELOPE_INCOMPLETE',
        detail: 'Maximum pressure is missing for the assessed envelope.',
        resolution_hint: 'Populate the service envelope before final disposition.',
      },
    ],
    evidence: [],
    mechanisms: [],
    decision: {
      final_disposition: 'insufficient_evidence',
      overall_confidence: 'low',
      unresolved_gaps: ['Maximum pressure is missing for the assessed envelope.'],
      summary_rationale: 'Assessment is partial because required service context is incomplete.',
      actions: [
        {
          action_id: 'resolve_service_envelope',
          label: 'Resolve Service Envelope Incomplete',
          rationale: 'Provide missing pressure and state fields before release.',
        },
      ],
    },
  });

  await page.goto('/oca');
  await page.getByRole('button', { name: 'Run OCA Case' }).click();

  await expect(page.getByText('Blocked States')).toBeVisible();
  await expect(page.getByText('SERVICE ENVELOPE INCOMPLETE')).toBeVisible();
  await expect(page.getByText('Maximum pressure is missing for the assessed envelope.')).toBeVisible();
  await expect(page.getByText('Insufficient Evidence')).toBeVisible();
  await expect(page.getByText('Resolve Service Envelope Incomplete')).toBeVisible();
});

test('oca workbench surfaces governing prohibition and authority fallback', async ({ page }) => {
  const prohibitedRequirements = buildDefaultRequirements().map((item) => (
    item.requirement_id === 'MPR_67'
      ? {
          ...item,
          triggered: true,
          status: 'prohibited',
          reasoning: 'Titanium use in GOX violates MPR 67.',
          downstream_actions: ['Replace prohibited material'],
        }
      : item
  ));

  await mockOcaWorkbenchApi(page, {
    authorityError: 'authority unavailable',
    requirements: prohibitedRequirements,
    decision: {
      final_disposition: 'prohibited',
      governing_prohibition: 'MPR 67: Titanium is prohibited in GOX.',
      summary_rationale: 'A governing prohibition was triggered by the entered titanium configuration.',
      actions: [
        {
          action_id: 'replace_prohibited_material',
          label: 'Replace prohibited material',
          rationale: 'Titanium cannot remain in this GOX service envelope.',
        },
      ],
    },
  });

  await page.goto('/oca');
  await page.getByLabel('Material Name').fill('Ti-6Al-4V');
  await page.getByRole('button', { name: 'Run OCA Case' }).click();

  await expect(page.getByText('Prohibited')).toBeVisible();
  await expect(page.getByText('Governing prohibition: MPR 67: Titanium is prohibited in GOX.')).toBeVisible();
  await expect(page.getByText('Replace prohibited material')).toBeVisible();
  await expect(page.getByText('Authority manifest unavailable.')).toBeVisible();
});

test('oca workbench surfaces api failures on create and export', async ({ page }) => {
  await mockOcaWorkbenchApi(page, { createCaseError: 'mock create failed' });

  await page.goto('/oca');
  await page.getByRole('button', { name: 'Run OCA Case' }).click();
  await expect(page.getByText('mock create failed')).toBeVisible();

  await page.unroute(/\/api\/oca(?:\/.*)?$/);
  await mockOcaWorkbenchApi(page, { exportError: 'mock export failed' });

  await page.reload();
  await page.getByRole('button', { name: 'Run OCA Case' }).click();
  await expect(page.getByText('Case Summary')).toBeVisible();
  await page.getByRole('button', { name: 'Generate Export Pack' }).click();
  await expect(page.getByText('mock export failed')).toBeVisible();
});
