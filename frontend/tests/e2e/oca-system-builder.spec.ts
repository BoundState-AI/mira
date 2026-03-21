import { expect, test, type Page, type Route } from '@playwright/test';

type MockMaterial = {
  slot_name: string;
  material: {
    material_name: string;
    spec?: string | null;
    identity_confidence?: number;
    flammability_rating?: string;
    is_titanium?: boolean;
    is_nonmetal?: boolean;
  };
};

type MockComponent = {
  component_id: string;
  archetype: string;
  label: string;
  position_x: number;
  position_y: number;
  materials: MockMaterial[];
  config: Record<string, unknown>;
  features: Record<string, unknown>;
  inferred_facts: Array<Record<string, unknown>>;
  zones: string[];
  mechanism_assessments: Array<Record<string, unknown>>;
  overall_status: 'green' | 'yellow' | 'red' | 'pending';
  highest_rating: number;
  credible_mechanisms: string[];
  connected: boolean;
  is_rigid_metallic_tubing?: boolean;
  is_metallic_flex_hose?: boolean;
  is_all_metal_seal?: boolean;
  is_metallic_pressure_vessel?: boolean;
};

type MockConnection = {
  connection_id: string;
  source_component_id: string;
  target_component_id: string;
};

type BuilderAssessmentMode = 'standard' | 'blocked_mpr67';

type BuilderMockOptions = {
  assessmentMode?: BuilderAssessmentMode;
  failOn?: Partial<Record<'createSystem' | 'updateInputs' | 'addComponent' | 'addConnection' | 'assess' | 'export', string>>;
};

function baseFeatures() {
  return {
    has_moving_contact: false,
    has_polymer_seal: false,
    has_dead_volume: false,
    creates_particles: false,
    has_cavity_downstream: false,
    wetted_surface_flag: true,
    porous_media_flag: false,
    electrical_energy_present: false,
    dynamic_contact_flag: false,
    contamination_trap_flag: false,
    filter_integrity_assumed: false,
    metal_pair_contact: false,
    reactive_metal_present: false,
    seat_contact_mode: null,
    sa_to_volume_ratio: 'low',
  };
}

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    headers: {
      'access-control-allow-origin': '*',
      'access-control-allow-methods': 'GET,POST,PUT,DELETE,OPTIONS',
      'access-control-allow-headers': 'Content-Type',
    },
    body: JSON.stringify(body),
  });
}

async function fulfillError(route: Route, status: number, detail: string) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    headers: {
      'access-control-allow-origin': '*',
      'access-control-allow-methods': 'GET,POST,PUT,DELETE,OPTIONS',
      'access-control-allow-headers': 'Content-Type',
    },
    body: JSON.stringify({ detail }),
  });
}

