#!/usr/bin/env python3
"""
Update MIRA Platform Capability Overview JSC.docx with:
  1. Expanded OCA section (Heading 3 under Gas Compatibility Assessment)
  2. Galvanic Compatibility (new Heading 2 after Gas Compatibility Assessment)
  3. Fracture Assessment (new Heading 2 after Galvanic)
  4. MIRA Chat (new Heading 2 after M&P Plan Generator)
  5. Update stats table: 8 → 12 modules

BoundState AI 2026
"""

import copy
import sys
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

SRC = Path(r"C:\Users\Jnwil\OneDrive\Desktop\boundstate\MIRA Platform Capability Overview JSC.docx")
DST = SRC  # overwrite in place

doc = Document(str(SRC))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_paragraph_index(doc, text_startswith=None, style_name=None, exact=None):
    """Find paragraph index by text prefix and/or style."""
    for i, p in enumerate(doc.paragraphs):
        if exact and p.text.strip() == exact:
            return i
        if text_startswith and p.text.strip().startswith(text_startswith):
            if style_name is None or p.style.name == style_name:
                return i
    return None


def _insert_heading(doc, after_index, text, level=2):
    """Insert a heading paragraph after the given index."""
    ref_para = doc.paragraphs[after_index]
    new_para = copy.deepcopy(ref_para._element)
    # Clear existing content
    for child in list(new_para):
        if child.tag.endswith('}r'):
            new_para.remove(child)
    # Set style
    pPr = new_para.find(qn('w:pPr'))
    if pPr is None:
        pPr = doc.paragraphs[after_index]._element.makeelement(qn('w:pPr'), {})
        new_para.insert(0, pPr)
    pStyle = pPr.find(qn('w:pStyle'))
    if pStyle is None:
        pStyle = pPr.makeelement(qn('w:pStyle'), {})
        pPr.insert(0, pStyle)
    pStyle.set(qn('w:val'), f'Heading{level}')
    # Add run with text
    run_elem = pPr.makeelement(qn('w:r'), {})
    t_elem = run_elem.makeelement(qn('w:t'), {})
    t_elem.text = text
    run_elem.append(t_elem)
    new_para.append(run_elem)
    ref_para._element.addnext(new_para)
    return new_para


def _insert_bullet(doc, after_elem, text):
    """Insert a bullet paragraph (Normal style with bullet char) after an element."""
    new_para = after_elem.makeelement(qn('w:p'), {})
    run_elem = new_para.makeelement(qn('w:r'), {})
    t_elem = run_elem.makeelement(qn('w:t'), {})
    t_elem.text = f"\u2022  {text}"
    t_elem.set(qn('xml:space'), 'preserve')
    run_elem.append(t_elem)
    new_para.append(run_elem)
    after_elem.addnext(new_para)
    return new_para


def _insert_normal(doc, after_elem, text):
    """Insert a normal paragraph after an element."""
    new_para = after_elem.makeelement(qn('w:p'), {})
    run_elem = new_para.makeelement(qn('w:r'), {})
    t_elem = run_elem.makeelement(qn('w:t'), {})
    t_elem.text = text
    t_elem.set(qn('xml:space'), 'preserve')
    run_elem.append(t_elem)
    new_para.append(run_elem)
    after_elem.addnext(new_para)
    return new_para


def _insert_section(doc, after_index, heading, heading_level, intro, bullets):
    """Insert a complete section: heading + intro paragraph + bullet list."""
    # Work backwards from the bottom so addnext inserts in correct order
    ref = doc.paragraphs[after_index]._element

    # Heading
    h_elem = ref.makeelement(qn('w:p'), {})
    pPr = h_elem.makeelement(qn('w:pPr'), {})
    pStyle = pPr.makeelement(qn('w:pStyle'), {})
    pStyle.set(qn('w:val'), f'Heading{heading_level}')
    pPr.append(pStyle)
    h_elem.append(pPr)
    run = h_elem.makeelement(qn('w:r'), {})
    t = run.makeelement(qn('w:t'), {})
    t.text = heading
    run.append(t)
    h_elem.append(run)
    ref.addnext(h_elem)

    # Intro paragraph
    prev = h_elem
    if intro:
        prev = _insert_normal(doc, prev, intro)

    # Bullets
    for b in bullets:
        prev = _insert_bullet(doc, prev, b)

    return prev


