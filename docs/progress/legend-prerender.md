# Progress: Local Pre-rendered Legends

**Related Plan:** [Plan](../plans/legend-prerender.md)

## Tasks
- [x] Refactor legend endpoint into `GetLayerLegendUseCase` (previous turn)
- [x] Create plan + progress docs
- [x] Extract shared `resolve_layer_source_path()`
- [x] Create `legend_renderer.py`
- [x] Extend `GetLayerLegendUseCase` for local types
- [x] Update endpoint wiring (session repo)
- [x] Tests pass (20 passed)
- [x] Final feature doc — [Feature](../features/legend-prerender.md)

## Log
- 2024: initial usecase refactor — `wms`, `wmts`, esri family covered; others `available: false`.
- 2024: plan approved — prerender local legends via Pillow + static `/tiles/` mount.