async function installSystemBuilderMock(page: Page, options: BuilderMockOptions = {}) {
  const assessmentMode = options.assessmentMode ?? 'standard';
  const state: {
    createCount: number;
    systemId: string | null;
    inputs: Record<string, unknown>;
    components: MockComponent[];
    connections: MockConnection[];
  } = {
    createCount: 0,
    systemId: null,
    inputs: {},
    components: [],
    connections: [],
  };

  await page.route(/\/oca\/systems(?:\/.*)?$/, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api/, '');

    if (request.method() === 'OPTIONS') {
      await route.fulfill({
        status: 204,
        headers: {
          'access-control-allow-origin': '*',
          'access-control-allow-methods': 'GET,POST,PUT,DELETE,OPTIONS',
          'access-control-allow-headers': 'Content-Type',
        },
      });
      return;
    }

    if (path === '/oca/systems' && request.method() === 'POST') {
      if (options.failOn?.createSystem) {
        await fulfillError(route, 500, options.failOn.createSystem);
        return;
      }
      const body = request.postDataJSON() as { name: string; inputs?: Record<string, unknown> };
      state.createCount += 1;
      const systemOrdinal = Math.floor((state.createCount - 1) / 2) + 1;
      state.systemId = `sys-${systemOrdinal}`;
      if (state.createCount % 2 === 1) {
        state.components = [];
        state.connections = [];
      }
      state.inputs = body.inputs ?? {};
      await fulfillJson(route, { system_id: state.systemId, name: body.name, blocked_states: [] });
      return;
    }

    if (!state.systemId || !path.startsWith(`/oca/systems/${state.systemId}`)) {
      await route.abort();
      return;
    }

    if (path === `/oca/systems/${state.systemId}/inputs` && request.method() === 'PUT') {
      if (options.failOn?.updateInputs) {
        await fulfillError(route, 500, options.failOn.updateInputs);
        return;
      }
      state.inputs = { ...state.inputs, ...(request.postDataJSON() as Record<string, unknown>) };
      await fulfillJson(route, { status: 'updated' });
      return;
    }

    if (path === `/oca/systems/${state.systemId}/components` && request.method() === 'POST') {
      if (options.failOn?.addComponent) {
        await fulfillError(route, 500, options.failOn.addComponent);
        return;
      }
      const body = request.postDataJSON() as {
        archetype: string;
        label: string;
        position_x: number;
        position_y: number;
        materials?: MockMaterial[];
        config?: Record<string, unknown>;
      };
      const existing = state.components.find((item) => (
        item.archetype === body.archetype
        && item.label === (body.label || body.archetype)
        && item.position_x === body.position_x
        && item.position_y === body.position_y
        && JSON.stringify(item.materials) === JSON.stringify(body.materials ?? [])
        && JSON.stringify(item.config) === JSON.stringify(body.config ?? {})
      ));
      if (existing) {
        await fulfillJson(route, {
          component_id: existing.component_id,
          features: existing.features,
          zones: existing.zones,
          inferred_facts: existing.inferred_facts,
        });
        return;
      }
      const component: MockComponent = {
        component_id: `cmp-${state.components.length + 1}`,
        archetype: body.archetype,
        label: body.label || body.archetype,
        position_x: body.position_x,
        position_y: body.position_y,
        materials: body.materials ?? [],
        config: body.config ?? {},
        features: {
          ...baseFeatures(),
          has_polymer_seal: (body.materials ?? []).some((item) => /ptfe/i.test(item.material.material_name)),
        },
        inferred_facts: [],
        zones: [],
        mechanism_assessments: [],
        overall_status: 'pending',
        highest_rating: 0,
        credible_mechanisms: [],
        connected: false,
      };
      state.components.push(component);
      await fulfillJson(route, {
        component_id: component.component_id,
        features: component.features,
        zones: component.zones,
        inferred_facts: component.inferred_facts,
      });
      return;
    }

    const componentMatch = path.match(/\/oca\/systems\/[^/]+\/components\/([^/]+)$/);
    if (componentMatch && request.method() === 'PUT') {
      const component = state.components.find((item) => item.component_id === componentMatch[1]);
      if (!component) {
        await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Not found' }) });
        return;
      }
      const updates = request.postDataJSON() as Partial<MockComponent> & { config?: Record<string, unknown> };
      component.label = updates.label ?? component.label;
      component.materials = updates.materials ?? component.materials;
      component.config = { ...component.config, ...(updates.config ?? {}) };
      component.is_rigid_metallic_tubing = updates.is_rigid_metallic_tubing ?? component.is_rigid_metallic_tubing;
      component.is_metallic_flex_hose = updates.is_metallic_flex_hose ?? component.is_metallic_flex_hose;
      component.is_all_metal_seal = updates.is_all_metal_seal ?? component.is_all_metal_seal;
      component.is_metallic_pressure_vessel = updates.is_metallic_pressure_vessel ?? component.is_metallic_pressure_vessel;
      component.features = {
        ...component.features,
        has_polymer_seal: component.materials.some((item) => /ptfe/i.test(item.material.material_name)),
      };
      await fulfillJson(route, { status: 'updated' });
      return;
    }

    if (componentMatch && request.method() === 'DELETE') {
      state.components = state.components.filter((item) => item.component_id !== componentMatch[1]);
      state.connections = state.connections.filter((item) => (
        item.source_component_id !== componentMatch[1] && item.target_component_id !== componentMatch[1]
      ));
      await fulfillJson(route, { status: 'removed' });
      return;
    }

    if (path === `/oca/systems/${state.systemId}/connections` && request.method() === 'POST') {
      if (options.failOn?.addConnection) {
        await fulfillError(route, 500, options.failOn.addConnection);
        return;
      }
      const body = request.postDataJSON() as { source_component_id: string; target_component_id: string };
      const existing = state.connections.find((item) => (
        item.source_component_id === body.source_component_id
        && item.target_component_id === body.target_component_id
      ));
      if (existing) {
        await fulfillJson(route, {
          connection_id: existing.connection_id,
          topology_changed: true,
          affected_component_ids: [body.source_component_id, body.target_component_id],
        });
        return;
      }
      const connection: MockConnection = {
        connection_id: `conn-${state.connections.length + 1}`,
        source_component_id: body.source_component_id,
        target_component_id: body.target_component_id,
      };
      state.connections.push(connection);
      await fulfillJson(route, {
        connection_id: connection.connection_id,
        topology_changed: true,
        affected_component_ids: [body.source_component_id, body.target_component_id],
      });
      return;
    }

    const connectionMatch = path.match(/\/oca\/systems\/[^/]+\/connections\/([^/]+)$/);
    if (connectionMatch && request.method() === 'DELETE') {
      state.connections = state.connections.filter((item) => item.connection_id !== connectionMatch[1]);
      await fulfillJson(route, { status: 'removed' });
      return;
    }

    if (path === `/oca/systems/${state.systemId}/assess` && request.method() === 'POST') {
      if (options.failOn?.assess) {
        await fulfillError(route, 500, options.failOn.assess);
        return;
      }
      const connectedIds = new Set(state.connections.flatMap((item) => [item.source_component_id, item.target_component_id]));
      const assessedComponents = state.components.map((component, index) => {
        const isPrimaryValve = /valve/i.test(component.label) || component.archetype === 'valve';
        const isLine = component.archetype === 'line';
        const connected = connectedIds.has(component.component_id);
        return {
          ...component,
          connected,
          zones: connected ? (isPrimaryValve ? ['unfiltered', 'acceptance_test'] : ['filtered']) : component.zones,
          overall_status: isPrimaryValve ? 'red' : isLine ? 'yellow' : 'green',
          highest_rating: isPrimaryValve ? 4 : isLine ? 2 : 1,
          credible_mechanisms: isPrimaryValve ? ['PI', 'RP'] : isLine ? ['RS'] : [],
          mechanism_assessments: isPrimaryValve ? [
            {
              mechanism_name: 'particle_impact',
              credible_status: 'credible',
              rating: 4,
              source_ref: 'mock-rule',
              observed_elements: ['particles', 'velocity'],
              missing_elements: [],
              required_elements: ['particles', 'velocity'],
              reviewer_comments: [],
            },
          ] : [],
          inferred_facts: connected ? [{
            fact_id: `fact-${index + 1}`,
            fact_name: 'connected_path',
            value: true,
            source: 'inferred',
            confidence: 'high',
            rule_id: 'TOPO-002',
            missing_assumptions: [],
            explanation: 'Connected to active flow path.',
          }] : [],
        };
      });
      state.components = assessedComponents;
      if (assessmentMode === 'blocked_mpr67') {
        await fulfillJson(route, {
          system_id: state.systemId,
          system_disposition: 'insufficient_evidence',
          system_reaction_effect: 'A',
          components: assessedComponents.map((component) => ({
            ...component,
            overall_status: component.archetype === 'valve' ? 'red' : 'pending',
            highest_rating: component.archetype === 'valve' ? 4 : 0,
            credible_mechanisms: component.archetype === 'valve' ? ['PI'] : [],
          })),
          kindling_chains: [],
          triggered_requirements: [
            {
              requirement_id: 'MPR_67',
              title: 'Titanium prohibition',
              tier: 'tier_a',
              satisfied: false,
              is_prohibition: true,
              prohibition_detail: 'Titanium remains active in GOX service.',
            },
          ],
          blocked_states: [
            {
              state_type: 'HYDRAULIC_STATE_INCOMPLETE',
              description: 'Hydraulic state incomplete for one or more flow paths.',
              missing_fields: ['design_flow_rate_m3_s'],
              resolution_hint: 'Define flow state before closure.',
            },
          ],
          hazard_controls: [],
          has_titanium: true,
          mpr67_active: true,
        });
        return;
      }
      await fulfillJson(route, {
        system_id: state.systemId,
        system_disposition: 'compatible_with_controls',
        system_reaction_effect: 'C',
        components: assessedComponents,
        kindling_chains: [
          {
            chain_id: 'chain-1',
            propagation_path: assessedComponents.slice(0, 2).map((item) => item.component_id),
            materials_in_path: assessedComponents.flatMap((item) => item.materials.map((mat) => mat.material.material_name)),
            chain_broken_at: null,
            break_reason: null,
            longest_continuous_length: 2,
            reaction_effect: 'C',
          },
        ],
        triggered_requirements: [],
        blocked_states: [],
        hazard_controls: [
          {
            component_ref: assessedComponents[0]?.component_id ?? 'cmp-1',
            ignition_hazard: 'particle_impact',
            probability_rating: 4,
            recommendation: 'Filter upstream and slow opening profile.',
            confidence: 'credible',
          },
        ],
        has_titanium: false,
        mpr67_active: false,
      });
      return;
    }

    const pathInspectorMatch = path.match(/\/oca\/systems\/[^/]+\/path\/([^/]+)$/);
    if (pathInspectorMatch && request.method() === 'GET') {
      const component = state.components.find((item) => item.component_id === pathInspectorMatch[1]);
      await fulfillJson(route, {
        component_id: pathInspectorMatch[1],
        upstream_contributors: state.connections
          .filter((item) => item.target_component_id === pathInspectorMatch[1])
          .map((item) => {
            const source = state.components.find((componentItem) => componentItem.component_id === item.source_component_id);
            return {
              component_id: item.source_component_id,
              label: source?.label ?? 'Upstream Component',
              contributions: source?.archetype === 'filter' ? 'Provides particle filtration' : 'Flow path contributor',
            };
          }),
        local_mechanism_triggers: component?.overall_status === 'red'
          ? [
              {
                mechanism: 'particle_impact',
                abbreviation: 'PI',
                status: 'credible',
                rating: '4',
                observed_elements: 'particles, velocity',
              },
            ]
          : [],
        downstream_propagation_risk: state.connections
          .filter((item) => item.source_component_id === pathInspectorMatch[1])
          .map((item) => {
            const downstream = state.components.find((componentItem) => componentItem.component_id === item.target_component_id);
            return `${downstream?.label ?? 'Downstream'}: flammable material — propagation possible`;
          }),
        controls_that_would_change: [
          {
            action: 'Add upstream filter',
            expected_effect: 'Removes unfiltered-particle pathway.',
            mechanism: 'particle_impact',
          },
        ],
      });
      return;
    }

    if (path === `/oca/systems/${state.systemId}/export` && request.method() === 'POST') {
      if (options.failOn?.export) {
        await fulfillError(route, 500, options.failOn.export);
        return;
      }
      await fulfillJson(route, {
        system_id: state.systemId,
        system_name: 'Mock O2 System',
        generated_at: '2026-03-10T12:00:00Z',
        system_oca_report: { total_components: state.components.length },
        component_cards: state.components.map((item) => ({ component_id: item.component_id, label: item.label })),
        kindling_chain_map: [],
        hazard_control_table: [],
        bill_of_materials: [],
        miul_seeds: [],
        acceptance_test_schedule: [],
        audit_trail: [],
      });
      return;
    }

    await route.abort();
  });

  return state;
}

