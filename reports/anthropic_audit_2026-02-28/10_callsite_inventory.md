# Anthropic/Claude Callsite Inventory (MIRA)

| Status | File | Call line(s) | Primary model ref | What it does |
|---|---|---|---|---|
| active | `athena/extraction/bok/extractor_v10.py` | `480:    response = client.messages.create(` | `claude-haiku-4-5-20251001` | ATHENA extraction/vision parsing |
| active | `athena/extraction/bok/standards_extractor_v6.py` | `476:        response = client.messages.create( | 520:        response = client.messages.create(` | `claude-sonnet-4-5-20250929` | ATHENA extraction/vision parsing |
| active | `athena/extraction/detector.py` | `147:            response = self.client.messages.create(` | `claude-sonnet-4-20250514` | ATHENA extraction/vision parsing |
| active | `athena/extraction/haiku_vision.py` | `154:        resp = self.client.messages.create(` | `claude-3-haiku-20240307` | ATHENA extraction/vision parsing |
| active | `athena/extraction/standards_extractor.py` | `258:        response = self.client.messages.create(` | `claude-sonnet-4-20250514` | ATHENA extraction/vision parsing |
| active | `athena/extraction/transcriber.py` | `124:            response = self.client.messages.create(` | `claude-sonnet-4-20250514` | ATHENA extraction/vision parsing |
| legacy_or_script | `athena/legacy/v6.py` | `475:        response = client.messages.create( | 519:        response = client.messages.create(` | `claude-sonnet-4-5-20250929` | Legacy/archive module |
| legacy_or_script | `athena/legacy/v7.py` | `845:        response = client.messages.create(` | `claude-haiku-4-5-20251001` | Legacy/archive module |
| legacy_or_script | `athena/legacy/v8.py` | `647:        response = client.messages.create(` | `claude-haiku-4-5-20251001` | Legacy/archive module |
| active | `athena/providers/anthropic.py` | `93:        response = self.client.messages.create( | 136:        response = self.client.messages.create(` | `claude-3-5-haiku-20241022` | ATHENA LLM provider adapter |
| active | `athena/providers/bedrock.py` | `91:        response = self.client.messages.create( | 134:        response = self.client.messages.create( | 214:        response = self.client.messages.create( | 252:        response = self.client.messages.create(` | `claude-3-5-haiku-20241022` | ATHENA LLM provider adapter |
| active | `core/evidence/llm_answer_generator.py` | `712:                message = self.haiku_client.client.messages.create(` | `claude-3-haiku-20240307` | Legacy evidence explanation generation |
| active | `data_laundering/bedrock_client.py` | `342:    #         resp = await client.invoke_model( | 384:    #         resp = await client.invoke_model( | 427:    #         resp = await client.invoke_model(` | `anthropic.claude-sonnet-4-5-20250929-v1:0` | Data laundering Bedrock client scaffolding |
| legacy_or_script | `mira/MIRA_V2/src/haiku_client.py` | `56:            message = self.client.messages.create(` | `claude-3-haiku-20240307` | Legacy/archive module |
| legacy_or_script | `mira/MIRA_V2/src/llm_answer_generator.py` | `712:                message = self.haiku_client.client.messages.create(` | `claude-3-haiku-20240307` | Legacy/archive module |
| active | `mira/api/routers/mira_v4.py` | `327:            message = client.messages.create( | 478:            message = client.messages.create(` | `anthropic.claude-sonnet-4-5-20250929-v1:0` | MIRA v4 query parse+answer generation |
| active | `mira/bsmh/bouncer.py` | `622:        message = client.messages.create(` | `claude-haiku-4-5-20251001` | BSMH safety/scope gate classification |
| active | `mira/bsmh/response_formatter.py` | `402:            message = client.messages.create( | 480:        message = client.messages.create( | 671:        message = client.messages.create(` | `anthropic.claude-3-haiku-20240307-v1:0` | BSMH response narrative formatting |
| active | `mira/bsmh/service.py` | `914:        message = client.messages.create(` | `claude-sonnet-4-5-20250929` | BSMH fracture-context parsing |
| active | `mira/knowledge_twins/bok_extractor_v10.py` | `480:    response = client.messages.create(` | `claude-haiku-4-5-20251001` | Knowledge twin/BOK extraction |
| active | `mira/knowledge_twins/bok_extractor_v7.py` | `846:        response = client.messages.create(` | `claude-haiku-4-5-20251001` | Knowledge twin/BOK extraction |
| active | `mira/knowledge_twins/bok_extractor_v8.py` | `648:        response = client.messages.create(` | `claude-haiku-4-5-20251001` | Knowledge twin/BOK extraction |
| active | `mira/knowledge_twins/bok_standards_extractor_v6.py` | `476:        response = client.messages.create( | 520:        response = client.messages.create(` | `claude-sonnet-4-5-20250929` | Knowledge twin/BOK extraction |
| active | `mira/knowledge_twins/extract h2.py` | `200:    response = client.messages.create(` | `claude-sonnet-4-20250514` | Knowledge twin/BOK extraction |
| active | `mira/maptis/pdf_extractor.py` | `232:        response = client.messages.create(` | `claude-sonnet-4-5-20250929` | MAPTIS PDF vision extraction |
| active | `mira/miul/material_code_selector.py` | `208:            message = self.client.messages.create(` | `claude-3-haiku-20240307` | MIUL material code selection |
| active | `mira/miul/mua_parser_v6.py` | `331:        response = client.messages.create( | 402:        response = client.messages.create(` | `claude-sonnet-4-5-20250929` | MIUL MUA form parser |
| active | `mira/miul/mua_synthesizer.py` | `468:            response = self.client.messages.create( | 544:            response = self.client.messages.create(` | `claude-sonnet-4-5-20250929` | MIUL precedent synthesis/rationale |
| legacy_or_script | `mira/miul/v1_archive/drawing_inventory.py` | `230:        response = self.client.messages.create(` | `claude-sonnet-4-5-20250929` | Legacy/archive module |
| legacy_or_script | `mira/miul/v1_archive/dt_miul_builder.py` | `411:        response = client.messages.create( | 751:            response = client.messages.create( | 1206:            response = client.messages.create( | 1361:            response = client.messages.create(` | `claude-sonnet-4-20250514` | Legacy/archive module |
| legacy_or_script | `mira/miul/v1_archive/extractors/haiku_drawing_extractor.py` | `293:            response = self.client.messages.create(` | `claude-sonnet-4-5-20250929` | Legacy/archive module |
| legacy_or_script | `mira/miul/v1_archive/haiku_bom_extractor.py` | `154:        resp = self.client.messages.create(` | `claude-3-haiku-20240307` | Legacy/archive module |
| legacy_or_script | `mira/miul/v1_archive/haiku_bom_extractor_old.py` | `270:            message = self.client.messages.create( | 332:            message = self.client.messages.create(` | `claude-3-haiku-20240307` | Legacy/archive module |
| legacy_or_script | `mira/miul/v1_archive/miul_extractor_v2.py` | `174:        resp = self.client.messages.create(` | `claude-sonnet-4-5-20250929` | Legacy/archive module |
| legacy_or_script | `mira/miul/v1_archive/msfc/extractor.py` | `560:            response = self.client.messages.create(` | `claude-3-haiku-20240307` | Legacy/archive module |
| legacy_or_script | `mira/miul/v1_archive/parts_inventory_extractor.py` | `504:            response = self.client.messages.create(` | `claude-sonnet-4-5-20250929` | Legacy/archive module |
| legacy_or_script | `mira/miul/v1_archive/stages/parse_drawings.py` | `345:        response = client.messages.create( | 444:        response = client.messages.create(` | `claude-sonnet-4-20250514` | Legacy/archive module |
| legacy_or_script | `mira/miul/v1_archive/stages/parse_dt.py` | `231:    response = client.messages.create(` | `claude-sonnet-4-20250514` | Legacy/archive module |
| active | `mira/miul/v2/cli.py` | `(no direct create in this file)` | `(see model refs)` | MIUL v2 client wiring (calls delegated) |
| active | `mira/miul/v2/extract.py` | `264:    message = anthropic_client.messages.create(` | `claude-sonnet-4-20250514` | MIUL v2 drawing vision extraction |
| active | `mira/miul/v2/graph.py` | `180:    message = anthropic_client.messages.create(` | `claude-sonnet-4-20250514` | MIUL v2 drawing-tree extraction |
| active | `mira/miul/v3/extract.py` | `303:            response = self.client.messages.create( | 1215:        response = client.client.messages.create(**api_kwargs) | 1281:        response = client.client.messages.create( | 1505:        response = client.client.messages.create(` | `claude-sonnet-4-5-20250929` | MIUL v3 extraction/validation |
| active | `mira/mua/final/renderer.py` | `309:        response = client.messages.create(` | `claude-sonnet-4-5-20250929` | MUA final renderer |
| active | `mira/mua/v6/logic_validator.py` | `175:            message = self._client.messages.create(` | `claude-3-5-haiku-20241022` | MUA rationale logic validation |
| active | `mira/mua/v7/draft_polish.py` | `259:        response = client.messages.create(` | `claude-sonnet-4-5-20250929` | MUA draft language polish |
| active | `mira/mua/v8/renderer.py` | `297:        response = client.messages.create(` | `claude-sonnet-4-5-20250929` | MUA v8 renderer |
| active | `mira/precedent_engine/core/narrator.py` | `151:        response = client.invoke_model(` | `(see model refs)` | Precedent narrator (Bedrock invoke_model) |
| active | `mira/precedent_engine/utils/bedrock.py` | `65:        response = bedrock.invoke_model(` | `(see model refs)` | Precedent Bedrock utility invocation |
| legacy_or_script | `scripts/drawing_tree_extractor.py` | `97:    response = client.messages.create( | 179:    response = client.messages.create(` | `claude-sonnet-4-20250514` | Script/test utility |
| legacy_or_script | `scripts/extract_fc_vision_v2.py` | `90:    response = client.messages.create(` | `claude-sonnet-4-5-20250929` | Script/test utility |
| legacy_or_script | `scripts/test_material_debug.py` | `43:response = client.messages.create(` | `claude-sonnet-4-20250514` | Script/test utility |
| legacy_or_script | `scripts/test_material_extraction.py` | `68:    response = client.messages.create(` | `claude-sonnet-4-20250514` | Script/test utility |
| sentinel | `sentinel-main/gptl/claude_client.py` | `504:                response = self._client.messages.create(**kwargs)` | `claude-3-5-haiku-20241022` | SENTINEL shared Claude client |