# ---------------------------------------------------------------------------
# 1. Expand O2 Compatibility (Heading 3, para 54)
# ---------------------------------------------------------------------------
oca_idx = _find_paragraph_index(doc, text_startswith="Oxygen (O2) Compatibility", style_name="Heading 3")
if oca_idx is None:
    print("ERROR: Could not find 'Oxygen (O2) Compatibility' heading")
    sys.exit(1)

# Find the last bullet under O2 section (para 58)
# Insert additional bullets after the existing ones
oca_last_bullet_idx = oca_idx + 4  # para 58: "Flammability rating lookup..."
last = _insert_bullet(doc, doc.paragraphs[oca_last_bullet_idx]._element,
    "Multi-step OCA case lifecycle: create case \u2192 precheck \u2192 evidence collection \u2192 decision with full audit trail")
last = _insert_bullet(doc, last,
    "Kindling chain analysis and promoted combustion test data cross-referencing")
last = _insert_bullet(doc, last,
    "Automatic MUA requirement detection: CONDITIONAL_PASS triggers MUA generation guidance per NASA-STD-6016C \u00a74.1.6")
last = _insert_bullet(doc, last,
    "Case-driven architecture: each assessment is a referenceable, auditable case with unique ID")

print("  [+] Expanded O2 Compatibility section")


# ---------------------------------------------------------------------------
# 2. Galvanic Compatibility (new Heading 2 after Knowledge Twins)
#    Insert before "Knowledge Twins" heading (para 59)
# ---------------------------------------------------------------------------
# We want it after the gas compat section ends.
# The last O2 bullet we just added is now the anchor.
# Actually, let's find Knowledge Twins and insert before it.
kt_idx = _find_paragraph_index(doc, text_startswith="Knowledge Twins", style_name="Heading 2")
if kt_idx is None:
    print("ERROR: Could not find 'Knowledge Twins' heading")
    sys.exit(1)

# Insert before Knowledge Twins = insert after the paragraph before it
# We need to insert after the last paragraph of the O2/Gas section
# which is now our expanded bullets. Insert just before kt_idx.
insert_before = doc.paragraphs[kt_idx]._element
galvanic_section = []

# Build the section elements and insert before Knowledge Twins
h = insert_before.makeelement(qn('w:p'), {})
pPr = h.makeelement(qn('w:pPr'), {})
pStyle = pPr.makeelement(qn('w:pStyle'), {})
pStyle.set(qn('w:val'), 'Heading2')
pPr.append(pStyle)
h.append(pPr)
run = h.makeelement(qn('w:r'), {})
t = run.makeelement(qn('w:t'), {})
t.text = "Galvanic Compatibility Assessment"
run.append(t)
h.append(run)
insert_before.addprevious(h)

intro = _insert_normal(doc, h,
    "The Galvanic Compatibility engine screens dissimilar metal couples for corrosion risk "
    "using electrochemical potential data and environment-specific severity factors. Engineers "
    "enter two materials and an environment, and MIRA evaluates the galvanic couple against "
    "MIL-STD-889 and NASA-STD-6012 requirements.")
bullets_galvanic = [
    "Electrochemical potential difference (EMF delta) calculation from validated galvanic series data",
    "Environment-specific severity multipliers: seawater, salt fog, humidity, controlled atmosphere",
    "Anode/cathode identification with area ratio correction for accelerated corrosion risk",
    "Interactive mitigation slider: drag toward green to explore protection schemes (coatings, isolation, sealants)",
    "Surface condition and electrical contact modifiers adjust the effective corrosion risk",
    "INCOMPATIBLE / MARGINAL / COMPATIBLE verdicts with standards citations",
]
prev = intro
for b in bullets_galvanic:
    prev = _insert_bullet(doc, prev, b)

print("  [+] Added Galvanic Compatibility Assessment section")


# ---------------------------------------------------------------------------
# 3. Fracture Assessment (new Heading 2 after Galvanic, before Knowledge Twins)
# ---------------------------------------------------------------------------
h_frac = insert_before.makeelement(qn('w:p'), {})
pPr = h_frac.makeelement(qn('w:pPr'), {})
pStyle = pPr.makeelement(qn('w:pStyle'), {})
pStyle.set(qn('w:val'), 'Heading2')
pPr.append(pStyle)
h_frac.append(pPr)
run = h_frac.makeelement(qn('w:r'), {})
t = run.makeelement(qn('w:t'), {})
t.text = "Fracture Assessment"
run.append(t)
h_frac.append(run)
insert_before.addprevious(h_frac)