async function seedBuilderDraft(
  page: Page,
  draft: Record<string, unknown>,
) {
  await page.addInitScript((initialDraft) => {
    const key = 'boundstate:oca-system-builder:draft:v1';
    if (window.localStorage.getItem(key)) {
      return;
    }
    window.localStorage.setItem(key, JSON.stringify(initialDraft));
  }, draft);
}

async function dragPaletteItemToCanvas(page: Page, testId: string, offsetX: number, offsetY: number) {
  const canvasBox = await page.getByTestId('oca-system-canvas').boundingBox();
  if (!canvasBox) {
    throw new Error('Canvas bounds unavailable');
  }

  await page.evaluate(({ paletteTestId, clientX, clientY }) => {
    const paletteItem = document.querySelector(`[data-testid="${paletteTestId}"]`);
    const canvas = document.querySelector('[data-testid="oca-system-canvas"]');
    if (!paletteItem || !canvas) {
      throw new Error('Drag source or canvas not found');
    }

    const dataTransfer = new DataTransfer();
    paletteItem.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer }));
    canvas.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer, clientX, clientY }));
    canvas.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer, clientX, clientY }));
  }, {
    paletteTestId: testId,
    clientX: canvasBox.x + offsetX,
    clientY: canvasBox.y + offsetY,
  });
}

async function connectComponents(page: Page, sourceTestId: string, targetTestId: string) {
  await page.evaluate(({ sourceId, targetId }) => {
    const source = document.querySelector(`[data-testid="${sourceId}"]`);
    const target = document.querySelector(`[data-testid="${targetId}"]`);
    if (!(source instanceof Element) || !(target instanceof Element)) {
      throw new Error('Component port handles unavailable');
    }

    const sourceBox = source.getBoundingClientRect();
    const targetBox = target.getBoundingClientRect();
    const sourceX = sourceBox.left + sourceBox.width / 2;
    const sourceY = sourceBox.top + sourceBox.height / 2;
    const targetX = targetBox.left + targetBox.width / 2;
    const targetY = targetBox.top + targetBox.height / 2;
    const steps = 16;

    const mouseEvent = (type: string, x: number, y: number, buttons: number) => new MouseEvent(type, {
      bubbles: true,
      cancelable: true,
      composed: true,
      button: 0,
      buttons,
      clientX: x,
      clientY: y,
      screenX: x,
      screenY: y,
      view: window,
    });

    source.dispatchEvent(mouseEvent('mousedown', sourceX, sourceY, 1));
    for (let step = 1; step <= steps; step += 1) {
      const progress = step / steps;
      const x = sourceX + (targetX - sourceX) * progress;
      const y = sourceY + (targetY - sourceY) * progress;
      document.dispatchEvent(mouseEvent('mousemove', x, y, 1));
    }
    target.dispatchEvent(mouseEvent('mouseup', targetX, targetY, 0));
  }, {
    sourceId: sourceTestId,
    targetId: targetTestId,
  });
}