intro_frac = _insert_normal(doc, h_frac,
    "The Fracture Assessment engine evaluates materials against NASA-STD-5009C and "
    "NASA-STD-5019A fracture control requirements. It determines fracture criticality, "
    "screens for damage tolerance, and identifies inspection and analysis requirements "
    "for safety-critical hardware.")
bullets_fracture = [
    "Fracture criticality classification: fracture-critical, low-risk, non-fracture-critical per NASA-STD-5009C",
    "Damage tolerance screening with KIc (fracture toughness) and da/dN (crack growth rate) data from MAPTIS",
    "Safe-life and fail-safe analysis routing based on hardware classification and mission type",
    "NDE (Non-Destructive Evaluation) requirement identification with inspection interval recommendations",
    "Integration with MUA Writer: fracture flag triggers automatic MUA classification and rationale generation",
    "Crewed vs. uncrewed mission classification with human-rated hardware screening gates",
]
prev = intro_frac
for b in bullets_fracture:
    prev = _insert_bullet(doc, prev, b)

print("  [+] Added Fracture Assessment section")


# ---------------------------------------------------------------------------
# 4. MIRA Chat (new Heading 2 after M&P Plan Generator, before Architecture)
# ---------------------------------------------------------------------------
arch_idx = _find_paragraph_index(doc, text_startswith="Architecture", style_name="Heading 1")
if arch_idx is None:
    print("ERROR: Could not find 'Architecture & Security' heading")
    sys.exit(1)

arch_elem = doc.paragraphs[arch_idx]._element

h_chat = arch_elem.makeelement(qn('w:p'), {})
pPr = h_chat.makeelement(qn('w:pPr'), {})
pStyle = pPr.makeelement(qn('w:pStyle'), {})
pStyle.set(qn('w:val'), 'Heading2')
pPr.append(pStyle)
h_chat.append(pPr)
run = h_chat.makeelement(qn('w:r'), {})
t = run.makeelement(qn('w:t'), {})
t.text = "MIRA Chat"
run.append(t)
h_chat.append(run)
arch_elem.addprevious(h_chat)

intro_chat = _insert_normal(doc, h_chat,
    "MIRA Chat is a multi-turn conversational interface that lets engineers ask questions "
    "in natural language and receive evidence-grounded answers dispatched through MIRA\u2019s "
    "validated engine pipeline. Unlike general-purpose chatbots, every response is produced "
    "by a deterministic engine\u2014the language model formats the answer, it never makes the decision.")
bullets_chat = [
    "Natural language query interpretation: three-stage pipeline (intent classification \u2192 entity extraction \u2192 task routing)",
    "Automatic engine dispatch: OCA, H2, Galvanic, Fracture, MAPTIS, and BSMH engines selected based on query content",
    "Multi-turn conversation with entity inheritance: \u201cWhat about at 1500 psi?\u201d carries material and environment from prior turns",
    "Senior M&P engineer persona: responses explain verdicts conversationally, not as data dumps",
    "Three task modes: answer questions, generate draft artifacts (MUAs, rationale entries), or review existing documents",
    "Code-based grader validates every response against spec non-negotiables before delivery",
    "Full audit trail: every interaction logged with parsed entities, engine verdicts, citations, and response hashes",
    "REFUSE gate: if an engine refuses, the chat refuses\u2014no softening, no workaround, no override",
    "Phase 2: SSE streaming, multi-engine auto-chaining with approval gates, PostgreSQL persistence",
]
prev = intro_chat
for b in bullets_chat:
    prev = _insert_bullet(doc, prev, b)

print("  [+] Added MIRA Chat section")


# ---------------------------------------------------------------------------
# 5. Update stats table: 8 → 12 modules
# ---------------------------------------------------------------------------
stats_table = doc.tables[0]
# First cell should say "8\nProduction Modules..."
cell = stats_table.rows[0].cells[0]
old_text = cell.text
if "8" in old_text:
    for p in cell.paragraphs:
        for run in p.runs:
            if "8" in run.text:
                run.text = run.text.replace("8", "12", 1)
                break
        break
    print("  [+] Updated stats table: 8 → 12 Production Modules")
else:
    print(f"  [!] Stats cell text unexpected: {old_text[:50]}")


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------
doc.save(str(DST))
print(f"\nSaved → {DST}")