test('oca system builder supports draft restore, assessment, path inspection, and export', async ({ page }) => {
  const state = await installSystemBuilderMock(page);
  await seedBuilderDraft(page, {
    version: 1,
    saved_at: '2026-03-10T12:00:00.000Z',
    inputs: {
      o2_fraction: 1,
      system_pressure_min_psia: 14.7,
      system_pressure_max_psia: 3000,
      phase: 'gox',
      oxygen_phase: 'gas',
      temp_min_c: null,
      temp_max_c: null,
      design_flow_rate_m3_s: 0.02,
      cleanliness_spec: 'Level 100',
      mission_phase: 'ground_test',
      project_name: '',
      hardware_name: '',
      reviewer_name: '',
      bi_directional_flow_risk: false,
    },
    components: [
      {
        component_id: 'draft-valve',
        archetype: 'valve',
        label: 'Valve',
        position_x: 280,
        position_y: 140,
        materials: [{ slot_name: 'body', material: { material_name: '316L' } }],
        config: {},
      },
      {
        component_id: 'draft-line',
        archetype: 'line',
        label: 'Line / Tube',
        position_x: 600,
        position_y: 340,
        materials: [{ slot_name: 'body', material: { material_name: '316L' } }],
        config: { inner_diameter_mm: 12, length_m: 1.5 },
      },
    ],
    connections: [{ source_component_id: 'draft-valve', target_component_id: 'draft-line' }],
  });

  await page.goto('/oca/system-builder');

  await expect(page.getByRole('heading', { name: 'OCA System Builder' })).toBeVisible();
  await expect(page.getByTestId('oca-system-canvas')).toBeVisible();

  await expect.poll(() => state.components.length).toBe(2);
  await expect.poll(() => state.connections.length).toBe(1);
  await expect(page.getByText(/Restored local draft with 2 components\./)).toBeVisible();
  await expect(page.getByText('Valve').first()).toBeVisible();
  await expect(page.getByText('Line / Tube').first()).toBeVisible();

  await page.getByTestId(`component-node-${state.components[0].component_id}`).click();
  await expect(page.getByText('Component Details')).toBeVisible();

  await page.locator('#component-label').fill('Main Isolation Valve');
  await page.locator('#component-materials').fill('body: 316L\nseat: PTFE');
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await expect(page.getByText('Main Isolation Valve').first()).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByText('Component Details')).toHaveCount(0);

  await expect.poll(async () => page.evaluate(() => {
    const draft = window.localStorage.getItem('boundstate:oca-system-builder:draft:v1');
    if (!draft) return null;
    const parsed = JSON.parse(draft) as { components?: Array<{ archetype: string; label: string }> };
    return parsed.components?.find((item) => item.archetype === 'valve')?.label ?? null;
  })).toBe('Main Isolation Valve');
  await page.reload();

  await expect(page.getByText(/Restored local draft with 2 components\./)).toBeVisible();
  await expect.poll(() => state.components.length).toBe(2);
  await expect(page.getByText('Main Isolation Valve').first()).toBeVisible();

  await page.getByTestId('oca-system-assess').click();
  await expect(page.getByText('Compatible With Controls')).toBeVisible();
  await expect(page.getByText('Kindling Chains (1)')).toBeVisible();
  await expect(page.getByText('Needs reassessment')).toHaveCount(0);

  const assessedValve = state.components.find((item) => item.label === 'Main Isolation Valve');
  if (!assessedValve) {
    throw new Error('Assessed valve missing from mock state');
  }

  await page.getByTestId(`component-inspect-${assessedValve.component_id}`).click();
  await expect(page.getByText('Path Inspector')).toBeVisible();
  await expect(page.getByText('Add upstream filter')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByText('Component Details')).toHaveCount(0);

  const downloadPromise = page.waitForEvent('download');
  await page.getByTestId('oca-system-export').click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toContain('oca-system-');
});

test('oca system builder supports raw palette add, connect, tabs, and reassessment flow', async ({ page }) => {
  const state = await installSystemBuilderMock(page);

  await page.goto('/oca/system-builder');
  await expect(page.getByRole('heading', { name: 'OCA System Builder' })).toBeVisible();

  await dragPaletteItemToCanvas(page, 'palette-valve', 340, 180);
  await dragPaletteItemToCanvas(page, 'palette-line', 620, 330);

  await expect.poll(() => state.components.length).toBe(2);
  const [valve, line] = state.components;
  await expect(page.getByTestId(`component-node-${valve.component_id}`)).toBeVisible();
  await expect(page.getByTestId(`component-node-${line.component_id}`)).toBeVisible();

  await connectComponents(
    page,
    `component-output-${valve.component_id}`,
    `component-input-${line.component_id}`,
  );
  await expect.poll(() => state.connections.length).toBe(1);

  await page.getByTestId('oca-system-assess').click();
  await expect(page.getByText('Compatible With Controls')).toBeVisible();

  await page.getByRole('tab', { name: /Summary/ }).click();
  await expect(page.getByText('Reaction Effect')).toBeVisible();

  await page.getByRole('tab', { name: /Kindling Chains/ }).click();
  await expect(page.getByText(/2 component\(s\) in chain/)).toBeVisible();

  await page.getByRole('tab', { name: /Hazard Controls/ }).click();
  await expect(page.getByText('Filter upstream and slow opening profile.')).toBeVisible();

  await page.getByTestId(`component-node-${valve.component_id}`).click();
  await expect(page.getByText('Component Details')).toBeVisible();
  await page.locator('#component-label').fill('Edited Valve');
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await expect(page.getByText('Edited Valve').first()).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByText('Needs reassessment')).toBeVisible();
});

test('oca system builder restores component property editing from the node sheet', async ({ page }) => {
  const state = await installSystemBuilderMock(page);

  await page.goto('/oca/system-builder');
  await expect(page.getByRole('heading', { name: 'OCA System Builder' })).toBeVisible();

  await dragPaletteItemToCanvas(page, 'palette-line', 420, 220);
  await expect.poll(() => state.components.length).toBe(1);

  const [line] = state.components;
  await page.getByTestId(`component-node-${line.component_id}`).click();
  await expect(page.getByText('Component Details')).toBeVisible();

  await page.locator('#component-label').fill('Main Feed Line');
  await page.locator('#component-materials').fill('body: Inconel 625');
  await page.locator('#wall_thickness_mm').fill('1.8');
  await page.locator('#inner_diameter_mm').fill('9.5');
  await page.getByRole('button', { name: 'Save Changes' }).click();

  await expect(page.getByText('Main Feed Line').first()).toBeVisible();
  await expect.poll(() => state.components[0]?.label ?? null).toBe('Main Feed Line');
  await expect.poll(() => state.components[0]?.materials?.[0]?.material?.material_name ?? null).toBe('Inconel 625');
  await expect.poll(() => state.components[0]?.config?.wall_thickness_mm ?? null).toBe(1.8);
  await expect.poll(() => state.components[0]?.config?.inner_diameter_mm ?? null).toBe(9.5);
});

test('oca system builder surfaces blocked states and MPR67 banner', async ({ page }) => {
  const state = await installSystemBuilderMock(page, { assessmentMode: 'blocked_mpr67' });
  await seedBuilderDraft(page, {
    version: 1,
    saved_at: '2026-03-10T12:00:00.000Z',
    inputs: {
      o2_fraction: 1,
      system_pressure_min_psia: 14.7,
      system_pressure_max_psia: 3000,
      phase: 'gox',
      oxygen_phase: 'gas',
      temp_min_c: null,
      temp_max_c: null,
      design_flow_rate_m3_s: null,
      cleanliness_spec: 'Level 100',
      mission_phase: 'ground_test',
      project_name: '',
      hardware_name: '',
      reviewer_name: '',
      bi_directional_flow_risk: false,
    },
    components: [
      {
        component_id: 'draft-valve',
        archetype: 'valve',
        label: 'Titanium Valve',
        position_x: 320,
        position_y: 160,
        materials: [{ slot_name: 'body', material: { material_name: 'Ti-6Al-4V' } }],
        config: {},
      },
    ],
    connections: [],
  });

  await page.goto('/oca/system-builder');
  await expect.poll(() => state.components.length).toBe(1);
  await page.getByTestId('oca-system-assess').click();

  await expect(page.getByText(/MPR 67 GOVERNING PROHIBITION/i)).toBeVisible();
  await expect(page.getByText('Blocked States')).toBeVisible();
  await expect(page.getByText('HYDRAULIC STATE INCOMPLETE')).toBeVisible();
  await expect(page.getByText('Hydraulic state incomplete for one or more flow paths.')).toBeVisible();
  await expect(page.getByText('Insufficient Evidence')).toBeVisible();
});

test('oca system builder surfaces palette add failures', async ({ page }) => {
  await installSystemBuilderMock(page, { failOn: { addComponent: 'mock add component failed' } });

  await page.goto('/oca/system-builder');
  await dragPaletteItemToCanvas(page, 'palette-valve', 320, 220);
  await expect(page.getByText('mock add component failed')).toBeVisible();
});

test('oca system builder surfaces assessment failures', async ({ page }) => {
  const state = await installSystemBuilderMock(page, { failOn: { assess: 'mock assessment failed' } });
  await seedBuilderDraft(page, {
    version: 1,
    saved_at: '2026-03-10T12:00:00.000Z',
    inputs: {
      o2_fraction: 1,
      system_pressure_min_psia: 14.7,
      system_pressure_max_psia: 3000,
      phase: 'gox',
      oxygen_phase: 'gas',
      temp_min_c: null,
      temp_max_c: null,
      design_flow_rate_m3_s: 0.01,
      cleanliness_spec: 'Level 100',
      mission_phase: 'ground_test',
      project_name: '',
      hardware_name: '',
      reviewer_name: '',
      bi_directional_flow_risk: false,
    },
    components: [
      {
        component_id: 'draft-valve',
        archetype: 'valve',
        label: 'Valve',
        position_x: 280,
        position_y: 140,
        materials: [{ slot_name: 'body', material: { material_name: '316L' } }],
        config: {},
      },
    ],
    connections: [],
  });

  await page.goto('/oca/system-builder');
  await expect.poll(() => state.components.length).toBe(1);
  await page.getByTestId('oca-system-assess').click();
  await expect(page.getByText('mock assessment failed')).toBeVisible();
});
